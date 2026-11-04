/**
 * Owner session: restore, login, logout, CSRF rotation.
 * Tokens live in memory only — never localStorage/sessionStorage/URLs.
 */

import type { QueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, configureApi } from "../api/client";
import * as api from "../api/endpoints";

export type SessionStatus = "booting" | "authed" | "anon";

interface SessionContextValue {
  status: SessionStatus;
  sessionId: string | null;
  expiresAt: string | null;
  /** True when a live session died (vs never logged in). */
  expired: boolean;
  login: (pin: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}

export function SessionProvider({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: ReactNode;
}): React.JSX.Element {
  const [status, setStatus] = useState<SessionStatus>("booting");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const csrfRef = useRef<string | null>(null);
  const refreshFlight = useRef<Promise<boolean> | null>(null);
  const queryRef = useRef(queryClient);
  queryRef.current = queryClient;

  const storeCsrf = useCallback((token: string | null) => {
    csrfRef.current = token;
  }, []);

  const clearAll = useCallback(() => {
    storeCsrf(null);
    setSessionId(null);
    setExpiresAt(null);
    queryRef.current.clear();
  }, [storeCsrf]);

  const handleUnauthorized = useCallback(() => {
    // Idempotent: simultaneous 401s collapse into one state change.
    setStatus((prev) => {
      if (prev !== "anon") {
        setExpired(true);
        clearAll();
        return "anon";
      }
      return prev;
    });
  }, [clearAll]);

  const handleCsrfRejected = useCallback((): Promise<boolean> => {
    if (!refreshFlight.current) {
      refreshFlight.current = (async () => {
        try {
          const fresh = await api.refreshCsrf();
          storeCsrf(fresh.csrf_token);
          return true;
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            handleUnauthorized();
          }
          return false;
        } finally {
          refreshFlight.current = null;
        }
      })();
    }
    return refreshFlight.current;
  }, [handleUnauthorized, storeCsrf]);

  useEffect(() => {
    configureApi({
      getCsrf: () => csrfRef.current,
      onUnauthorized: handleUnauthorized,
      onCsrfRejected: handleCsrfRejected,
    });
  }, [handleUnauthorized, handleCsrfRejected]);

  // Session restore: the HttpOnly cookie survives refresh; the CSRF token
  // does not (in-memory by design) and is rotated lazily on first 403.
  useEffect(() => {
    let cancelled = false;
    api
      .fetchMe()
      .then((me) => {
        if (cancelled) return;
        if (me.authenticated && me.session_id) {
          setSessionId(me.session_id);
          setExpiresAt(me.expires_at);
          setExpired(false);
          setStatus("authed");
        } else {
          setStatus("anon");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("anon");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (pin: string) => {
      clearAll();
      setExpired(false);
      const done = await api.login(pin);
      storeCsrf(done.csrf_token);
      setSessionId(done.session_id);
      setExpiresAt(done.expires_at);
      setStatus("authed");
    },
    [clearAll, storeCsrf],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Best effort: local state is cleared regardless so no sensitive
      // material lingers after the user asked to leave.
    }
    setExpired(false);
    clearAll();
    setStatus("anon");
  }, [clearAll]);

  const value = useMemo<SessionContextValue>(
    () => ({ status, sessionId, expiresAt, expired, login, logout }),
    [status, sessionId, expiresAt, expired, login, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

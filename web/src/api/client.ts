/**
 * Single API client: credentials, CSRF, envelope errors, timeouts, aborts.
 * No secrets here; auth state lives in the session provider (in-memory).
 */

import { config } from "../config";
import type { ApiErrorEnvelope } from "./types";

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly requestId: string | null;
  readonly aborted: boolean;

  constructor(
    message: string,
    opts: { status?: number | null; code?: string; requestId?: string | null; aborted?: boolean } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status ?? null;
    this.code = opts.code ?? "E_INTERNAL";
    this.requestId = opts.requestId ?? null;
    this.aborted = opts.aborted ?? false;
  }
}

interface ApiRegistry {
  getCsrf: () => string | null;
  onUnauthorized: () => void;
  /** Refresh the CSRF token; resolves true when a retry may proceed. */
  onCsrfRejected: () => Promise<boolean>;
}

const registry: ApiRegistry = {
  getCsrf: () => null,
  onUnauthorized: () => undefined,
  onCsrfRejected: () => Promise.resolve(false),
};

export function configureApi(next: Partial<ApiRegistry>): void {
  Object.assign(registry, next);
}

export interface FetchOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal | null;
  timeoutMs?: number;
  /** Attach the in-memory CSRF token (cookie-auth mutations). */
  needsCsrf?: boolean;
  /** Skip the global 401 handler (login/boot calls handle it locally). */
  skipAuthHandler?: boolean;
}

function envelopeFromJson(body: unknown, fallback: string): { code: string; message: string; requestId: string | null } {
  if (typeof body === "object" && body !== null) {
    const err = (body as Partial<ApiErrorEnvelope>).error;
    if (err && typeof err === "object") {
      const rec = err as Record<string, unknown>;
      return {
        code: typeof rec.code === "string" ? rec.code : "E_INTERNAL",
        message: typeof rec.message === "string" ? rec.message : fallback,
        requestId: typeof rec.request_id === "string" ? rec.request_id : null,
      };
    }
  }
  return { code: "E_INTERNAL", message: fallback, requestId: null };
}

function isCsrfRejection(status: number, code: string, message: string): boolean {
  return status === 403 && code === "E_AUTH" && /csrf/i.test(message);
}

async function request(
  path: string,
  opts: FetchOptions,
  retried: boolean,
): Promise<Response> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;
  if (opts.form !== undefined) {
    body = opts.form; // browser sets the multipart boundary
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  if (opts.needsCsrf) {
    const token = registry.getCsrf();
    if (token) headers["X-CSRF-Token"] = token;
  }

  const controller = new AbortController();
  let timedOut = false;
  const timeoutMs = opts.timeoutMs ?? config.defaultTimeoutMs;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onExternalAbort = (): void => controller.abort();
  opts.signal?.addEventListener("abort", onExternalAbort, { once: true });

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body,
      credentials: "include",
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        timedOut ? "The request timed out." : "The request was cancelled.",
        { code: timedOut ? "E_NETWORK" : "E_ABORTED", aborted: !timedOut },
      );
    }
    throw new ApiError("Cannot reach the server.", { code: "E_NETWORK" });
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onExternalAbort);
  }

  if (response.status === 401 && !opts.skipAuthHandler) {
    registry.onUnauthorized();
  }
  if (
    !retried &&
    opts.needsCsrf &&
    response.status === 403
  ) {
    // Peek for a CSRF rejection: validate_csrf runs before any service
    // logic, so a failed first attempt never mutated anything — one retry
    // with a rotated token is safe.
    const clone = response.clone();
    const text = await clone.text().catch(() => "");
    let parsed: unknown = null;
    try {
      parsed = text ? (JSON.parse(text) as unknown) : null;
    } catch {
      parsed = null;
    }
    const info = envelopeFromJson(parsed, "Forbidden");
    if (isCsrfRejection(response.status, info.code, info.message)) {
      const mayRetry = await registry.onCsrfRejected();
      if (mayRetry) return request(path, opts, true);
    }
  }
  return response;
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text().catch(() => "");
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = text ? (JSON.parse(text) as unknown) : null;
    } catch {
      parsed = null;
    }
    const info = envelopeFromJson(parsed, `Request failed (${response.status})`);
    throw new ApiError(info.message, {
      status: response.status,
      code: info.code,
      requestId: info.requestId,
    });
  }
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("The server returned an unreadable response.", {
      status: response.status,
      code: "E_INTERNAL",
    });
  }
}

/** JSON request with envelope error mapping. */
export async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const response = await request(path, opts, false);
  return parseJson<T>(response);
}

/** Authenticated raw-bytes request (artifact preview). */
export async function apiBytes(path: string, opts: FetchOptions = {}): Promise<Blob> {
  const response = await request(path, opts, false);
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let parsed: unknown = null;
    try {
      parsed = text ? (JSON.parse(text) as unknown) : null;
    } catch {
      parsed = null;
    }
    const info = envelopeFromJson(parsed, `Request failed (${response.status})`);
    throw new ApiError(info.message, {
      status: response.status,
      code: info.code,
      requestId: info.requestId,
    });
  }
  return response.blob();
}

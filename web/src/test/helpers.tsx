/** Shared UI test harness: providers, router, stubbed fetch. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, vi, type Mock } from "vitest";
import type { ReactElement } from "react";
import { SessionProvider } from "../auth/session";
import { ToastProvider } from "../components/overlays";

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function envelope(code: string, message: string, requestId = "req_test"): Record<string, unknown> {
  return { error: { code, message, request_id: requestId, details: [] } };
}

export type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Install a global fetch stub; restored automatically after each test. */
export function stubFetch(handler: FetchHandler): Mock {
  const mock = vi.fn(handler) as Mock;
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/" }: { route?: string } = {},
): RenderResult {
  const client = testQueryClient();
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <ToastProvider>
          <SessionProvider queryClient={client}>{ui}</SessionProvider>
        </ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

/** Render the real App routes (integration-style) at one entry path. */
export function renderAppAt(App: () => React.JSX.Element, route: string): RenderResult {
  const client = testQueryClient();
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <ToastProvider>
          <SessionProvider queryClient={client}>
            <App />
          </SessionProvider>
        </ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

export function RouteProbe({ expected }: { expected: string }): React.JSX.Element {
  return (
    <Routes>
      <Route path="*" element={<span data-testid="route-probe">{expected}</span>} />
    </Routes>
  );
}

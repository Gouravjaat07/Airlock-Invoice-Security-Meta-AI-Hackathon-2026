import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiBytes, apiFetch, configureApi } from "./client";
import { envelope, jsonResponse, stubFetch } from "../test/helpers";

beforeEach(() => {
  configureApi({
    getCsrf: () => null,
    onUnauthorized: () => undefined,
    onCsrfRejected: () => Promise.resolve(false),
  });
});

describe("apiFetch", () => {
  it("returns parsed JSON on success", async () => {
    stubFetch(() => jsonResponse({ ok: true }));
    await expect(apiFetch("/api/v1/health")).resolves.toEqual({ ok: true });
  });

  it("sends credentials and JSON bodies", async () => {
    const fetchMock = stubFetch(() => jsonResponse({}));
    await apiFetch("/api/v1/auth/login", { method: "POST", json: { pin: "x" } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ pin: "x" }));
  });

  it("maps the error envelope to ApiError fields", async () => {
    stubFetch(() => jsonResponse(envelope("E_RATE_LIMIT", "Slow down", "req_1"), 429));
    const error = (await apiFetch("/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(429);
    expect(error.code).toBe("E_RATE_LIMIT");
    expect(error.message).toBe("Slow down");
    expect(error.requestId).toBe("req_1");
  });

  it("rejects malformed JSON bodies", async () => {
    stubFetch(() => new Response("{nope", { status: 200 }));
    await expect(apiFetch("/x")).rejects.toMatchObject({ code: "E_INTERNAL" });
  });

  it("maps network failure to E_NETWORK", async () => {
    stubFetch(() => {
      throw new TypeError("fetch failed");
    });
    await expect(apiFetch("/x")).rejects.toMatchObject({ code: "E_NETWORK" });
  });

  it("aborts on timeout", async () => {
    stubFetch((_url, init) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    await expect(apiFetch("/x", { timeoutMs: 5 })).rejects.toMatchObject({ code: "E_NETWORK" });
  });

  it("does not set Content-Type for multipart forms", async () => {
    const fetchMock = stubFetch(() => jsonResponse({}));
    await apiFetch("/api/v1/cases", { method: "POST", form: new FormData() });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("attaches the CSRF token to flagged mutations", async () => {
    configureApi({ getCsrf: () => "csrf_abc" });
    const fetchMock = stubFetch(() => jsonResponse({}));
    await apiFetch("/api/v1/cases/c/reject", { method: "POST", needsCsrf: true });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf_abc");
  });

  it("fires the 401 handler unless skipped", async () => {
    const onUnauthorized = vi.fn();
    configureApi({ onUnauthorized });
    stubFetch(() => jsonResponse(envelope("E_AUTH", "nope"), 401));
    await expect(apiFetch("/x")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    await expect(apiFetch("/x", { skipAuthHandler: true })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("retries once after CSRF rotation, then gives up", async () => {
    configureApi({ getCsrf: () => "stale", onCsrfRejected: () => Promise.resolve(true) });
    let calls = 0;
    const fetchMock = stubFetch(() => {
      calls += 1;
      return jsonResponse(envelope("E_AUTH", "Invalid CSRF token"), 403);
    });
    await expect(
      apiFetch("/api/v1/cases/c/reject", { method: "POST", needsCsrf: true }),
    ).rejects.toMatchObject({ status: 403 });
    expect(calls).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry non-CSRF 403 responses", async () => {
    const onCsrfRejected = vi.fn(() => Promise.resolve(true));
    configureApi({ onCsrfRejected });
    stubFetch(() => jsonResponse(envelope("E_AUTH", "Forbidden"), 403));
    await expect(apiFetch("/x", { needsCsrf: true })).rejects.toBeInstanceOf(ApiError);
    expect(onCsrfRejected).not.toHaveBeenCalled();
  });
});

describe("apiBytes", () => {
  it("returns blobs on success and envelope errors on failure", async () => {
    stubFetch(() => new Response("PDF!", { status: 200 }));
    const blob = await apiBytes("/content");
    expect(await blob.text()).toBe("PDF!");
  });
});

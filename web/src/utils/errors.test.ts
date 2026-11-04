import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { isCsrfError, isRateLimitError, isSessionError, safeMessage } from "./errors";

describe("safeMessage", () => {
  it("prefers the sanitized backend message for known codes", () => {
    const error = new ApiError("Too many attempts. Try again later.", {
      status: 429,
      code: "E_RATE_LIMIT",
    });
    expect(safeMessage(error)).toBe("Too many attempts. Try again later.");
  });

  it("falls back to mapped copy when the message is empty", () => {
    const error = new ApiError("", { status: 503, code: "E_API_UNAVAILABLE" });
    expect(safeMessage(error)).toBe("A model provider is unavailable right now.");
  });

  it("handles non-ApiError input", () => {
    expect(safeMessage(new Error("boom"))).toBe("boom");
    expect(safeMessage(null)).toBe("Something went wrong.");
  });
});

describe("predicates", () => {
  it("detects session, CSRF, and rate-limit failures", () => {
    expect(isSessionError(new ApiError("x", { status: 401, code: "E_AUTH" }))).toBe(true);
    expect(isSessionError(new ApiError("x", { status: 403, code: "E_AUTH" }))).toBe(false);
    expect(isCsrfError(new ApiError("Invalid CSRF token", { status: 403, code: "E_AUTH" }))).toBe(true);
    expect(isCsrfError(new ApiError("Forbidden", { status: 403, code: "E_OTHER" }))).toBe(false);
    expect(isRateLimitError(new ApiError("x", { status: 429, code: "E_RATE_LIMIT" }))).toBe(true);
  });
});

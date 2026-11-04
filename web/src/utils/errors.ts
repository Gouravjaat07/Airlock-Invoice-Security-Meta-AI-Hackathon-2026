/** Backend error codes → safe UI copy. Raw traces/paths never rendered. */

import { ApiError } from "../api/client";

const CODE_MESSAGES: Record<string, string> = {
  E_UPLOAD: "The uploaded files were rejected. Check the file types and sizes and try again.",
  E_SCHEMA: "The request or stored data failed validation.",
  E_READER_UNAVAILABLE: "Document extraction is unavailable right now.",
  E_READER_TIMEOUT: "Document extraction timed out.",
  E_API_UNAVAILABLE: "A model provider is unavailable right now.",
  E_AUTH: "Authentication failed.",
  E_RATE_LIMIT: "Too many attempts. Wait a little and try again.",
  E_EXPIRED: "This item has expired.",
  E_DUPLICATE: "This invoice was already submitted.",
  E_POLICY_DENY: "Policy denied this action.",
  E_POLICY_ESCALATE: "Policy requires owner review before this action.",
  E_CONFLICT: "A conflicting change happened. Refresh and try again.",
  E_STATE_TRANSITION: "This action is not allowed in the current state.",
  E_AUDIT: "Audit verification failed.",
  E_STORAGE: "Artifact storage is unavailable.",
  E_DATABASE: "The database is unavailable.",
  E_INTERNAL: "Something went wrong on the server.",
  E_NETWORK: "Cannot reach the server. Check your connection.",
  E_ABORTED: "The request was cancelled.",
};

export function safeMessage(error: unknown): string {
  if (error instanceof ApiError) {
    // Prefer the backend message when it is a known-safe code message shape;
    // fall back to the mapped copy. Backend messages are already sanitized
    // server-side, but never render details/raw payloads.
    if (error.code && CODE_MESSAGES[error.code]) {
      return error.message && error.message !== error.code
        ? error.message
        : CODE_MESSAGES[error.code];
    }
    return error.message || "Something went wrong.";
  }
  if (error instanceof Error) return error.message || "Something went wrong.";
  return "Something went wrong.";
}

export function isSessionError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function isCsrfError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    /csrf/i.test(error.message)
  );
}

export function isRateLimitError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 429;
}

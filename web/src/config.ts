/** Console configuration. Same-origin by default; only non-secret values here. */

function baseUrl(): string {
  const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
  return raw.replace(/\/+$/, "");
}

export const config = {
  /** "" = same origin (dev proxy / reverse proxy). Never a secret. */
  apiBaseUrl: baseUrl(),
  /** Default fetch timeout for quick calls. Long calls override per-call. */
  defaultTimeoutMs: 30_000,
  /** Processing can run minutes of model calls server-side. */
  processTimeoutMs: 10 * 60_000,
  /** Intake pre-checks mirror backend *defaults*; the server is authoritative. */
  intake: {
    maxFiles: 5,
    maxBytesPerFile: 10 * 1024 * 1024,
    invoiceAccept: [".pdf", ".png", ".jpg", ".jpeg"],
    deliveryAccept: [".png", ".jpg", ".jpeg", ".mp4"],
    voiceAccept: [".wav"],
  },
} as const;

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: same-origin through the /api proxy (backend has no CORS by design).
// Production: serve web/dist behind the same origin as the API (reverse
// proxy) so cookies + CSRF keep working without code changes.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  preview: { port: 4173, strictPort: true },
  build: { sourcemap: false, outDir: "dist" },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});

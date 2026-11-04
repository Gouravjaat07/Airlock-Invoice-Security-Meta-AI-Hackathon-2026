import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";

// Explicit imports (no vitest globals), so register cleanup manually.
afterEach(() => {
  cleanup();
});

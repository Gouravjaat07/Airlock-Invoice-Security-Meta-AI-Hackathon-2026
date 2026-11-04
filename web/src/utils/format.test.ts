import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatMoney,
  humanizeState,
  shortRef,
} from "./format";

describe("formatBytes", () => {
  it("formats bytes and larger units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
  });

  it("rejects non-finite and negative input", () => {
    expect(formatBytes(Number.NaN)).toBe("—");
    expect(formatBytes(-5)).toBe("—");
  });
});

describe("formatDateTime / formatDate", () => {
  it("returns an em dash for empty input", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
  });

  it("passes invalid strings through instead of crashing", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });

  it("formats valid ISO timestamps", () => {
    expect(formatDateTime("2026-01-15T10:30:00+00:00")).not.toBe("—");
    expect(formatDate("2026-02-01")).not.toBe("—");
  });
});

describe("shortRef", () => {
  it("truncates long references", () => {
    expect(shortRef("case_0123456789abcdef")).toBe("case_012…");
    expect(shortRef("short")).toBe("short");
    expect(shortRef(null)).toBe("—");
  });
});

describe("formatMoney", () => {
  it("passes backend strings through untouched", () => {
    expect(formatMoney("1240.00", "INR")).toBe("1240.00 INR");
    expect(formatMoney("1240.00", null)).toBe("1240.00");
    expect(formatMoney(null, "INR")).toBe("—");
    expect(formatMoney("", "INR")).toBe("—");
  });
});

describe("humanizeState", () => {
  it("title-cases snake state", () => {
    expect(humanizeState("NEEDS_REVIEW")).toBe("Needs Review");
    expect(humanizeState("MOCK_COMPLETED")).toBe("Mock Completed");
  });
});

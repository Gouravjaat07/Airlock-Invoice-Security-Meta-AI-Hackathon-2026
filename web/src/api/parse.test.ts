import { describe, expect, it } from "vitest";
import { factValue, parseVerdict } from "./parse";
import type { VerdictRow } from "./types";

function row(overrides: Partial<VerdictRow> = {}): VerdictRow {
  return {
    verdict_id: "v1",
    case_id: "c1",
    verdict: "DENY",
    reasons_json: JSON.stringify(["R2"]),
    rule_ids_json: JSON.stringify(["R1", "R2"]),
    rule_details_json: JSON.stringify([
      { rule_id: "R1", passed: true, reason_code: "ok", message: "fine", evidence: {} },
      { rule_id: "R2", passed: false, reason_code: "mismatch", message: "bad", evidence: { a: 1 } },
    ]),
    policy_version: "2.0.0",
    created_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

describe("parseVerdict", () => {
  it("parses a healthy row without degradation", () => {
    const parsed = parseVerdict(row());
    expect(parsed.degraded).toBe(false);
    expect(parsed.reasons).toEqual(["R2"]);
    expect(parsed.rules).toHaveLength(2);
    expect(parsed.rules[1].passed).toBe(false);
  });

  it("flags corrupt columns instead of throwing", () => {
    const parsed = parseVerdict(row({ rule_details_json: "{nope" }));
    expect(parsed.degraded).toBe(true);
    expect(parsed.rules).toEqual([]);
  });

  it("drops malformed rule entries and flags degradation", () => {
    const parsed = parseVerdict(
      row({ rule_details_json: JSON.stringify([{ rule_id: "R1" }]) }),
    );
    expect(parsed.degraded).toBe(true);
    expect(parsed.rules).toEqual([]);
  });

  it("rejects non-list payloads", () => {
    const parsed = parseVerdict(row({ reasons_json: JSON.stringify({}) }));
    expect(parsed.degraded).toBe(true);
    expect(parsed.reasons).toEqual([]);
  });
});

describe("factValue", () => {
  it("finds values by field name", () => {
    expect(factValue<string>([{ field: "total", value: "10" }], "total")).toBe("10");
    expect(factValue<string>([{ field: "total", value: "10" }], "missing")).toBeUndefined();
  });
});

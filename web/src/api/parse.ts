/** Safe parsers for backend JSON-string columns. Never throw on bad data. */

import type { RuleDetail, VerdictRow } from "./types";

export interface ParsedVerdict {
  reasons: string[];
  ruleIds: string[];
  rules: RuleDetail[];
  /** True when any column failed to parse (UI must say so, not hide it). */
  degraded: boolean;
}

function parseList(raw: string): { items: unknown[]; ok: boolean } {
  try {
    const value: unknown = JSON.parse(raw);
    if (Array.isArray(value)) return { items: value, ok: true };
    return { items: [], ok: false };
  } catch {
    return { items: [], ok: false };
  }
}

function isRuleDetail(value: unknown): value is RuleDetail {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.rule_id === "string" &&
    typeof v.passed === "boolean" &&
    typeof v.reason_code === "string" &&
    typeof v.message === "string" &&
    typeof v.evidence === "object" &&
    v.evidence !== null
  );
}

export function parseVerdict(row: VerdictRow): ParsedVerdict {
  const reasons = parseList(row.reasons_json);
  const ruleIds = parseList(row.rule_ids_json);
  const details = parseList(row.rule_details_json);
  const rules: RuleDetail[] = [];
  let rulesOk = details.ok;
  for (const item of details.items) {
    if (isRuleDetail(item)) rules.push(item);
    else rulesOk = false;
  }
  return {
    reasons: reasons.items.filter(
      (r): r is string => typeof r === "string",
    ),
    ruleIds: ruleIds.items.filter(
      (r): r is string => typeof r === "string",
    ),
    rules,
    degraded: !reasons.ok || !ruleIds.ok || !rulesOk,
  };
}

/** Typed field access for fact values; returns undefined when absent. */
export function factValue<T>(facts: { field: string; value: unknown }[], field: string): T | undefined {
  const found = facts.find((f) => f.field === field);
  return found ? (found.value as T) : undefined;
}

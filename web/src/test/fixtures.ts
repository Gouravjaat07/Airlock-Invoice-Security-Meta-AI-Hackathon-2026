/** Contract fixtures mirroring real backend shapes (never production data). */

import type {
  CaseSummary,
  HealthResponse,
  ProposalRow,
  ProvidersResponse,
  ProviderStatusItem,
  VerdictRow,
} from "../api/types";

export function verdictRow(overrides: Partial<VerdictRow> = {}): VerdictRow {
  return {
    verdict_id: "verdict_1",
    case_id: "case_1",
    verdict: "ALLOW_PROPOSAL",
    reasons_json: JSON.stringify([]),
    rule_ids_json: JSON.stringify(["R1", "R2", "R3"]),
    rule_details_json: JSON.stringify([
      { rule_id: "R1", passed: true, reason_code: "ok", message: "Vendor resolved", evidence: {} },
      { rule_id: "R2", passed: true, reason_code: "ok", message: "Bank matches", evidence: {} },
    ]),
    policy_version: "2.0.0",
    created_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

export function caseSummary(overrides: Partial<CaseSummary> = {}): CaseSummary {
  return {
    case: {
      id: "case_1",
      state: "UPLOADED",
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
      completed_at: null,
      error_code: null,
      error_summary: null,
      version: 1,
    },
    artifacts: [
      { id: "art_1", kind: "invoice", media_type: "application/pdf", size_bytes: 42, sha256: "ab".repeat(32) },
    ],
    facts: [
      {
        id: "fact_1",
        field: "total",
        value: "1240.00",
        taint_class: "T2",
        validation_status: "UNCONFIRMED",
        validated_by: [],
        source: { artifact_id: "art_1", artifact_kind: "invoice", page: null, region: null, timecode: null },
        producer: {
          adapter: "fixture",
          adapter_version: "1",
          model_id: null,
          prompt_version: null,
          extracted_at: null,
          request_id: null,
        },
      },
    ],
    verdict: null,
    proposal: null,
    payments: [],
    explanation: null,
    ...overrides,
  };
}

export function proposalRow(overrides: Partial<ProposalRow> = {}): ProposalRow {
  return {
    proposal_id: "prop_1",
    case_id: "case_1",
    vendor_id: "vendor_1",
    payee_display_name: "Acme Supplies",
    amount: "1240.00",
    currency: "INR",
    due_date: "2026-03-01",
    invoice_reference: "INV-1",
    verdict_id: "verdict_1",
    proposal_hash: "cd".repeat(32),
    policy_version: "2.0.0",
    expires_at: "2026-01-02T00:00:00+00:00",
    status: "PENDING",
    created_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

export function providerStatusItem(overrides: Partial<ProviderStatusItem> = {}): ProviderStatusItem {
  return {
    task: "invoice_extraction",
    provider: "meta",
    model: "muse-spark-1.3",
    availability: "ready",
    reason: "Meta Model API configured",
    ...overrides,
  };
}

export function providersResponse(overrides: Partial<ProvidersResponse> = {}): ProvidersResponse {
  return {
    providers: [
      providerStatusItem({}),
      providerStatusItem({
        task: "transcription",
        model: "muse-voice-transcribe-1.0",
        availability: "missing_credential",
        reason: "MODEL_API_KEY is not configured",
      }),
      providerStatusItem({
        task: "segmentation",
        model: "sam-3.1",
        availability: "breaker_open",
        reason: "recent repeated Meta API failures",
      }),
    ],
    ...overrides,
  };
}

export function healthResponse(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: "ok",
    version: "0.1.0",
    database: "ok",
    schema_version: 3,
    policy_version: "2.0.0",
    ...overrides,
  };
}

export function dashboardSummary() {
  return {
    cases_by_state: { UPLOADED: 2, PROPOSED: 1 },
    proposals_by_status: { PENDING: 1 },
    payments_total: 0,
    recent_cases: [
      { id: "case_1", state: "UPLOADED", created_at: "2026-01-01T00:00:00+00:00", updated_at: "2026-01-01T00:00:00+00:00" },
    ],
  };
}

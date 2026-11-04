/**
 * Backend contract types, 1:1 with the FastAPI responses (verified against
 * app/api + services; see docs/phase4/ARCHITECTURE_DISCOVERY.md).
 * The frontend never invents fields: unknown shapes stay `unknown`.
 */

export type Verdict = "ALLOW_PROPOSAL" | "ESCALATE" | "DENY";

export interface ApiErrorDetails {
  code?: string;
  message?: string;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id: string;
    details: unknown;
  };
}

/* -- auth ------------------------------------------------------------ */

export interface LoginResponse {
  session_id: string;
  csrf_token: string;
  expires_at: string | null;
}

export interface SessionInfo {
  authenticated: boolean;
  session_id: string | null;
  expires_at: string | null;
}

export interface CsrfRefreshResponse {
  csrf_token: string;
}

/* -- cases ----------------------------------------------------------- */

export interface CaseRow {
  id: string;
  state: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error_code: string | null;
  error_summary: string | null;
  version: number;
}

export interface CaseListResponse {
  cases: CaseRow[];
  limit: number;
  offset: number;
}

export interface Artifact {
  id: string;
  kind: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
}

export interface FactSource {
  artifact_id: string;
  artifact_kind: string;
  page: number | null;
  region: string | null;
  timecode: string | null;
}

export interface FactProducer {
  adapter: string;
  adapter_version: string;
  model_id: string | null;
  prompt_version: string | null;
  extracted_at: string | null;
  request_id: string | null;
}

export interface Fact {
  id: string;
  field: string;
  value: unknown;
  taint_class: string;
  validation_status: string;
  validated_by: unknown;
  source: FactSource;
  producer: FactProducer;
}

export interface LineItemValue {
  description: string;
  quantity: string;
  unit_price: string;
  catalogue_item_id: string | null;
  extracted_item_id: string | null;
}

export interface BankFactValue {
  fingerprint: string | null;
  match: boolean | null;
}

export interface VerdictRow {
  verdict_id: string;
  case_id: string;
  verdict: Verdict;
  reasons_json: string;
  rule_ids_json: string;
  rule_details_json: string;
  policy_version: string;
  created_at: string;
}

export interface RuleDetail {
  rule_id: string;
  passed: boolean;
  reason_code: string;
  message: string;
  evidence: Record<string, unknown>;
}

export interface PaymentRow {
  payment_id: string;
  proposal_id: string;
  idempotency_key: string;
  proposal_hash: string;
  case_id: string;
  amount: string;
  currency: string;
  executed_at: string;
  status: string;
}

export interface CaseSummary {
  case: CaseRow;
  artifacts: Artifact[];
  facts: Fact[];
  verdict: VerdictRow | null;
  proposal: ProposalRow | null;
  payments: PaymentRow[];
  explanation: string | null;
}

/* -- proposals / approval / payments --------------------------------- */

export interface ProposalRow {
  proposal_id: string;
  case_id: string;
  vendor_id: string;
  payee_display_name: string;
  amount: string;
  currency: string;
  due_date: string;
  invoice_reference: string;
  verdict_id: string;
  proposal_hash: string;
  policy_version: string;
  expires_at: string;
  status: string;
  created_at: string;
}

export interface ProposalListResponse {
  proposals: ProposalRow[];
  limit: number;
  offset: number;
}

export interface ChallengeResponse {
  challenge_id: string;
  proposal_hash: string;
  expires_in_minutes: number;
  proposal: ProposalRow;
}

export interface PaymentView {
  payment_id: string;
  proposal_id: string;
  case_id: string;
  amount: string;
  currency: string;
  executed_at: string;
  status: string;
  label: string;
  mock: boolean;
}

export interface CasePaymentsResponse {
  payments: PaymentView[];
}

/* -- dashboard / audit / providers / health -------------------------- */

export interface DashboardSummary {
  cases_by_state: Record<string, number>;
  proposals_by_status: Record<string, number>;
  payments_total: number;
  recent_cases: Array<{
    id: string;
    state: string;
    created_at: string;
    updated_at: string;
  }>;
}

export interface AuditEvent {
  id: number;
  ts: string;
  case_id: string | null;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  payload: unknown;
  prev_hash: string;
  event_hash: string;
}

export interface CaseAuditResponse {
  case_id: string;
  events: AuditEvent[];
}

export interface RecentAuditResponse {
  events: AuditEvent[];
  limit: number;
  offset: number;
}

export interface AuditVerifyResult {
  ok: boolean;
  events: number;
  break_at?: number | null;
  reason?: string | null;
}

/** Backend Availability values (app/providers/registry.py). Keep in sync. */
export type ProviderAvailability =
  | "ready"
  | "missing_credential"
  | "misconfigured"
  | "disabled"
  | "breaker_open"
  | "not_applicable";

/** Backend TaskKind values. Keep in sync. */
export type ProviderTask = "invoice_extraction" | "transcription" | "segmentation";

export interface ProviderStatusItem {
  task: ProviderTask;
  provider: string;
  model: string;
  availability: ProviderAvailability;
  reason: string;
}

export interface ProvidersResponse {
  providers: ProviderStatusItem[];
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  schema_version: number;
  policy_version: string;
}

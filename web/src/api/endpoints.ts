/** Typed endpoint map. Paths/methods mirror the backend routes exactly. */

import { config } from "../config";
import { apiBytes, apiFetch } from "./client";
import type {
  AuditVerifyResult,
  CaseAuditResponse,
  CaseListResponse,
  CasePaymentsResponse,
  CaseSummary,
  ChallengeResponse,
  CsrfRefreshResponse,
  DashboardSummary,
  HealthResponse,
  LoginResponse,
  PaymentView,
  ProposalListResponse,
  ProposalRow,
  ProvidersResponse,
  RecentAuditResponse,
  SessionInfo,
} from "./types";

/* auth */

export function login(pin: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    json: { pin },
    skipAuthHandler: true,
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/api/v1/auth/logout", {
    method: "POST",
    skipAuthHandler: true,
  });
}

export function fetchMe(): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/api/v1/auth/me", { skipAuthHandler: true });
}

export function refreshCsrf(): Promise<CsrfRefreshResponse> {
  return apiFetch<CsrfRefreshResponse>("/api/v1/auth/csrf-refresh", {
    method: "POST",
    skipAuthHandler: true,
  });
}

/* cases */

export function listCases(limit: number, offset: number): Promise<CaseListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<CaseListResponse>(`/api/v1/cases?${params.toString()}`);
}

export function getCase(caseId: string): Promise<CaseSummary> {
  return apiFetch<CaseSummary>(`/api/v1/cases/${encodeURIComponent(caseId)}`);
}

export function createCase(form: FormData, idempotencyKey: string): Promise<CaseSummary> {
  return apiFetch<CaseSummary>("/api/v1/cases", {
    method: "POST",
    form,
    headers: { "Idempotency-Key": idempotencyKey },
    timeoutMs: 120_000,
  });
}

export function processCase(caseId: string, signal?: AbortSignal | null): Promise<CaseSummary> {
  return apiFetch<CaseSummary>(`/api/v1/cases/${encodeURIComponent(caseId)}/process`, {
    method: "POST",
    signal,
    timeoutMs: config.processTimeoutMs,
  });
}

export function rejectCase(caseId: string): Promise<CaseSummary> {
  return apiFetch<CaseSummary>(`/api/v1/cases/${encodeURIComponent(caseId)}/reject`, {
    method: "POST",
    needsCsrf: true,
  });
}

export function editFact(caseId: string, factId: string, value: unknown): Promise<CaseSummary> {
  return apiFetch<CaseSummary>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/facts/${encodeURIComponent(factId)}/edit`,
    { method: "POST", json: { value }, needsCsrf: true, timeoutMs: config.processTimeoutMs },
  );
}

export function artifactBlob(caseId: string, artifactId: string, signal?: AbortSignal | null): Promise<Blob> {
  return apiBytes(
    `/api/v1/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(artifactId)}/content`,
    { signal },
  );
}

/* proposals / approval / payments */

export function listProposals(limit: number, offset: number): Promise<ProposalListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProposalListResponse>(`/api/v1/proposals?${params.toString()}`);
}

export function getProposal(proposalId: string): Promise<ProposalRow> {
  return apiFetch<ProposalRow>(`/api/v1/proposals/${encodeURIComponent(proposalId)}`);
}

export function issueChallenge(proposalId: string): Promise<ChallengeResponse> {
  return apiFetch<ChallengeResponse>(
    `/api/v1/proposals/${encodeURIComponent(proposalId)}/challenge`,
    { method: "POST", json: {}, needsCsrf: true },
  );
}

export function confirmProposal(proposalId: string, challengeId: string, pin: string): Promise<PaymentView> {
  return apiFetch<PaymentView>(
    `/api/v1/proposals/${encodeURIComponent(proposalId)}/confirm`,
    { method: "POST", json: { challenge_id: challengeId, pin }, needsCsrf: true },
  );
}

export function getPayment(paymentId: string): Promise<PaymentView> {
  return apiFetch<PaymentView>(`/api/v1/payments/mock/${encodeURIComponent(paymentId)}`);
}

export function listCasePayments(caseId: string): Promise<CasePaymentsResponse> {
  return apiFetch<CasePaymentsResponse>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/payments/mock`,
  );
}

/* dashboard / audit / providers / health */

export function dashboardSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/v1/dashboard/summary");
}

export function caseAudit(caseId: string): Promise<CaseAuditResponse> {
  return apiFetch<CaseAuditResponse>(`/api/v1/audit/${encodeURIComponent(caseId)}`);
}

export function recentAudit(limit: number, offset: number): Promise<RecentAuditResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<RecentAuditResponse>(`/api/v1/audit/recent?${params.toString()}`);
}

export function verifyAudit(): Promise<AuditVerifyResult> {
  return apiFetch<AuditVerifyResult>("/api/v1/audit/verify", { method: "POST" });
}

export function providerStatuses(): Promise<ProvidersResponse> {
  return apiFetch<ProvidersResponse>("/api/v1/providers");
}

export function health(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/v1/health", { skipAuthHandler: true });
}

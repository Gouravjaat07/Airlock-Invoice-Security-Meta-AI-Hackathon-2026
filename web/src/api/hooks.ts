/** Server-state hooks: one query key per resource, invalidation on mutate. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./endpoints";
import type { CaseSummary } from "./types";

export const PAGE_SIZE = 20;

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
}

export function useDashboard(enabled = true) {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboardSummary,
    retry: false,
    enabled,
  });
}

export function useCases(limit: number, offset: number) {
  return useQuery({
    queryKey: ["cases", limit, offset],
    queryFn: () => api.listCases(limit, offset),
    retry: false,
  });
}

export function useCase(caseId: string | undefined) {
  return useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.getCase(caseId ?? ""),
    retry: false,
    enabled: Boolean(caseId),
  });
}

export function useProposals(limit: number, offset: number) {
  return useQuery({
    queryKey: ["proposals", limit, offset],
    queryFn: () => api.listProposals(limit, offset),
    retry: false,
  });
}

export function useProposal(proposalId: string | undefined) {
  return useQuery({
    queryKey: ["proposal", proposalId],
    queryFn: () => api.getProposal(proposalId ?? ""),
    retry: false,
    enabled: Boolean(proposalId),
  });
}

export function useCaseAudit(caseId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["audit", caseId],
    queryFn: () => api.caseAudit(caseId ?? ""),
    retry: false,
    enabled: Boolean(caseId) && enabled,
  });
}

export function useRecentAudit(limit: number, offset: number) {
  return useQuery({
    queryKey: ["audit-recent", limit, offset],
    queryFn: () => api.recentAudit(limit, offset),
    retry: false,
  });
}

export function useProviders() {
  return useQuery({ queryKey: ["providers"], queryFn: api.providerStatuses, retry: false });
}

/** Refresh every case-derived view after a case mutation. */
export function useInvalidateCase() {
  const client = useQueryClient();
  return (caseId: string) => {
    void client.invalidateQueries({ queryKey: ["case", caseId] });
    void client.invalidateQueries({ queryKey: ["cases"] });
    void client.invalidateQueries({ queryKey: ["dashboard"] });
    void client.invalidateQueries({ queryKey: ["audit", caseId] });
    void client.invalidateQueries({ queryKey: ["proposals"] });
    void client.invalidateQueries({ queryKey: ["audit-recent"] });
  };
}

export function useRejectCase(caseId: string) {
  const invalidate = useInvalidateCase();
  return useMutation<CaseSummary, unknown, void>({
    mutationFn: () => api.rejectCase(caseId),
    onSuccess: () => invalidate(caseId),
  });
}

export function useEditFact(caseId: string) {
  const invalidate = useInvalidateCase();
  return useMutation<CaseSummary, unknown, { factId: string; value: unknown }>({
    mutationFn: ({ factId, value }) => api.editFact(caseId, factId, value),
    onSuccess: () => invalidate(caseId),
  });
}

export function useChallenge(proposalId: string) {
  return useMutation({
    mutationFn: () => api.issueChallenge(proposalId),
  });
}

export function useConfirm(proposalId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ challengeId, pin }: { challengeId: string; pin: string }) =>
      api.confirmProposal(proposalId, challengeId, pin),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["proposal", proposalId] });
      void client.invalidateQueries({ queryKey: ["proposals"] });
      void client.invalidateQueries({ queryKey: ["cases"] });
      void client.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useVerifyAudit() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.verifyAudit,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["audit-recent"] });
    },
  });
}

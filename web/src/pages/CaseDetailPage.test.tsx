import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { caseSummary, verdictRow } from "../test/fixtures";
import { envelope, jsonResponse, renderAppAt, stubFetch } from "../test/helpers";
import type { CaseSummary } from "../api/types";

const ME = { authenticated: true, session_id: "sess_1", expires_at: null };

function denySummary(): CaseSummary {
  return caseSummary({
    case: { ...caseSummary().case, state: "NEEDS_REVIEW" },
    verdict: verdictRow({
      verdict: "DENY",
      rule_details_json: JSON.stringify([
        { rule_id: "R1", passed: true, reason_code: "ok", message: "Vendor resolved", evidence: {} },
        { rule_id: "R2", passed: false, reason_code: "mismatch", message: "Bank mismatch", evidence: {} },
      ]),
    }),
    explanation: "Verdict: DENY.",
  });
}

function stubCaseWorld(summary: CaseSummary, onProcess?: () => void) {
  stubFetch((url, _init) => {
    void _init;
    if (url.endsWith("/api/v1/auth/me")) return jsonResponse(ME);
    if (url.endsWith("/api/v1/dashboard/summary")) {
      return jsonResponse({ cases_by_state: {}, proposals_by_status: {}, payments_total: 0, recent_cases: [] });
    }
    if (url.match(/\/api\/v1\/cases\/[^/]+\/process$/)) {
      onProcess?.();
      return jsonResponse(summary);
    }
    if (url.match(/\/api\/v1\/cases\/[^/]+\/artifacts\/[^/]+\/content$/)) {
      return new Response("PDF-BYTES", { status: 200 });
    }
    if (url.endsWith("/api/v1/audit/case_1")) {
      return jsonResponse({ case_id: "case_1", events: [] });
    }
    if (url.endsWith("/api/v1/cases/case_1")) return jsonResponse(summary);
    return jsonResponse(envelope("E_INTERNAL", `unexpected ${url}`), 500);
  });
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});

describe("CaseDetailPage", () => {
  it("renders facts and the DENY policy breakdown", async () => {
    stubCaseWorld(denySummary());
    const user = userEvent.setup();
    renderAppAt(App, "/cases/case_1");
    expect(await screen.findByText("1240.00")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Policy" }));
    expect(await screen.findByText("Deny")).toBeInTheDocument();
    expect(screen.getByText(/Bank mismatch/)).toBeInTheDocument();
    expect(screen.getByText("Verdict: DENY.")).toBeInTheDocument();
  });

  it("processes an UPLOADED case and refreshes", async () => {
    let processed = 0;
    stubCaseWorld(caseSummary(), () => {
      processed += 1;
    });
    const user = userEvent.setup();
    renderAppAt(App, "/cases/case_1");
    await user.click(await screen.findByRole("button", { name: "Process case" }));
    await waitFor(() => expect(processed).toBe(1));
    expect(await screen.findByText(/Processing finished/)).toBeInTheDocument();
  });

  it("hides the process action once executed", async () => {
    stubCaseWorld(caseSummary({ case: { ...caseSummary().case, state: "EXECUTED" } }));
    renderAppAt(App, "/cases/case_1");
    expect(await screen.findByText("Executed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /process case|retry processing/i })).toBeNull();
  });

  it("previews the invoice artifact on the evidence tab", async () => {
    stubCaseWorld(caseSummary());
    const user = userEvent.setup();
    renderAppAt(App, "/cases/case_1");
    await user.click(await screen.findByRole("tab", { name: /Evidence/ }));
    expect(await screen.findByTitle("Artifact art_1")).toBeInTheDocument();
  });
});

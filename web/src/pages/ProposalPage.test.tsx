import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../App";
import { caseSummary, proposalRow, verdictRow } from "../test/fixtures";
import { envelope, jsonResponse, renderAppAt, stubFetch } from "../test/helpers";

const ME = { authenticated: true, session_id: "sess_1", expires_at: null };

const PAYMENT = {
  payment_id: "pay_1",
  proposal_id: "prop_1",
  case_id: "case_1",
  amount: "1240.00",
  currency: "INR",
  executed_at: "2026-01-01T01:00:00+00:00",
  status: "MOCK_COMPLETED",
  label: "MOCK PAYMENT — NO MONEY TRANSFERRED",
  mock: true,
};

function stubApprovalWorld(options: { verdictId?: string; verdict?: "ALLOW_PROPOSAL" | "DENY"; status?: string }) {
  const { verdictId = "verdict_1", verdict = "ALLOW_PROPOSAL", status = "PENDING" } = options;
  stubFetch((url, init) => {
    if (url.endsWith("/api/v1/auth/me")) return jsonResponse(ME);
    if (url.endsWith("/api/v1/dashboard/summary")) {
      return jsonResponse({ cases_by_state: {}, proposals_by_status: {}, payments_total: 0, recent_cases: [] });
    }
    if (url.endsWith("/api/v1/proposals/prop_1")) return jsonResponse(proposalRow({ status }));
    if (url.endsWith("/api/v1/cases/case_1")) {
      return jsonResponse(caseSummary({ verdict: verdictRow({ verdict, verdict_id: verdictId }) }));
    }
    if (url.endsWith("/api/v1/proposals/prop_1/challenge")) {
      expect(init?.method).toBe("POST");
      return jsonResponse({
        challenge_id: "ch_SECRET_X",
        proposal_hash: "cd".repeat(32),
        expires_in_minutes: 5,
        proposal: proposalRow({ status }),
      });
    }
    if (url.endsWith("/api/v1/proposals/prop_1/confirm")) {
      const body = JSON.parse(String(init?.body)) as { challenge_id: string; pin: string };
      expect(body.challenge_id).toBe("ch_SECRET_X");
      expect(body.pin).toBe("1234");
      return jsonResponse(PAYMENT);
    }
    return jsonResponse(envelope("E_INTERNAL", `unexpected ${url}`), 500);
  });
}

describe("ProposalPage approval flow", () => {
  it("reviews, challenges, and confirms without ever rendering the bearer", async () => {
    stubApprovalWorld({});
    const user = userEvent.setup();
    renderAppAt(App, "/proposals/prop_1");
    expect(await screen.findByText("Acme Supplies")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Start approval" }));
    expect(await screen.findByRole("button", { name: "Authorize mock payment" })).toBeInTheDocument();
    expect(screen.queryByText(/ch_SECRET_X/)).toBeNull();
    await user.click(screen.getByRole("checkbox"));
    await user.type(screen.getByLabelText("Owner PIN"), "1234");
    await user.click(screen.getByRole("button", { name: "Authorize mock payment" }));
    expect(await screen.findByText("Mock execution confirmed")).toBeInTheDocument();
    expect(screen.getByText("MOCK PAYMENT — NO MONEY TRANSFERRED")).toBeInTheDocument();
    expect(screen.queryByText(/ch_SECRET_X/)).toBeNull();
    // The confirm form (and its PIN state) is gone after success.
    expect(screen.queryByLabelText("Owner PIN")).toBeNull();
  });

  it("withholds approval when the verdict is not an ALLOW match", async () => {
    stubApprovalWorld({ verdict: "DENY" });
    renderAppAt(App, "/proposals/prop_1");
    expect(await screen.findByText(/not currently eligible/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start approval" })).toBeNull();
  });

  it("withholds approval for non-pending proposals", async () => {
    stubApprovalWorld({ status: "CONFIRMED" });
    renderAppAt(App, "/proposals/prop_1");
    expect(await screen.findByText(/Proposal is confirmed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start approval" })).toBeNull();
  });
});

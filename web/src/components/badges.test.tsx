import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AvailabilityBadge,
  CaseStateBadge,
  FieldStatusBadge,
  PaymentBadge,
  ProposalBadge,
  TaintBadge,
  VerdictBadge,
} from "./badges";

describe("status badges", () => {
  it("labels known states with icon and text", () => {
    render(<CaseStateBadge state="NEEDS_REVIEW" />);
    expect(screen.getByText("Needs Review")).toBeInTheDocument();
    render(<VerdictBadge verdict="ALLOW_PROPOSAL" />);
    expect(screen.getByText("Allow proposal")).toBeInTheDocument();
    render(<ProposalBadge status="PENDING" />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
    render(<PaymentBadge status="MOCK_COMPLETED" mock />);
    expect(screen.getByText("Mock completed")).toBeInTheDocument();
    render(<TaintBadge taint="T2" />);
    expect(screen.getByText("T2 · Model")).toBeInTheDocument();
    render(<FieldStatusBadge status="CONFLICT" />);
    expect(screen.getByText("Conflict")).toBeInTheDocument();
    render(<AvailabilityBadge availability="breaker_open" />);
    expect(screen.getByText("Breaker Open")).toBeInTheDocument();
  });

  it("falls back to the raw value for unknown states", () => {
    render(<CaseStateBadge state="SOMETHING_NEW" />);
    expect(screen.getByText("SOMETHING_NEW")).toBeInTheDocument();
    render(<VerdictBadge verdict="MAYBE" />);
    expect(screen.getByText("MAYBE")).toBeInTheDocument();
  });

  it("covers every backend provider availability value", () => {
    const cases: Array<[string, string]> = [
      ["ready", "Ready"],
      ["missing_credential", "Missing Credential"],
      ["misconfigured", "Misconfigured"],
      ["disabled", "Disabled"],
      ["breaker_open", "Breaker Open"],
      ["not_applicable", "Not Applicable"],
    ];
    for (const [value, label] of cases) {
      const { unmount } = render(<AvailabilityBadge availability={value} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
    render(<AvailabilityBadge availability="something_new" />);
    expect(screen.getByText("something_new")).toBeInTheDocument();
  });
});

/**
 * Proposal review + owner approval. The challenge bearer lives in component
 * state only: never rendered, never stored, cleared on completion/unmount.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useCase, useChallenge, useConfirm, useProposal } from "../api/hooks";
import type { PaymentView } from "../api/types";
import { PaymentBadge, ProposalBadge, VerdictBadge } from "../components/badges";
import { Button, Field, PinInput } from "../components/controls";
import {
  Alert,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
} from "../components/feedback";
import { Card, CopyRef } from "../components/misc";
import { useToast } from "../components/overlays";
import { formatDate, formatDateTime, formatMoney } from "../utils/format";
import { safeMessage } from "../utils/errors";

interface ActiveChallenge {
  challengeId: string;
  expiresAt: Date;
}

export function ProposalPage(): React.JSX.Element {
  const { proposalId } = useParams<{ proposalId: string }>();
  const { notify } = useToast();
  const proposal = useProposal(proposalId);
  const linkedCase = useCase(proposal.data?.case_id);
  const challenge = useChallenge(proposalId ?? "");
  const confirm = useConfirm(proposalId ?? "");

  const [active, setActive] = useState<ActiveChallenge | null>(null);
  const [pin, setPin] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [done, setDone] = useState<PaymentView | null>(null);

  if (proposal.isPending) {
    return (
      <div>
        <PageHeader title="Proposal" crumb={{ label: "Proposals", to: "/proposals" }} />
        <SkeletonRows rows={8} />
      </div>
    );
  }
  if (proposal.isError) {
    const missing = proposal.error instanceof ApiError && proposal.error.status === 404;
    return (
      <div>
        <PageHeader title="Proposal" crumb={{ label: "Proposals", to: "/proposals" }} />
        <ErrorState
          title={missing ? "Proposal not found" : "Proposal unavailable"}
          message={safeMessage(proposal.error)}
          requestId={proposal.error instanceof ApiError ? proposal.error.requestId : null}
          onRetry={() => void proposal.refetch()}
        />
      </div>
    );
  }

  const row = proposal.data;
  const verdictRow = linkedCase.data?.verdict ?? null;
  const verdictCurrent =
    verdictRow !== null &&
    verdictRow.verdict === "ALLOW_PROPOSAL" &&
    verdictRow.verdict_id === row.verdict_id;
  const startChallenge = (): void => {
    setConfirmError(null);
    setDone(null);
    challenge.mutate(undefined, {
      onSuccess: (created) => {
        setActive({
          challengeId: created.challenge_id,
          expiresAt: new Date(Date.now() + created.expires_in_minutes * 60_000),
        });
        notify("Approval challenge issued. Confirm below before it expires.", "info");
      },
      onError: (error) => {
        setConfirmError(safeMessage(error));
        void proposal.refetch();
      },
    });
  };

  const submitConfirm = async (): Promise<void> => {
    if (!active || !acknowledged || !pin.trim()) return;
    setConfirmError(null);
    confirm.mutate(
      { challengeId: active.challengeId, pin },
      {
        onSuccess: (payment) => {
          setDone(payment);
          setActive(null);
          setAcknowledged(false);
          notify("Mock payment executed.", "success");
          void proposal.refetch();
        },
        onError: (error) => {
          if (error instanceof ApiError && /challenge/i.test(error.message)) {
            setActive(null);
            setConfirmError(
              "The challenge is invalid or expired. Start a new approval challenge to continue.",
            );
          } else {
            setConfirmError(safeMessage(error));
          }
          void proposal.refetch();
        },
        onSettled: () => setPin(""),
      },
    );
  };

  return (
    <div>
      <PageHeader
        title={`Proposal ${row.proposal_id.slice(0, 8)}…`}
        crumb={{ label: "Proposals", to: "/proposals" }}
        description="Review the exact backend values, then approve explicitly. Nothing here authorizes itself."
        actions={<CopyRef value={row.proposal_id} label="Copy proposal id" />}
      />

      <div className="ak-stack">
        <Card title="Review">
          <dl className="ak-dl">
            <dt>Status</dt>
            <dd>
              <ProposalBadge status={row.status} />
            </dd>
            <dt>Payee</dt>
            <dd>{row.payee_display_name}</dd>
            <dt>Amount</dt>
            <dd className="ak-num">{formatMoney(row.amount, row.currency)}</dd>
            <dt>Invoice</dt>
            <dd>{row.invoice_reference}</dd>
            <dt>Due</dt>
            <dd>{formatDate(row.due_date)}</dd>
            <dt>Case</dt>
            <dd>
              <Link to={`/cases/${encodeURIComponent(row.case_id)}`} className="ak-mono">
                {row.case_id}
              </Link>
            </dd>
            <dt>Policy</dt>
            <dd>
              {verdictRow ? <VerdictBadge verdict={verdictRow.verdict} /> : "—"}{" "}
              <span className="ak-caption">policy {row.policy_version}</span>
            </dd>
            <dt>Expires</dt>
            <dd>{formatDateTime(row.expires_at)}</dd>
            <dt>Proposal hash</dt>
            <dd>
              <CopyRef value={row.proposal_hash} label="Copy proposal hash" />
            </dd>
          </dl>
        </Card>

        {done ? (
          <Card title="Mock execution confirmed">
            <Alert tone="success">
              <strong>{done.label}</strong>
            </Alert>
            <dl className="ak-dl">
              <dt>Payment</dt>
              <dd>
                <CopyRef value={done.payment_id} />
              </dd>
              <dt>Amount</dt>
              <dd className="ak-num">{formatMoney(done.amount, done.currency)}</dd>
              <dt>Executed</dt>
              <dd>{formatDateTime(done.executed_at)}</dd>
              <dt>Status</dt>
              <dd>
                <PaymentBadge status={done.status} mock={done.mock} />
              </dd>
            </dl>
            <p style={{ marginTop: 12 }}>
              <Link className="ak-btn ak-btn--secondary ak-btn--sm" to={`/cases/${encodeURIComponent(done.case_id)}`}>
                Open the case
              </Link>
            </p>
          </Card>
        ) : row.status !== "PENDING" ? (
          <EmptyState
            title={`Proposal is ${row.status.toLowerCase()}`}
            body="Only pending proposals can enter approval. The server enforces this regardless of what the UI shows."
          />
        ) : linkedCase.isPending ? (
          <SkeletonRows rows={3} />
        ) : !verdictCurrent ? (
          <Alert tone="warning">
            This proposal is not currently eligible: the linked case has{" "}
            {verdictRow ? (
              <>
                verdict <strong>{verdictRow.verdict}</strong>
                {verdictRow.verdict_id !== row.verdict_id ? " (a newer verdict superseded it)" : ""}
              </>
            ) : (
              "no verdict"
            )}
            . Approval unlocks only for a pending proposal bound to the current ALLOW_PROPOSAL
            verdict.
          </Alert>
        ) : active === null ? (
          <Card title="Approval">
            <p style={{ marginBottom: 14 }}>
              Approval issues a single-use challenge bound to this exact proposal, your session,
              and a short expiry. You will confirm with the owner PIN on the next step.
            </p>
            <Button variant="primary" loading={challenge.isPending} onClick={startChallenge}>
              Start approval
            </Button>
          </Card>
        ) : (
          <Card title="Confirm approval">
            <Alert tone="warning">
              You are authorizing a <strong>MOCK payment of {formatMoney(row.amount, row.currency)} to{" "}
              {row.payee_display_name}</strong>. No real funds move. The challenge expires{" "}
              {formatDateTime(active.expiresAt.toISOString())} and is single-use.
            </Alert>
            {confirmError ? <Alert tone="danger">{confirmError}</Alert> : null}
            <label
              style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 16 }}
            >
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
                style={{ marginTop: 4 }}
              />
              <span>
                I have reviewed the payee, amount, and policy result above and I authorize this
                mock execution.
              </span>
            </label>
            <Field label="Owner PIN" htmlFor="confirm-pin">
              <PinInput
                id="confirm-pin"
                value={pin}
                minLength={4}
                maxLength={64}
                required
                disabled={confirm.isPending}
                onChange={(event) => setPin(event.target.value)}
              />
            </Field>
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
              <Button
                variant="primary"
                loading={confirm.isPending}
                disabled={!acknowledged || !pin.trim()}
                onClick={() => void submitConfirm()}
              >
                Authorize mock payment
              </Button>
              <Button variant="ghost" disabled={confirm.isPending} onClick={() => setActive(null)}>
                Discard challenge
              </Button>
            </div>
          </Card>
        )}
        {confirmError && active === null && !done ? <Alert tone="danger">{confirmError}</Alert> : null}
      </div>
    </div>
  );
}

/** Case workspace: extraction review, policy, evidence, payments, audit. */

import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { processCase } from "../api/endpoints";
import { useCase, useCaseAudit, useEditFact, useInvalidateCase, useRejectCase } from "../api/hooks";
import { parseVerdict } from "../api/parse";
import type { AuditEvent, CaseSummary, Fact } from "../api/types";
import {
  CaseStateBadge,
  EvidenceStatusBadge,
  FieldStatusBadge,
  PaymentBadge,
  ProposalBadge,
  TaintBadge,
  VerdictBadge,
} from "../components/badges";
import { Button, Field, Select, TextArea, TextInput } from "../components/controls";
import { EvidencePreview } from "../components/EvidencePreview";
import {
  Alert,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  Spinner,
} from "../components/feedback";
import { AuditTimeline, Card, CopyRef, Tabs } from "../components/misc";
import { Dialog, useToast } from "../components/overlays";
import { formatDate, formatDateTime, formatMoney, humanizeState, shortRef } from "../utils/format";
import { evidenceInfoFor } from "../utils/evidence";
import { isSessionError, safeMessage } from "../utils/errors";

const PROCESSABLE = ["UPLOADED", "ERROR", "EXPIRED"];
const REJECTABLE = ["NEEDS_REVIEW", "PROPOSED"];
const EDITABLE = ["UPLOADED", "ERROR", "EXPIRED", "REJECTED", "NEEDS_REVIEW", "PROPOSED"];
const JSON_FACTS = ["line_items", "bank"];

function FactValueCell({ fact }: { fact: Fact }): React.JSX.Element {
  const { value } = fact;
  if (value === null || value === undefined || value === "") return <span>—</span>;
  if (fact.field === "line_items" && Array.isArray(value)) {
    const items = value as Array<Record<string, unknown>>;
    return (
      <table className="ak-table" style={{ marginTop: 4 }}>
        <thead>
          <tr>
            <th scope="col">Description</th>
            <th scope="col">Qty</th>
            <th scope="col">Unit price</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i}>
              <td>{String(item.description ?? "—")}</td>
              <td className="ak-num">{String(item.quantity ?? "—")}</td>
              <td className="ak-num">{String(item.unit_price ?? "—")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (typeof value === "object") {
    return (
      <details>
        <summary className="ak-caption" style={{ cursor: "pointer" }}>
          Structured value
        </summary>
        <pre className="ak-mono" style={{ whiteSpace: "pre-wrap", fontSize: 12.5 }}>
          {JSON.stringify(value, null, 2)}
        </pre>
      </details>
    );
  }
  return <span>{String(value)}</span>;
}

function OverviewTab({ summary }: { summary: CaseSummary }): React.JSX.Element {
  const { case: row, facts, proposal } = summary;
  return (
    <div className="ak-stack">
      {row.state === "ERROR" ? (
        <Alert tone="danger">
          Processing failed{row.error_code ? ` (${row.error_code})` : ""}:{" "}
          {row.error_summary ?? "see the audit trail for details."}
        </Alert>
      ) : null}
      <Card title="Case">
        <dl className="ak-dl">
          <dt>Case ID</dt>
          <dd>
            <CopyRef value={row.id} />
          </dd>
          <dt>State</dt>
          <dd>
            <CaseStateBadge state={row.state} />
          </dd>
          <dt>Created</dt>
          <dd>{formatDateTime(row.created_at)}</dd>
          <dt>Updated</dt>
          <dd>{formatDateTime(row.updated_at)}</dd>
          {row.completed_at ? (
            <>
              <dt>Completed</dt>
              <dd>{formatDateTime(row.completed_at)}</dd>
            </>
          ) : null}
        </dl>
      </Card>
      <Card title={`Extracted fields (${facts.length})`}>
        {facts.length === 0 ? (
          <p className="ak-caption">
            No extracted fields yet. Process the case to run extraction and policy evaluation.
          </p>
        ) : (
          <div className="ak-table-wrap">
            <table className="ak-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Candidate value</th>
                  <th scope="col">Provenance</th>
                  <th scope="col">Validation</th>
                </tr>
              </thead>
              <tbody>
                {facts.map((fact) => (
                  <tr key={fact.id}>
                    <td>
                      <strong>{fact.field}</strong>
                      <div className="ak-caption">
                        {fact.producer.adapter}
                        {fact.producer.model_id ? ` · ${fact.producer.model_id}` : ""}
                      </div>
                    </td>
                    <td>
                      <FactValueCell fact={fact} />
                    </td>
                    <td>
                      <TaintBadge taint={fact.taint_class} />
                      <div className="ak-caption" style={{ marginTop: 4 }}>
                        via {shortRef(fact.source.artifact_id)}
                        {fact.source.page == null ? " · page n/a" : ` · p.${fact.source.page}`}
                      </div>
                    </td>
                    <td>
                      <FieldStatusBadge status={fact.validation_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ak-caption" style={{ marginTop: 10 }}>
          Candidates are untrusted model output until corroborated. Precise source regions are
          unavailable when the backend reports no page geometry.
        </p>
      </Card>
      {proposal ? (
        <Card title="Proposal">
          <dl className="ak-dl">
            <dt>Proposal</dt>
            <dd>
              <Link to={`/proposals/${encodeURIComponent(proposal.proposal_id)}`} className="ak-mono">
                {proposal.proposal_id}
              </Link>{" "}
              <ProposalBadge status={proposal.status} />
            </dd>
            <dt>Payee</dt>
            <dd>{proposal.payee_display_name}</dd>
            <dt>Amount</dt>
            <dd className="ak-num">{formatMoney(proposal.amount, proposal.currency)}</dd>
            <dt>Due</dt>
            <dd>{formatDate(proposal.due_date)}</dd>
          </dl>
        </Card>
      ) : null}
    </div>
  );
}

function PolicyTab({ summary }: { summary: CaseSummary }): React.JSX.Element {
  const verdict = summary.verdict;
  if (!verdict) {
    return (
      <EmptyState
        title="Not evaluated yet"
        body="No policy verdict exists for this case. Process the case to run the deterministic R1–R10 evaluation."
      />
    );
  }
  const parsed = parseVerdict(verdict);
  return (
    <div className="ak-stack">
      <Card title="Verdict">
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <VerdictBadge verdict={verdict.verdict} />
          <span className="ak-caption">
            policy {verdict.policy_version} · {formatDateTime(verdict.created_at)} ·{" "}
            <span className="ak-mono">{shortRef(verdict.verdict_id)}</span>
          </span>
        </div>
        {summary.explanation ? <p style={{ marginTop: 12 }}>{summary.explanation}</p> : null}
        {parsed.degraded ? (
          <div style={{ marginTop: 12 }}>
            <Alert tone="warning">
              Part of the stored rule detail could not be parsed; the verdict above is still the
              authoritative backend value.
            </Alert>
          </div>
        ) : null}
      </Card>
      <Card title={`Rules (${parsed.rules.length})`}>
        <div className="ak-table-wrap">
          <table className="ak-table">
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">Outcome</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {parsed.rules.map((rule) => (
                <tr key={rule.rule_id}>
                  <td className="ak-mono">
                    <strong>{rule.rule_id}</strong>
                  </td>
                  <td>
                    {rule.passed ? (
                      <span className="ak-badge ak-badge--success">Pass</span>
                    ) : (
                      <span className="ak-badge ak-badge--danger">Fail</span>
                    )}
                  </td>
                  <td>
                    <div>
                      <span className="ak-mono ak-caption">{rule.reason_code}</span> — {rule.message}
                    </div>
                    {Object.keys(rule.evidence).length > 0 ? (
                      <details>
                        <summary className="ak-caption" style={{ cursor: "pointer" }}>
                          Evidence
                        </summary>
                        <pre className="ak-mono" style={{ whiteSpace: "pre-wrap", fontSize: 12.5 }}>
                          {JSON.stringify(rule.evidence, null, 2)}
                        </pre>
                      </details>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function EvidenceMeta({ events, type }: { events: AuditEvent[]; type: string }): React.JSX.Element | null {
  const items = events.filter((e) => e.event_type === type);
  if (items.length === 0) return null;
  return (
    <div className="ak-stack">
      {items.map((event) => (
        <Card key={event.id} title={`${type} · ${formatDateTime(event.ts)}`}>
          <pre className="ak-mono" style={{ whiteSpace: "pre-wrap", fontSize: 12.5, margin: 0 }}>
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </Card>
      ))}
    </div>
  );
}

function EvidenceTab({ summary, events }: { summary: CaseSummary; events: AuditEvent[] }): React.JSX.Element {
  const kinds = ["invoice", "delivery", "voice"] as const;
  return (
    <div className="ak-stack">
      {kinds.map((kind) => {
        const items = summary.artifacts.filter((a) => a.kind === kind);
        if (items.length === 0) return null;
        return (
          <div key={kind}>
            <h2 style={{ marginBottom: 10 }}>{humanizeState(kind)} evidence</h2>
            <div className="ak-stack">
              {items.map((artifact) => {
                const info = evidenceInfoFor(artifact, events);
                return (
                  <Card
                    key={artifact.id}
                    title={`${artifact.kind} · ${shortRef(artifact.id)}`}
                    action={<CopyRef value={artifact.sha256} label="Copy sha256" />}
                  >
                    <div style={{ marginBottom: 10 }}>
                      <EvidenceStatusBadge status={info.status} label={info.label} />
                    </div>
                    {info.detail ? (
                      <p className="ak-caption" style={{ marginTop: 0 }}>
                        {info.detail}
                      </p>
                    ) : null}
                    {info.adapter || info.model || info.requestId || info.errorCode ? (
                      <dl className="ak-dl" style={{ gridTemplateColumns: "88px 1fr", marginBottom: 10 }}>
                        {info.adapter ? (
                          <>
                            <dt>Provider</dt>
                            <dd>{info.adapter}</dd>
                          </>
                        ) : null}
                        {info.model ? (
                          <>
                            <dt>Model</dt>
                            <dd className="ak-mono">{info.model}</dd>
                          </>
                        ) : null}
                        {info.requestId ? (
                          <>
                            <dt>Request</dt>
                            <dd className="ak-mono">{shortRef(info.requestId)}</dd>
                          </>
                        ) : null}
                        {info.errorCode ? (
                          <>
                            <dt>Error</dt>
                            <dd className="ak-mono">{info.errorCode}</dd>
                          </>
                        ) : null}
                      </dl>
                    ) : null}
                    <EvidencePreview caseId={summary.case.id} artifact={artifact} />
                  </Card>
                );
              })}
            </div>
          </div>
        );
      })}
      <h2>Verification records</h2>
      <EvidenceMeta events={events} type="voice.transcript" />
      <EvidenceMeta events={events} type="sam.evidence" />
      {events.some((e) => e.event_type === "voice.transcript" || e.event_type === "sam.evidence") ? null : (
        <p className="ak-caption">
          No voice or visual verification records. Transcript text and segmentation masks are not
          stored retrievably; only the summarized verification metadata above is available.
        </p>
      )}
    </div>
  );
}

function PaymentsTab({ summary }: { summary: CaseSummary }): React.JSX.Element {
  if (summary.payments.length === 0) {
    return (
      <EmptyState
        title="No mock executions"
        body="Nothing has been executed for this case. Execution happens only through an approved proposal challenge."
      />
    );
  }
  return (
    <div className="ak-stack">
      <Alert tone="info">
        Simulated executions only — <strong>MOCK PAYMENT — no money is transferred.</strong>
      </Alert>
      <div className="ak-table-wrap">
        <table className="ak-table">
          <thead>
            <tr>
              <th scope="col">Payment</th>
              <th scope="col">Amount</th>
              <th scope="col">Executed</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {summary.payments.map((payment) => (
              <tr key={payment.payment_id}>
                <td>
                  <CopyRef value={payment.payment_id} />
                </td>
                <td className="ak-num">{formatMoney(payment.amount, payment.currency)}</td>
                <td className="ak-num">{formatDateTime(payment.executed_at)}</td>
                <td>
                  <PaymentBadge status={payment.status} mock />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function CaseDetailPage(): React.JSX.Element {
  const { caseId } = useParams<{ caseId: string }>();
  const { notify } = useToast();
  const invalidate = useInvalidateCase();
  const [tab, setTab] = useState("overview");
  const [processing, setProcessing] = useState(false);
  const [processError, setProcessError] = useState<{ message: string; requestId: string | null } | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const detail = useCase(caseId);
  const audit = useCaseAudit(caseId);
  const reject = useRejectCase(caseId ?? "");
  const edit = useEditFact(caseId ?? "");
  const [editField, setEditField] = useState("");
  const [editText, setEditText] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const startProcess = async (): Promise<void> => {
    if (!caseId || processing) return;
    setProcessing(true);
    setProcessError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await processCase(caseId, controller.signal);
      invalidate(caseId);
      notify("Processing finished. The verdict below is the backend result.", "success");
    } catch (error) {
      if (error instanceof ApiError && error.aborted) {
        notify("Stopped waiting. The server job may still finish — refresh to check.", "info");
        invalidate(caseId);
      } else if (!isSessionError(error)) {
        setProcessError({
          message: safeMessage(error),
          requestId: error instanceof ApiError ? error.requestId : null,
        });
      }
    } finally {
      abortRef.current = null;
      setProcessing(false);
    }
  };

  if (detail.isPending) {
    return (
      <div>
        <PageHeader title="Case" crumb={{ label: "Cases", to: "/cases" }} />
        <SkeletonRows rows={8} />
      </div>
    );
  }
  if (detail.isError) {
    return (
      <div>
        <PageHeader title="Case" crumb={{ label: "Cases", to: "/cases" }} />
        <ErrorState
          title={detail.error instanceof ApiError && detail.error.status === 404 ? "Case not found" : "Case unavailable"}
          message={safeMessage(detail.error)}
          requestId={detail.error instanceof ApiError ? detail.error.requestId : null}
          onRetry={() => void detail.refetch()}
        />
      </div>
    );
  }

  const summary = detail.data;
  const state = summary.case.state;
  const editableFacts = summary.facts;
  const selectedFact = editableFacts.find((f) => f.id === editField) ?? null;

  const submitEdit = (): void => {
    if (!selectedFact) {
      setEditError("Choose a field to correct.");
      return;
    }
    let value: unknown = editText;
    if (JSON_FACTS.includes(selectedFact.field)) {
      try {
        value = JSON.parse(editText) as unknown;
      } catch {
        setEditError("This field needs valid JSON (the server validates it strictly).");
        return;
      }
    }
    if (!JSON_FACTS.includes(selectedFact.field) && editText.trim() === "") {
      setEditError("Enter a replacement value.");
      return;
    }
    setEditError(null);
    edit.mutate(
      { factId: selectedFact.id, value },
      {
        onSuccess: () => {
          notify("Correction recorded. Policy was re-run by the server.", "success");
          setEditOpen(false);
          setEditText("");
        },
        onError: (error) => setEditError(safeMessage(error)),
      },
    );
  };

  return (
    <div>
      <PageHeader
        title={`Case ${shortRef(summary.case.id)}`}
        crumb={{ label: "Cases", to: "/cases" }}
        description={`State: ${humanizeState(state)} · version ${summary.case.version}`}
        actions={
          <>
            {summary.proposal ? (
              <Link
                className="ak-btn ak-btn--secondary ak-btn--sm"
                to={`/proposals/${encodeURIComponent(summary.proposal.proposal_id)}`}
              >
                View proposal
              </Link>
            ) : null}
            {PROCESSABLE.includes(state) && !processing ? (
              <Button variant="primary" size="sm" onClick={() => void startProcess()}>
                {state === "UPLOADED" ? "Process case" : "Retry processing"}
              </Button>
            ) : null}
            {processing ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => abortRef.current?.abort()}
              >
                Stop waiting
              </Button>
            ) : null}
            {REJECTABLE.includes(state) ? (
              <Button variant="danger" size="sm" onClick={() => setRejectOpen(true)}>
                Reject
              </Button>
            ) : null}
            {EDITABLE.includes(state) && summary.facts.length > 0 ? (
              <Button variant="secondary" size="sm" onClick={() => setEditOpen(true)}>
                Correct a field
              </Button>
            ) : null}
          </>
        }
      />

      {processing ? (
        <Alert tone="info">
          <Spinner label="Processing — extraction and policy checks are running on the server. This can take minutes with live models." />
        </Alert>
      ) : null}
      {processError ? (
        <Alert tone="danger">
          {processError.message}{" "}
          {processError.requestId ? <code>ref {processError.requestId}</code> : null}
        </Alert>
      ) : null}

      <Tabs
        label="Case sections"
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "policy", label: "Policy" },
          { id: "evidence", label: `Evidence (${summary.artifacts.length})` },
          { id: "payments", label: `Payments (${summary.payments.length})` },
          { id: "audit", label: "Audit" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "overview" ? <OverviewTab summary={summary} /> : null}
      {tab === "policy" ? <PolicyTab summary={summary} /> : null}
      {tab === "evidence" ? (
        audit.isPending ? (
          <SkeletonRows rows={4} />
        ) : audit.isError ? (
          <ErrorState
            title="Evidence metadata unavailable"
            message={safeMessage(audit.error)}
            onRetry={() => void audit.refetch()}
          />
        ) : (
          <EvidenceTab summary={summary} events={audit.data.events} />
        )
      ) : null}
      {tab === "payments" ? <PaymentsTab summary={summary} /> : null}
      {tab === "audit" ? (
        audit.isPending ? (
          <SkeletonRows rows={4} />
        ) : audit.isError ? (
          <ErrorState
            title="Audit unavailable"
            message={safeMessage(audit.error)}
            onRetry={() => void audit.refetch()}
          />
        ) : (
          <AuditTimeline events={audit.data.events} />
        )
      ) : null}

      {rejectOpen ? (
        <Dialog
          title="Reject this case?"
          description="The case moves to REJECTED and can no longer produce a proposal unless an owner correction re-runs it. This is recorded in the audit trail."
          onClose={() => setRejectOpen(false)}
          actions={
            <>
              <Button variant="secondary" onClick={() => setRejectOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={reject.isPending}
                onClick={() =>
                  reject.mutate(undefined, {
                    onSuccess: () => {
                      notify("Case rejected.", "success");
                      setRejectOpen(false);
                    },
                    onError: (error) => notify(safeMessage(error), "danger"),
                  })
                }
              >
                Reject case
              </Button>
            </>
          }
        >
          <p className="ak-caption">Rejection is immediate and server-enforced.</p>
        </Dialog>
      ) : null}

      {editOpen ? (
        <Dialog
          title="Correct a field"
          description="Owner correction: typed, re-validated by the server, and audited. Policy re-runs automatically."
          onClose={() => setEditOpen(false)}
          actions={
            <>
              <Button variant="secondary" onClick={() => setEditOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={edit.isPending} onClick={submitEdit}>
                Save correction
              </Button>
            </>
          }
        >
          <Field label="Field" htmlFor="edit-field">
            <Select
              id="edit-field"
              value={editField}
              onChange={(event) => {
                setEditField(event.target.value);
                setEditText("");
                setEditError(null);
              }}
            >
              <option value="">Choose…</option>
              {editableFacts.map((fact) => (
                <option key={fact.id} value={fact.id}>
                  {fact.field}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={selectedFact && JSON_FACTS.includes(selectedFact.field) ? "New value (JSON)" : "New value"}
            htmlFor="edit-value"
            error={editError}
          >
            {selectedFact && JSON_FACTS.includes(selectedFact.field) ? (
              <TextArea
                id="edit-value"
                value={editText}
                rows={6}
                className="ak-mono"
                onChange={(event) => setEditText(event.target.value)}
              />
            ) : (
              <TextInput
                id="edit-value"
                value={editText}
                onChange={(event) => setEditText(event.target.value)}
              />
            )}
          </Field>
        </Dialog>
      ) : null}
    </div>
  );
}

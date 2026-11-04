/** Global audit trail (newest first) + hash-chain verification. Read-only. */

import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { PAGE_SIZE, useRecentAudit, useVerifyAudit } from "../api/hooks";
import type { AuditVerifyResult } from "../api/types";
import { Alert, EmptyState, ErrorState, PageHeader, Pagination, SkeletonRows } from "../components/feedback";
import { ListIcon } from "../components/icons";
import { AuditTimeline } from "../components/misc";
import { safeMessage } from "../utils/errors";

export function AuditPage(): React.JSX.Element {
  const [offset, setOffset] = useState(0);
  const query = useRecentAudit(PAGE_SIZE, offset);
  const verify = useVerifyAudit();
  const [result, setResult] = useState<AuditVerifyResult | null>(null);

  return (
    <div>
      <PageHeader
        title="Audit history"
        description="Tamper-evident event chain across all cases. Newest first; nothing here can be edited."
        actions={
          <button
            type="button"
            className="ak-btn ak-btn--secondary ak-btn--sm"
            disabled={verify.isPending}
            onClick={() =>
              verify.mutate(undefined, {
                onSuccess: (res) => setResult(res),
                onError: () => setResult(null),
              })
            }
          >
            {verify.isPending ? "Verifying…" : "Verify chain"}
          </button>
        }
      />
      {verify.isError ? (
        <Alert tone="danger">{safeMessage(verify.error)}</Alert>
      ) : null}
      {result ? (
        result.ok ? (
          <Alert tone="success">
            Chain verified: {result.events} events, no gaps or hash mismatches. Tamper-evident —
            a privileged attacker rewriting both records and hashes would still not be caught by
            this check alone.
          </Alert>
        ) : (
          <Alert tone="danger">
            Verification failed at event {result.break_at}: {result.reason ?? "unknown reason"} (
            {result.events} events scanned).
          </Alert>
        )
      ) : null}
      {query.isPending ? (
        <SkeletonRows rows={8} />
      ) : query.isError ? (
        <ErrorState
          title="Audit unavailable"
          message={safeMessage(query.error)}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          onRetry={() => void query.refetch()}
        />
      ) : query.data.events.length === 0 && offset === 0 ? (
        <EmptyState
          icon={<ListIcon />}
          title="No audit events"
          body="Events appear here as cases move through intake, policy, approval, and execution."
        />
      ) : (
        <div>
          <div className="ak-card">
            <AuditTimeline events={query.data.events} />
          </div>
          <Pagination
            limit={PAGE_SIZE}
            offset={offset}
            hasMore={query.data.events.length === PAGE_SIZE}
            onPrev={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            onNext={() => setOffset((o) => o + PAGE_SIZE)}
          />
          <p className="ak-caption" style={{ marginTop: 12 }}>
            Per-case trails live on each <Link to="/cases">case page</Link>.
          </p>
        </div>
      )}
    </div>
  );
}

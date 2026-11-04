/** Data-driven overview. Every number comes from /dashboard/summary. */

import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { PAGE_SIZE, useDashboard } from "../api/hooks";
import { CaseStateBadge } from "../components/badges";
import { EmptyState, ErrorState, PageHeader, SkeletonRows, Spinner } from "../components/feedback";
import { FileIcon, RefreshIcon } from "../components/icons";
import { formatDateTime } from "../utils/format";
import { safeMessage } from "../utils/errors";

export function DashboardPage(): React.JSX.Element {
  const query = useDashboard();

  if (query.isPending) {
    return (
      <div>
        <PageHeader title="Overview" description="Live totals from the verification backend." />
        <div className="ak-grid-4">
          {["a", "b", "c", "d"].map((k) => (
            <div className="ak-kpi" key={k} aria-hidden="true">
              <div className="ak-skeleton" style={{ height: 30, width: 80 }} />
              <div style={{ height: 8 }} />
              <div className="ak-skeleton" style={{ height: 14, width: 120 }} />
            </div>
          ))}
        </div>
        <div style={{ height: 16 }} />
        <SkeletonRows rows={5} />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div>
        <PageHeader title="Overview" description="Live totals from the verification backend." />
        <ErrorState
          title="Dashboard unavailable"
          message={safeMessage(query.error)}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const summary = query.data;
  const totalCases = Object.values(summary.cases_by_state).reduce((a, b) => a + b, 0);
  const needsReview = summary.cases_by_state.NEEDS_REVIEW ?? 0;
  const pendingProposals = summary.proposals_by_status.PENDING ?? 0;

  return (
    <div>
      <PageHeader
        title="Overview"
        description="Live totals from the verification backend. Nothing here is estimated."
        actions={
          <button
            type="button"
            className="ak-btn ak-btn--secondary ak-btn--sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            {query.isFetching ? <Spinner /> : <RefreshIcon />} Refresh
          </button>
        }
      />
      <div className="ak-grid-4">
        <Link className="ak-kpi" to="/cases">
          <div className="ak-kpi-label">Total cases</div>
          <div className="ak-kpi-value">{totalCases}</div>
          <div className="ak-kpi-sub">All states, all time</div>
        </Link>
        <Link className="ak-kpi" to="/cases">
          <div className="ak-kpi-label">Needs review</div>
          <div className="ak-kpi-value">{needsReview}</div>
          <div className="ak-kpi-sub">Escalated to the owner</div>
        </Link>
        <Link className="ak-kpi" to="/proposals">
          <div className="ak-kpi-label">Pending proposals</div>
          <div className="ak-kpi-value">{pendingProposals}</div>
          <div className="ak-kpi-sub">Awaiting approval decision</div>
        </Link>
        <div className="ak-kpi">
          <div className="ak-kpi-label">Mock executions</div>
          <div className="ak-kpi-value">{summary.payments_total}</div>
          <div className="ak-kpi-sub">Simulated only — no real funds</div>
        </div>
      </div>

      <div style={{ height: 24 }} />
      <h2 style={{ marginBottom: 12 }}>Recent cases</h2>
      {summary.recent_cases.length === 0 ? (
        <EmptyState
          icon={<FileIcon />}
          title="No cases yet"
          body="Submit the first invoice to start verification. Uploaded files are treated as untrusted evidence."
          actions={
            <Link className="ak-btn ak-btn--primary ak-btn--sm" to="/cases/new">
              New case
            </Link>
          }
        />
      ) : (
        <div className="ak-table-wrap">
          <table className="ak-table">
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">State</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {summary.recent_cases.map((row) => (
                <tr key={row.id} className="ak-rowlink">
                  <td>
                    <Link to={`/cases/${encodeURIComponent(row.id)}`} className="ak-mono">
                      {row.id}
                    </Link>
                  </td>
                  <td>
                    <CaseStateBadge state={row.state} />
                  </td>
                  <td className="ak-num">{formatDateTime(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="ak-caption" style={{ marginTop: 12 }}>
        Showing up to {Math.min(PAGE_SIZE, 5)} recent cases. Full history lives under Cases.
      </p>
    </div>
  );
}

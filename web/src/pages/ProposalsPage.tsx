/** Owner proposal queue, newest first. */

import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { PAGE_SIZE, useProposals } from "../api/hooks";
import { ProposalBadge } from "../components/badges";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  SkeletonRows,
} from "../components/feedback";
import { ShieldIcon } from "../components/icons";
import { formatDateTime, formatMoney } from "../utils/format";
import { safeMessage } from "../utils/errors";

export function ProposalsPage(): React.JSX.Element {
  const [offset, setOffset] = useState(0);
  const query = useProposals(PAGE_SIZE, offset);

  return (
    <div>
      <PageHeader
        title="Proposals"
        description="Policy-eligible payment proposals awaiting an owner decision. Approval always requires an explicit challenge."
      />
      {query.isPending ? (
        <SkeletonRows rows={8} />
      ) : query.isError ? (
        <ErrorState
          title="Proposals unavailable"
          message={safeMessage(query.error)}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          onRetry={() => void query.refetch()}
        />
      ) : query.data.proposals.length === 0 && offset === 0 ? (
        <EmptyState
          icon={<ShieldIcon />}
          title="No proposals"
          body="Eligible proposals appear here after a case evaluates to ALLOW_PROPOSAL."
          actions={
            <Link className="ak-btn ak-btn--secondary ak-btn--sm" to="/cases">
              Review cases
            </Link>
          }
        />
      ) : (
        <div>
          <div className="ak-table-wrap">
            <table className="ak-table">
              <thead>
                <tr>
                  <th scope="col">Proposal</th>
                  <th scope="col">Payee</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {query.data.proposals.map((row) => (
                  <tr key={row.proposal_id}>
                    <td>
                      <Link
                        to={`/proposals/${encodeURIComponent(row.proposal_id)}`}
                        className="ak-mono"
                      >
                        {row.proposal_id}
                      </Link>
                    </td>
                    <td>{row.payee_display_name}</td>
                    <td className="ak-num">{formatMoney(row.amount, row.currency)}</td>
                    <td>
                      <ProposalBadge status={row.status} />
                    </td>
                    <td className="ak-num">{formatDateTime(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            limit={PAGE_SIZE}
            offset={offset}
            hasMore={query.data.proposals.length === PAGE_SIZE}
            onPrev={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            onNext={() => setOffset((o) => o + PAGE_SIZE)}
          />
        </div>
      )}
    </div>
  );
}

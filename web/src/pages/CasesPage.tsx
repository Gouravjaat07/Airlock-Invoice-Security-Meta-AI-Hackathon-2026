/** Paginated case list. No filters: the API offers none, so none are faked. */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { PAGE_SIZE, useCases } from "../api/hooks";
import { CaseStateBadge } from "../components/badges";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  SkeletonRows,
} from "../components/feedback";
import { FileIcon } from "../components/icons";
import { formatDateTime } from "../utils/format";
import { safeMessage } from "../utils/errors";

export function CasesPage(): React.JSX.Element {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const query = useCases(PAGE_SIZE, offset);

  return (
    <div>
      <PageHeader
        title="Cases"
        description="Every submitted invoice, newest first. Select a row for the full review workspace."
        actions={
          <Link className="ak-btn ak-btn--primary ak-btn--sm" to="/cases/new">
            New case
          </Link>
        }
      />
      {query.isPending ? (
        <SkeletonRows rows={8} />
      ) : query.isError ? (
        <ErrorState
          title="Cases unavailable"
          message={safeMessage(query.error)}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          onRetry={() => void query.refetch()}
        />
      ) : query.data.cases.length === 0 && offset === 0 ? (
        <EmptyState
          icon={<FileIcon />}
          title="No cases yet"
          body="Submit the first invoice to start verification."
          actions={
            <Link className="ak-btn ak-btn--primary ak-btn--sm" to="/cases/new">
              New case
            </Link>
          }
        />
      ) : (
        <div>
          <div className="ak-table-wrap">
            <table className="ak-table">
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">State</th>
                  <th scope="col">Created</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {query.data.cases.map((row) => (
                  <tr
                    key={row.id}
                    className="ak-rowlink"
                    onClick={() => void navigate(`/cases/${encodeURIComponent(row.id)}`)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        void navigate(`/cases/${encodeURIComponent(row.id)}`);
                      }
                    }}
                    tabIndex={0}
                    aria-label={`Open case ${row.id}`}
                  >
                    <td className="ak-mono">{row.id}</td>
                    <td>
                      <CaseStateBadge state={row.state} />
                    </td>
                    <td className="ak-num">{formatDateTime(row.created_at)}</td>
                    <td className="ak-num">{formatDateTime(row.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            limit={PAGE_SIZE}
            offset={offset}
            hasMore={query.data.cases.length === PAGE_SIZE}
            onPrev={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            onNext={() => setOffset((o) => o + PAGE_SIZE)}
          />
        </div>
      )}
    </div>
  );
}

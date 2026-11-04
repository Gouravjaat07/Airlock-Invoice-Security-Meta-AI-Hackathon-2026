/** Provider status, exactly as the backend reports it. No live probing. */

import { ApiError } from "../api/client";
import { useProviders } from "../api/hooks";
import { AvailabilityBadge } from "../components/badges";
import { Alert, EmptyState, ErrorState, PageHeader, SkeletonRows, Spinner } from "../components/feedback";
import { CpuIcon, RefreshIcon } from "../components/icons";
import { Card } from "../components/misc";
import { humanizeState } from "../utils/format";
import { safeMessage } from "../utils/errors";

const TASK_LABELS: Record<string, string> = {
  invoice_extraction: "Invoice extraction",
  transcription: "Voice transcription",
  segmentation: "Visual segmentation",
};

export function ProvidersPage(): React.JSX.Element {
  const query = useProviders();

  return (
    <div>
      <PageHeader
        title="Providers"
        description="Configured model providers per task. Status reflects configuration and recent failures — never a live paid probe."
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
      {query.isPending ? (
        <SkeletonRows rows={4} />
      ) : query.isError ? (
        <ErrorState
          title="Provider status unavailable"
          message={safeMessage(query.error)}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          onRetry={() => void query.refetch()}
        />
      ) : query.data.providers.length === 0 ? (
        <EmptyState
          icon={<CpuIcon />}
          title="No providers configured"
          body="The backend reports no provider tasks. Extraction falls back to nothing — unconfigured tasks fail closed."
        />
      ) : (
        <div className="ak-stack">
          <Alert tone="info">
            “Ready” means configured and selectable, not that a live call succeeded. Credentials
            are never exposed here or to the browser.
          </Alert>
          <div className="ak-grid-3">
            {query.data.providers.map((item) => (
              <Card key={item.task} title={TASK_LABELS[item.task] ?? humanizeState(item.task)}>
                <div style={{ marginBottom: 10 }}>
                  <AvailabilityBadge availability={item.availability} />
                </div>
                <dl className="ak-dl" style={{ gridTemplateColumns: "88px 1fr" }}>
                  <dt>Provider</dt>
                  <dd>{item.provider}</dd>
                  <dt>Model</dt>
                  <dd className="ak-mono">{item.model}</dd>
                </dl>
                <p className="ak-caption" style={{ marginTop: 10 }}>
                  {item.reason || "No further detail."}
                </p>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

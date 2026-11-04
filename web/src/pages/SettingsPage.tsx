/** Read-only operational info: session, backend health, console notes. */

import { useSession } from "../auth/session";
import { useHealth } from "../api/hooks";
import { Alert, ErrorState, PageHeader, SkeletonRows } from "../components/feedback";
import { Card, CopyRef } from "../components/misc";
import { formatDateTime } from "../utils/format";
import { safeMessage } from "../utils/errors";

export function SettingsPage(): React.JSX.Element {
  const { sessionId, expiresAt } = useSession();
  const health = useHealth();

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Operational information. Airlock has no browser-editable server settings — policy, registry, and credentials are managed server-side."
      />
      <div className="ak-stack">
        <Card title="Session">
          <dl className="ak-dl">
            <dt>Owner session</dt>
            <dd>{sessionId ? <CopyRef value={sessionId} /> : "—"}</dd>
            <dt>Expires</dt>
            <dd>{formatDateTime(expiresAt)}</dd>
          </dl>
          <p className="ak-caption" style={{ marginTop: 10 }}>
            Authenticated over an HttpOnly cookie; the CSRF token lives in memory only and
            rotates automatically when rejected.
          </p>
        </Card>
        <Card title="Backend">
          {health.isPending ? (
            <SkeletonRows rows={4} />
          ) : health.isError ? (
            <ErrorState
              title="Health check failed"
              message={safeMessage(health.error)}
              onRetry={() => void health.refetch()}
            />
          ) : (
            <dl className="ak-dl">
              <dt>Status</dt>
              <dd>{health.data.status}</dd>
              <dt>Database</dt>
              <dd>{health.data.database}</dd>
              <dt>Version</dt>
              <dd className="ak-mono">{health.data.version}</dd>
              <dt>Schema</dt>
              <dd className="ak-num">v{health.data.schema_version}</dd>
              <dt>Policy</dt>
              <dd className="ak-mono">{health.data.policy_version}</dd>
            </dl>
          )}
        </Card>
        <Alert tone="info">
          This console executes <strong>mock payments only</strong>. It never sees provider API
          keys, the PIN hash, or bank secrets, and it cannot change verdicts, registry entries,
          or policy rules.
        </Alert>
      </div>
    </div>
  );
}

/** Feedback primitives: spinner, skeletons, states, alerts, headers, pager. */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertIcon, CheckCircleIcon, ChevronLeftIcon, ChevronRightIcon, InfoIcon } from "./icons";

export function Spinner({ label }: { label?: string }): React.JSX.Element {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className="ak-spinner" role="status" aria-label={label ?? "Loading"} />
      {label ? <span className="ak-caption">{label}</span> : null}
    </span>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }): React.JSX.Element {
  return (
    <div aria-hidden="true" style={{ display: "grid", gap: 10 }}>
      {Array.from({ length: rows }, (_, i) => (
        <div className="ak-skeleton" style={{ height: 18 }} key={i} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  actions?: ReactNode;
}): React.JSX.Element {
  return (
    <div className="ak-state">
      <span className="ak-state-icon">{icon ?? <InfoIcon />}</span>
      <h3>{title}</h3>
      <p>{body}</p>
      {actions ? <div className="ak-state-actions">{actions}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  message,
  requestId,
  onRetry,
}: {
  title: string;
  message: string;
  requestId?: string | null;
  onRetry?: () => void;
}): React.JSX.Element {
  return (
    <div className="ak-state" role="alert">
      <span className="ak-state-icon">
        <AlertIcon />
      </span>
      <h3>{title}</h3>
      <p>{message}</p>
      {requestId ? <p className="ak-caption ak-mono">ref {requestId}</p> : null}
      {onRetry ? (
        <div className="ak-state-actions">
          <button type="button" className="ak-btn ak-btn--secondary ak-btn--sm" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
    </div>
  );
}

type AlertTone = "danger" | "warning" | "success" | "info";

const ALERT_ICONS: Record<AlertTone, ReactNode> = {
  danger: <AlertIcon />,
  warning: <AlertIcon />,
  success: <CheckCircleIcon />,
  info: <InfoIcon />,
};

export function Alert({
  tone,
  children,
}: {
  tone: AlertTone;
  children: ReactNode;
}): React.JSX.Element {
  return (
    <div className={`ak-alert ak-alert--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      {ALERT_ICONS[tone]}
      <div>{children}</div>
    </div>
  );
}

export function PageHeader({
  crumb,
  title,
  description,
  actions,
}: {
  crumb?: { label: string; to: string };
  title: string;
  description?: string;
  actions?: ReactNode;
}): React.JSX.Element {
  return (
    <div>
      {crumb ? (
        <div className="ak-crumb">
          <Link to={crumb.to}>{crumb.label}</Link>
        </div>
      ) : null}
      <div className="ak-pagehead">
        <div>
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </div>
        {actions ? <div className="ak-pagehead-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export function Pagination({
  limit,
  offset,
  hasMore,
  onPrev,
  onNext,
}: {
  limit: number;
  offset: number;
  hasMore: boolean;
  onPrev: () => void;
  onNext: () => void;
}): React.JSX.Element {
  const page = Math.floor(offset / limit) + 1;
  return (
    <nav className="ak-pager" aria-label="Pagination">
      <span>Page {page}</span>
      <div className="ak-pager-buttons">
        <button
          type="button"
          className="ak-btn ak-btn--secondary ak-btn--sm"
          onClick={onPrev}
          disabled={offset === 0}
        >
          <ChevronLeftIcon /> Previous
        </button>
        <button
          type="button"
          className="ak-btn ak-btn--secondary ak-btn--sm"
          onClick={onNext}
          disabled={!hasMore}
        >
          Next <ChevronRightIcon />
        </button>
      </div>
    </nav>
  );
}

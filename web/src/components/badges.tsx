/** Semantic status badges. Icon + text always (never color alone). */

import type { ReactNode } from "react";
import { humanizeState } from "../utils/format";
import {
  AlertIcon,
  CheckCircleIcon,
  ClockIcon,
  InfoIcon,
  XCircleIcon,
} from "./icons";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "accent";

function Badge({ tone, icon, label, title }: { tone: Tone; icon: ReactNode; label: string; title?: string }): React.JSX.Element {
  return (
    <span className={`ak-badge ak-badge--${tone}`} title={title}>
      {icon}
      {label}
    </span>
  );
}

const CASE_TONES: Record<string, { tone: Tone; icon: ReactNode }> = {
  UPLOADED: { tone: "info", icon: <InfoIcon /> },
  READING: { tone: "info", icon: <ClockIcon /> },
  CORROBORATING: { tone: "info", icon: <ClockIcon /> },
  VERDICT: { tone: "info", icon: <ClockIcon /> },
  PROPOSED: { tone: "accent", icon: <InfoIcon /> },
  CONFIRMED: { tone: "success", icon: <CheckCircleIcon /> },
  EXECUTED: { tone: "success", icon: <CheckCircleIcon /> },
  REJECTED: { tone: "danger", icon: <XCircleIcon /> },
  NEEDS_REVIEW: { tone: "warning", icon: <AlertIcon /> },
  ERROR: { tone: "danger", icon: <XCircleIcon /> },
  CANCELLED: { tone: "neutral", icon: <XCircleIcon /> },
  EXPIRED: { tone: "neutral", icon: <ClockIcon /> },
};

export function CaseStateBadge({ state }: { state: string }): React.JSX.Element {
  const known = CASE_TONES[state];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={state} />;
  return <Badge tone={known.tone} icon={known.icon} label={humanizeState(state)} title={state} />;
}

const VERDICT_TONES: Record<string, { tone: Tone; icon: ReactNode; label: string }> = {
  ALLOW_PROPOSAL: { tone: "success", icon: <CheckCircleIcon />, label: "Allow proposal" },
  ESCALATE: { tone: "warning", icon: <AlertIcon />, label: "Escalate" },
  DENY: { tone: "danger", icon: <XCircleIcon />, label: "Deny" },
};

export function VerdictBadge({ verdict }: { verdict: string }): React.JSX.Element {
  const known = VERDICT_TONES[verdict];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={verdict} />;
  return <Badge tone={known.tone} icon={known.icon} label={known.label} title={verdict} />;
}

const PROPOSAL_TONES: Record<string, { tone: Tone; icon: ReactNode }> = {
  PENDING: { tone: "warning", icon: <ClockIcon /> },
  CONFIRMED: { tone: "success", icon: <CheckCircleIcon /> },
  EXPIRED: { tone: "neutral", icon: <ClockIcon /> },
  REJECTED: { tone: "danger", icon: <XCircleIcon /> },
};

export function ProposalBadge({ status }: { status: string }): React.JSX.Element {
  const known = PROPOSAL_TONES[status];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={status} />;
  return <Badge tone={known.tone} icon={known.icon} label={humanizeState(status)} title={status} />;
}

export function PaymentBadge({ status, mock }: { status: string; mock?: boolean }): React.JSX.Element {
  if (status === "MOCK_COMPLETED") {
    return <Badge tone="success" icon={<CheckCircleIcon />} label="Mock completed" title={mock === false ? status : `MOCK: ${status}`} />;
  }
  if (status === "FAILED") {
    return <Badge tone="danger" icon={<XCircleIcon />} label="Failed" title={status} />;
  }
  return <Badge tone="neutral" icon={<InfoIcon />} label={status} />;
}

const TAINT_LABELS: Record<string, { tone: Tone; label: string }> = {
  T0: { tone: "accent", label: "T0 · Owner" },
  T1: { tone: "info", label: "T1 · Trusted" },
  T2: { tone: "warning", label: "T2 · Model" },
  T3: { tone: "neutral", label: "T3 · Raw" },
};

export function TaintBadge({ taint }: { taint: string }): React.JSX.Element {
  const known = TAINT_LABELS[taint];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={taint} />;
  return <Badge tone={known.tone} icon={<InfoIcon />} label={known.label} title={taint} />;
}

const FIELD_STATUS_TONES: Record<string, { tone: Tone; icon: ReactNode }> = {
  CONFIRMED: { tone: "success", icon: <CheckCircleIcon /> },
  CONFLICT: { tone: "danger", icon: <XCircleIcon /> },
  UNCONFIRMED: { tone: "warning", icon: <AlertIcon /> },
  NOT_PROVIDED: { tone: "neutral", icon: <InfoIcon /> },
  NOT_APPLICABLE: { tone: "neutral", icon: <InfoIcon /> },
};

export function FieldStatusBadge({ status }: { status: string }): React.JSX.Element {
  const known = FIELD_STATUS_TONES[status];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={status} />;
  return <Badge tone={known.tone} icon={known.icon} label={humanizeState(status)} title={status} />;
}

const AVAILABILITY_TONES: Record<string, { tone: Tone; icon: ReactNode }> = {
  ready: { tone: "success", icon: <CheckCircleIcon /> },
  missing_credential: { tone: "danger", icon: <XCircleIcon /> },
  misconfigured: { tone: "danger", icon: <XCircleIcon /> },
  disabled: { tone: "warning", icon: <AlertIcon /> },
  breaker_open: { tone: "warning", icon: <AlertIcon /> },
  not_applicable: { tone: "neutral", icon: <InfoIcon /> },
};

const EVIDENCE_TONES: Record<string, { tone: Tone; icon: ReactNode }> = {
  uploaded: { tone: "info", icon: <InfoIcon /> },
  processing: { tone: "info", icon: <ClockIcon /> },
  validated: { tone: "success", icon: <CheckCircleIcon /> },
  rejected: { tone: "danger", icon: <XCircleIcon /> },
  evaluated: { tone: "info", icon: <InfoIcon /> },
  evaluated_empty: { tone: "warning", icon: <AlertIcon /> },
  conflict: { tone: "danger", icon: <XCircleIcon /> },
  not_evaluated: { tone: "warning", icon: <AlertIcon /> },
  failed: { tone: "danger", icon: <XCircleIcon /> },
};

export function EvidenceStatusBadge({ status, label }: { status: string; label: string }): React.JSX.Element {
  const known = EVIDENCE_TONES[status];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={label} title={status} />;
  return <Badge tone={known.tone} icon={known.icon} label={label} title={status} />;
}

export function AvailabilityBadge({ availability }: { availability: string }): React.JSX.Element {
  const known = AVAILABILITY_TONES[availability];
  if (!known) return <Badge tone="neutral" icon={<InfoIcon />} label={availability} />;
  return (
    <Badge tone={known.tone} icon={known.icon} label={humanizeState(availability)} title={availability} />
  );
}

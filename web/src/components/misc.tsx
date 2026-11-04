/** Tabs, audit timeline, copy-reference button. */

import { useRef, useState, type ReactNode } from "react";
import type { AuditEvent } from "../api/types";
import { formatDateTime, shortRef } from "../utils/format";
import { CopyIcon } from "./icons";

export interface TabItem {
  id: string;
  label: string;
}

export function Tabs({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  label: string;
}): React.JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (event: React.KeyboardEvent): void => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const index = tabs.findIndex((t) => t.id === active);
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    onChange(next.id);
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
    buttons?.[(index + delta + tabs.length) % tabs.length]?.focus();
  };

  return (
    <div ref={listRef} className="ak-tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          tabIndex={tab.id === active ? 0 : -1}
          className="ak-tab"
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function summarizePayload(payload: unknown): string {
  if (payload === null || payload === undefined) return "—";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload);
  } catch {
    return "[unreadable]";
  }
}

export function AuditTimeline({ events }: { events: AuditEvent[] }): React.JSX.Element {
  return (
    <ol className="ak-timeline">
      {events.map((event) => (
        <li key={event.id}>
          <div className="ak-t-head">
            <span className="ak-t-type">{event.event_type}</span>
            <span className="ak-t-time">{formatDateTime(event.ts)}</span>
          </div>
          <div className="ak-caption">
            {event.actor_type}
            {event.actor_id ? ` · ${shortRef(event.actor_id)}` : ""}
            {event.case_id ? ` · case ${shortRef(event.case_id)}` : " · global"}
            {` · #${event.id}`}
          </div>
          <details>
            <summary className="ak-caption" style={{ cursor: "pointer" }}>
              Payload
            </summary>
            <pre>{summarizePayload(event.payload)}</pre>
          </details>
        </li>
      ))}
    </ol>
  );
}

export function CopyRef({ value, label }: { value: string; label?: string }): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button type="button" className="ak-copybtn" onClick={() => void copy()} title={label ?? value}>
      <CopyIcon />
      <span>{copied ? "Copied" : shortRef(value)}</span>
    </button>
  );
}

export function Card({
  title,
  children,
  action,
}: {
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}): React.JSX.Element {
  return (
    <section className="ak-card">
      {title ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <h2 className="ak-card-title" style={{ marginBottom: 12 }}>
            {title}
          </h2>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

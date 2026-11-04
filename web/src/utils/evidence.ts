/**
 * Per-artifact evidence status, derived from artifacts + audit events.
 * The backend is authoritative: this module only maps recorded events to
 * display states. Unknown shapes stay unknown (never invented).
 */

import type { Artifact, AuditEvent } from "../api/types";

export type EvidenceStatus =
  | "uploaded"
  | "processing"
  | "validated"
  | "rejected"
  | "evaluated"
  | "evaluated_empty"
  | "conflict"
  | "not_evaluated"
  | "failed";

export interface EvidenceInfo {
  status: EvidenceStatus;
  label: string;
  detail: string | null;
  adapter: string | null;
  model: string | null;
  requestId: string | null;
  errorCode: string | null;
}

function asRecord(payload: unknown): Record<string, unknown> {
  if (typeof payload === "object" && payload !== null && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }
  return {};
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function asCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Latest event of a type, preferring the one linked to this artifact. */
function latestFor(events: AuditEvent[], type: string, artifact: Artifact): AuditEvent | null {
  const candidates = events.filter((e) => e.event_type === type);
  if (candidates.length === 0) return null;
  const linked = candidates.filter((e) => {
    const payload = asRecord(e.payload);
    return payload["artifact_id"] === artifact.id || payload["artifact_sha256"] === artifact.sha256;
  });
  const pool = linked.length > 0 ? linked : candidates;
  return pool.reduce((a, b) => (b.id > a.id ? b : a));
}

function hasType(events: AuditEvent[], type: string): boolean {
  return events.some((e) => e.event_type === type);
}

function invoiceInfo(_artifact: Artifact, events: AuditEvent[]): EvidenceInfo {
  const completed = latestFor(events, "reader.completed", _artifact);
  const done = completed ? asRecord(completed.payload) : {};
  const base = {
    adapter: asString(done["adapter"]),
    model: asString(done["model"]),
    requestId: asString(done["request_id"]),
    errorCode: null as string | null,
  };
  if (hasType(events, "extraction.validated")) {
    return { status: "validated", label: "Validated", detail: null, ...base };
  }
  const rejected = latestFor(events, "extraction.rejected", _artifact);
  if (rejected) {
    const errors = asRecord(rejected.payload)["errors"];
    const first = Array.isArray(errors) && errors.length > 0 ? asRecord(errors[0]) : {};
    const count = Array.isArray(errors) ? errors.length : 0;
    const message = asString(first["message"]) ?? asString(first["code"]);
    return {
      status: "rejected",
      label: "Rejected",
      detail: count > 0 ? `${count} schema error${count === 1 ? "" : "s"}${message ? `: ${message}` : ""}` : "Schema validation failed",
      ...base,
    };
  }
  const failed = latestFor(events, "reader.error", _artifact);
  if (failed) {
    const code = asString(asRecord(failed.payload)["code"]);
    return { status: "failed", label: "Failed", detail: null, ...base, errorCode: code };
  }
  if (hasType(events, "reader.started")) {
    return { status: "processing", label: "Processing", detail: "Reader started; no terminal record yet", ...base };
  }
  return { status: "uploaded", label: "Uploaded — not processed", detail: null, ...base };
}

function laneInfo(
  artifact: Artifact,
  events: AuditEvent[],
  type: string,
  emptyLabel: string,
): EvidenceInfo {
  const event = latestFor(events, type, artifact);
  const none: EvidenceInfo = {
    status: "uploaded",
    label: "Uploaded — not processed",
    detail: null,
    adapter: null,
    model: null,
    requestId: null,
    errorCode: null,
  };
  if (!event) return none;
  const payload = asRecord(event.payload);
  const status = asString(payload["status"]);
  const base = {
    adapter: asString(payload["adapter"]),
    model: asString(payload["model"]),
    requestId: asString(payload["request_id"]),
    errorCode: asString(payload["error_code"]) ?? asString(payload["code"]),
  };
  // Records predating the status field: infer from legacy keys.
  if (!status) {
    if (asString(payload["error"])) {
      return { status: "failed", label: "Failed", detail: asString(payload["error"]), ...base };
    }
    return { status: "evaluated", label: "Processed", detail: null, ...base };
  }
  if (status === "failed") {
    return { status: "failed", label: "Failed", detail: asString(payload["error"]), ...base };
  }
  if (status === "not_evaluated") {
    return {
      status: "not_evaluated",
      label: "Uploaded — not evaluated",
      detail: asString(payload["reason"]),
      ...base,
    };
  }
  if (status === "empty") {
    return { status: "evaluated_empty", label: emptyLabel, detail: asString(payload["reason"]), ...base };
  }
  if (status === "evaluated") {
    if (payload["conflict"] === true) {
      const detail = asRecord(event.payload)["conflict_detail"];
      const first = Array.isArray(detail) && detail.length > 0 ? String(detail[0]) : null;
      return { status: "conflict", label: "Conflict detected", detail: first, ...base };
    }
    const count = asCount(payload["count"]);
    if (count === 0) {
      return { status: "evaluated_empty", label: "Processed — 0 objects", detail: "Completed with zero detections", ...base };
    }
    return {
      status: "evaluated",
      label: count === null ? "Processed" : `Processed — ${count} object${count === 1 ? "" : "s"}`,
      detail: null,
      ...base,
    };
  }
  return none;
}

export function evidenceInfoFor(artifact: Artifact, events: AuditEvent[]): EvidenceInfo {
  if (artifact.kind === "voice") {
    return laneInfo(artifact, events, "voice.transcript", "Empty transcript");
  }
  if (artifact.kind === "delivery") {
    return laneInfo(artifact, events, "sam.evidence", "Processed — 0 objects");
  }
  return invoiceInfo(artifact, events);
}

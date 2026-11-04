import { describe, expect, it } from "vitest";
import type { Artifact, AuditEvent } from "../api/types";
import { evidenceInfoFor } from "./evidence";

const SHA = "ab".repeat(32);

function artifact(overrides: Partial<Artifact> = {}): Artifact {
  return { id: "art_1", kind: "invoice", media_type: "application/pdf", size_bytes: 42, sha256: SHA, ...overrides };
}

let nextId = 1;

function event(type: string, payload: unknown): AuditEvent {
  return {
    id: nextId++,
    ts: "2026-01-01T00:00:00+00:00",
    case_id: "case_1",
    event_type: type,
    actor_type: "system",
    actor_id: null,
    payload,
    prev_hash: "GENESIS",
    event_hash: "x",
  };
}

describe("evidenceInfoFor", () => {
  it("marks artifacts with no records as uploaded", () => {
    const info = evidenceInfoFor(artifact({ kind: "voice" }), []);
    expect(info.status).toBe("uploaded");
    expect(info.label).toMatch(/not processed/i);
  });

  it("distinguishes invoice validated / rejected / failed / processing", () => {
    const art = artifact();
    expect(evidenceInfoFor(art, [event("extraction.validated", {})]).status).toBe("validated");
    const rejected = evidenceInfoFor(
      art,
      [event("extraction.rejected", { errors: [{ code: "currency", message: "bad" }] })],
    );
    expect(rejected.status).toBe("rejected");
    expect(rejected.detail).toContain("1 schema error");
    expect(evidenceInfoFor(art, [event("reader.error", { code: "E_API" })]).status).toBe("failed");
    expect(evidenceInfoFor(art, [event("reader.started", {})]).status).toBe("processing");
  });

  it("carries reader provenance for invoices", () => {
    const info = evidenceInfoFor(
      artifact(),
      [
        event("reader.completed", { adapter: "meta-spark", model: "muse-spark-1.3", request_id: "resp_1" }),
        event("extraction.validated", {}),
      ],
    );
    expect(info.adapter).toBe("meta-spark");
    expect(info.model).toBe("muse-spark-1.3");
    expect(info.requestId).toBe("resp_1");
  });

  it("maps voice lane statuses without collapsing them", () => {
    const art = artifact({ kind: "voice" });
    const done = evidenceInfoFor(
      art,
      [event("voice.transcript", { status: "evaluated", conflict: false, adapter: "meta-voice", model: "muse-voice-transcribe-1.0" })],
    );
    expect(done.status).toBe("evaluated");
    expect(done.model).toBe("muse-voice-transcribe-1.0");

    const conflict = evidenceInfoFor(
      art,
      [event("voice.transcript", { status: "evaluated", conflict: true, conflict_detail: ["PO mismatch"] })],
    );
    expect(conflict.status).toBe("conflict");
    expect(conflict.detail).toBe("PO mismatch");

    const empty = evidenceInfoFor(art, [event("voice.transcript", { status: "empty" })]);
    expect(empty.status).toBe("evaluated_empty");

    const skipped = evidenceInfoFor(
      art,
      [event("voice.transcript", { status: "not_evaluated", reason: "no extraction" })],
    );
    expect(skipped.status).toBe("not_evaluated");
    expect(skipped.detail).toBe("no extraction");

    const failed = evidenceInfoFor(
      art,
      [event("voice.transcript", { status: "failed", error: "boom", error_code: "server" })],
    );
    expect(failed.status).toBe("failed");
    expect(failed.errorCode).toBe("server");
  });

  it("maps sam lane statuses including zero-object completion", () => {
    const art = artifact({ kind: "delivery" });
    const zero = evidenceInfoFor(
      art,
      [event("sam.evidence", { status: "evaluated", count: 0, frames: 0, adapter: "meta-sam", model: "sam-3.1" })],
    );
    expect(zero.status).toBe("evaluated_empty");
    expect(zero.adapter).toBe("meta-sam");

    const count = evidenceInfoFor(art, [event("sam.evidence", { status: "evaluated", count: 30 })]);
    expect(count.status).toBe("evaluated");
    expect(count.label).toContain("30");

    const skipped = evidenceInfoFor(art, [event("sam.evidence", { status: "not_evaluated", reason: "vendor unresolved" })]);
    expect(skipped.status).toBe("not_evaluated");

    const failed = evidenceInfoFor(art, [event("sam.evidence", { status: "failed", error_code: "timeout" })]);
    expect(failed.status).toBe("failed");
    expect(failed.errorCode).toBe("timeout");
  });

  it("prefers the record linked to the artifact", () => {
    const first = artifact({ id: "art_1", kind: "voice", sha256: "aa" });
    const second = artifact({ id: "art_2", kind: "voice", sha256: "bb" });
    const events = [
      event("voice.transcript", { status: "failed", artifact_sha256: "aa", error_code: "server" }),
      event("voice.transcript", { status: "evaluated", conflict: false, artifact_sha256: "bb" }),
    ];
    expect(evidenceInfoFor(first, events).status).toBe("failed");
    expect(evidenceInfoFor(second, events).status).toBe("evaluated");
  });

  it("tolerates legacy records without a status field", () => {
    const art = artifact({ kind: "voice" });
    expect(evidenceInfoFor(art, [event("voice.transcript", { conflict: false })]).status).toBe("evaluated");
    expect(evidenceInfoFor(art, [event("voice.transcript", { error: "boom" })]).status).toBe("failed");
    expect(evidenceInfoFor(art, [event("voice.transcript", null)]).status).toBe("evaluated");
  });
});

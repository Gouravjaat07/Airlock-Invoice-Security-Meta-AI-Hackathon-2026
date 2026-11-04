"""Currency + R7 end-to-end: mocked providers, real pipeline/policy.

Reproduces the live `case_mw1...` failure (`extraction.rejected` code
`currency`) without live calls: Spark returns controlled currency
variants, voice/SAM run on stubbed transports, and the test asserts
extraction, lane, and R7 outcomes together.
"""

from __future__ import annotations

import json
import struct

import httpx

from app.providers.http import POOL
from app.services import case_service
from app.storage.repositories import AuditRepository, FactRepository
from tests.conftest import ROOT_DIR, fixture_bytes
from tests.providers.helpers import responses_ok

BOX8 = "<|box;x1=0;y1=0;x2=7;y2=7;w=8;h=8|>"
MASK = "<|mask;x=0;y=0;data=1,1,!!!!!&!!!!!|>"


def _clean_extraction() -> dict:
    spec = json.loads((ROOT_DIR / "fixtures" / "scenarios" / "clean.json").read_text())
    return dict(spec["extraction"])


def _sse_completed(lane: str) -> bytes:
    body = (
        "event: response.completed\n"
        f"data: {json.dumps({'response': responses_ok(lane, model='sam-3.1')})}\n\n"
    )
    return body.encode()


def _wav(seconds: float = 0.5) -> bytes:
    frames = int(16000 * seconds)
    data = b"\x00" * (frames * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    chunks = struct.pack("<4sI", b"fmt ", 16) + fmt
    chunks += struct.pack("<4sI", b"data", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def _lane(count: int) -> str:
    if count == 0:
        return ""
    return "<0f>" + ",".join(f"{i}{BOX8}{MASK}" for i in range(1, count + 1))


def _router(extraction_json: str, lane: str, transcript: str):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/asr/transcribe"):
            return httpx.Response(200, json={
                "sessionId": "sess_9", "transcript": transcript,
                "audioDurationMs": 500,
                "turns": [{"turnId": 1, "startMs": 0, "endMs": 500,
                           "transcript": transcript}]})
        if path.endswith("/responses"):
            body = json.loads(request.content.decode())
            if str(body.get("model", "")).startswith("sam-"):
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    content=_sse_completed(lane))
            return httpx.Response(200, json=responses_ok(extraction_json))
        raise AssertionError(f"unexpected path {path}")

    return httpx.MockTransport(handler)


def _setup(settings):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0


def _process(seeded_db, settings, store, files):
    created = case_service.create_case(seeded_db, settings, store, files)
    return case_service.process_case(seeded_db, settings, store,
                                     created["case"]["id"])


def _audit(seeded_db, case_id, event_type):
    events = AuditRepository().list_for_case(seeded_db, case_id)
    return [json.loads(e["payload_json"]) for e in events
            if e["event_type"] == event_type]


def _r7_reason(summary) -> tuple[str, str]:
    details = json.loads(summary["verdict"]["rule_details_json"])
    r7 = next(d for d in details if d["rule_id"] == "R7")
    return r7["reason_code"], r7["message"]


def test_extraction_failure_currency_ambiguous_marks_lanes_not_evaluated(
        seeded_db, settings, store):
    """Live-issue reproduction: `$` fails, lanes transcribe but never compare."""
    _setup(settings)
    extraction = _clean_extraction()
    extraction["currency"] = "$"  # ambiguous: never USD
    transport = _router(json.dumps(extraction), _lane(30),
                        "purchase order PO-1001 confirmed, thirty items")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "DENY"
    assert "R8" in json.loads(result["verdict"]["rule_ids_json"])
    assert result["proposal"] is None
    # Actionable structured error, not a bare pattern mismatch.
    rejected = _audit(seeded_db, result["case"]["id"], "extraction.rejected")
    assert len(rejected) == 1
    err = rejected[0]["errors"][0]
    assert err["code"] == "currency"
    assert "Ambiguous" in err["message"]
    assert "ISO 4217" in err["message"]
    # Voice transcribed independently, comparison skipped.
    voice = _audit(seeded_db, result["case"]["id"], "voice.transcript")[0]
    assert voice["status"] == "not_evaluated"
    assert voice["adapter"] == "meta-voice"
    assert voice["conflict"] is False
    # SAM uploaded but vendor unresolved (no extraction).
    sam = _audit(seeded_db, result["case"]["id"], "sam.evidence")[0]
    assert sam["status"] == "not_evaluated"
    assert "count" not in sam
    # R7 must not claim consistency.
    reason, message = _r7_reason(result)
    assert reason == "evidence-not-evaluated"
    assert "delivery" in message and "voice" in message


def test_successful_extraction_lowercase_enables_lanes(seeded_db, settings, store):
    _setup(settings)
    extraction = _clean_extraction()
    extraction["currency"] = "usd"  # safely uppercases to USD
    transport = _router(json.dumps(extraction), _lane(30),
                        "thirty items received in good condition")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    facts = {f["field"]: json.loads(f["value_json"])
             for f in FactRepository().list_for_case(seeded_db, result["case"]["id"])}
    assert facts["currency"] == "USD"
    assert facts["total"] == "1240.00"  # amounts preserved
    voice = _audit(seeded_db, result["case"]["id"], "voice.transcript")[0]
    assert voice["status"] == "evaluated"
    assert voice["conflict"] is False
    sam = _audit(seeded_db, result["case"]["id"], "sam.evidence")[0]
    assert sam["status"] == "evaluated"
    assert sam["count"] == 30
    reason, _ = _r7_reason(result)
    assert reason == "evidence-consistent"


def test_voice_conflict_escalates_after_success(seeded_db, settings, store):
    _setup(settings)
    extraction = _clean_extraction()
    transport = _router(json.dumps(extraction), _lane(30),
                        "regarding purchase order PO-9999")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R7" in json.loads(result["verdict"]["rule_ids_json"])
    voice = _audit(seeded_db, result["case"]["id"], "voice.transcript")[0]
    assert voice["status"] == "evaluated"
    assert voice["conflict"] is True


def test_sam_empty_result_escalates(seeded_db, settings, store):
    _setup(settings)
    extraction = _clean_extraction()
    transport = _router(json.dumps(extraction), _lane(0), "thirty items")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png"))]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R7" in json.loads(result["verdict"]["rule_ids_json"])
    sam = _audit(seeded_db, result["case"]["id"], "sam.evidence")[0]
    assert sam["status"] == "evaluated"
    assert sam["count"] == 0


def test_partial_provider_failure_voice_fails_sam_succeeds(
        seeded_db, settings, store):
    _setup(settings)
    extraction = _clean_extraction()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/asr/transcribe"):
            return httpx.Response(500, json={"error": {"message": "boom"}})
        body = json.loads(request.content.decode())
        if str(body.get("model", "")).startswith("sam-"):
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content=_sse_completed(_lane(30)))
        return httpx.Response(200, json=responses_ok(json.dumps(extraction)))

    transport = httpx.MockTransport(handler)
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    # Voice is optional: failure is recorded, invoice still allows.
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    voice = _audit(seeded_db, result["case"]["id"], "voice.transcript")[0]
    assert voice["status"] == "failed"
    sam = _audit(seeded_db, result["case"]["id"], "sam.evidence")[0]
    assert sam["status"] == "evaluated"
    reason, message = _r7_reason(result)
    assert reason == "evidence-not-evaluated"
    assert "voice" in message


def test_non_usd_currency_preserved_not_schema_failure(
        seeded_db, settings, store):
    _setup(settings)
    extraction = _clean_extraction()
    extraction["currency"] = "EUR"
    transport = _router(json.dumps(extraction), _lane(30), "thirty items")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf"))]
    result = _process(seeded_db, settings, store, files)
    # EUR validates (not R8); the USD-only PO mismatches (R5 ESCALATE).
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R8" not in json.loads(result["verdict"]["rule_ids_json"])
    facts = {f["field"]: json.loads(f["value_json"])
             for f in FactRepository().list_for_case(seeded_db, result["case"]["id"])}
    assert facts["currency"] == "EUR"

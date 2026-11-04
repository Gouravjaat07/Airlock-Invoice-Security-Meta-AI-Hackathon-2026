"""Provider pipeline integration: real services, stubbed network only.

Uses the real database layer, migrations, pipeline, and policy engine;
only the HTTP boundary is stubbed (POOL test transports). Proves the
live-provider path end to end without credentials or network.
"""

from __future__ import annotations

import json
import struct

import httpx
import pytest

from app.core.errors import AppError
from app.providers.http import POOL
from app.services import case_service
from app.storage.repositories import AuditRepository, FactRepository
from tests.conftest import ROOT_DIR, fixture_bytes
from tests.providers.helpers import responses_ok

BOX8 = "<|box;x1=0;y1=0;x2=7;y2=7;w=8;h=8|>"
# 1x1 one_bit mask decoding to [0] (hand-verified vector).
MASK = "<|mask;x=0;y=0;data=1,1,!!!!!&!!!!!|>"


def _clean_extraction_json() -> str:
    spec = json.loads((ROOT_DIR / "fixtures" / "scenarios" / "clean.json").read_text())
    return json.dumps(spec["extraction"])


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


def _process(seeded_db, settings, store, files):
    created = case_service.create_case(seeded_db, settings, store, files)
    return case_service.process_case(seeded_db, settings, store,
                                     created["case"]["id"])


def test_spark_pipeline_allow_with_provenance(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    POOL.set_test_transport("meta:180", _router(_clean_extraction_json(),
                                                _lane(30), "thirty items"))
    invoice = ("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf"))
    result = _process(seeded_db, settings, store, [invoice])
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert result["proposal"] is not None
    facts = FactRepository().list_for_case(seeded_db, result["case"]["id"])
    producers = [json.loads(fact["producer_json"]) for fact in facts]
    assert producers, "facts must carry producer provenance"
    assert all(producer["adapter"] == "meta-spark" for producer in producers)
    assert all(producer["model_id"] == "muse-spark-1.3" for producer in producers)
    assert all(producer["request_id"] == "resp_1" for producer in producers)
    events = AuditRepository().list_for_case(seeded_db, result["case"]["id"])
    completed = [event for event in events
                 if event["event_type"] == "reader.completed"]
    assert len(completed) == 1
    payload = json.loads(completed[0]["payload_json"])
    assert payload["usage"]["attempts"] == 1
    assert payload["model"] == "muse-spark-1.3"


def test_spark_evidence_pages_become_fact_provenance(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    extraction = json.loads(_clean_extraction_json())
    extraction["evidence"] = {"pages": {"total": 1, "vendor_name": 1}}
    POOL.set_test_transport("meta:180", _router(json.dumps(extraction),
                                                _lane(30), "x"))
    invoice = ("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf"))
    result = _process(seeded_db, settings, store, [invoice])
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    facts = FactRepository().list_for_case(seeded_db, result["case"]["id"])
    by_field = {fact["field"]: json.loads(fact["source_json"])
                for fact in facts}
    assert by_field["total"]["page"] == 1
    assert by_field["vendor_name"]["page"] == 1
    assert by_field["tax"]["page"] is None


def test_spark_bad_content_denies_r8(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    POOL.set_test_transport("meta:180", _router("not json{{", _lane(30), "x"))
    invoice = ("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf"))
    result = _process(seeded_db, settings, store, [invoice])
    assert result["verdict"]["verdict"] == "DENY"
    assert "R8" in json.loads(result["verdict"]["rule_ids_json"])


def test_spark_transport_failure_is_error_not_fallback(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    POOL.set_test_transport("meta:180", httpx.MockTransport(handler))
    invoice = ("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf"))
    created = case_service.create_case(seeded_db, settings, store, [invoice])
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    # Explicit failure, never a silent fixture reroute.
    assert exc_info.value.code == "E_API_UNAVAILABLE"


def test_voice_and_sam_live_paths(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router(_clean_extraction_json(), _lane(30),
                        "thirty items received in good condition")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    events = AuditRepository().list_for_case(seeded_db, result["case"]["id"])
    by_type = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(
            json.loads(event["payload_json"]))
    assert by_type["sam.evidence"][0]["count"] == 30
    assert by_type["sam.evidence"][0]["model"] == "sam-3.1"
    assert by_type["voice.transcript"][0]["turns"] == 1
    assert by_type["voice.transcript"][0]["conflict"] is False


def test_sam_mismatch_escalates_r7(seeded_db, settings, store):
    settings.voice_provider = "mock"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router(_clean_extraction_json(), _lane(2), "x")
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png"))]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R7" in json.loads(result["verdict"]["rule_ids_json"])


def _voice_files():
    return [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
            ("voice", "note.wav", _wav())]


def _voice_payloads(seeded_db, case_id):
    events = AuditRepository().list_for_case(seeded_db, case_id)
    return [json.loads(event["payload_json"]) for event in events
            if event["event_type"] == "voice.transcript"]


def test_voice_transcribed_despite_extraction_failure(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router("not json{{", _lane(30),
                        "purchase order PO-1001 confirmed")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _voice_files())
    assert result["verdict"]["verdict"] == "DENY"
    assert result["proposal"] is None
    payloads = _voice_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "not_evaluated"
    assert payloads[0]["adapter"] == "meta-voice"
    assert payloads[0]["model"] == "muse-voice-transcribe-1.0"
    assert payloads[0]["artifact_sha256"]
    assert payloads[0]["conflict"] is False


def test_voice_empty_transcript_never_confirms(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router(_clean_extraction_json(), _lane(30), "   ")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _voice_files())
    payloads = _voice_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "empty"
    assert payloads[0]["conflict"] is False


def test_voice_provider_failure_recorded_not_fatal(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/asr/transcribe"):
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(200, json=responses_ok(
            _clean_extraction_json()))

    transport = httpx.MockTransport(handler)
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _voice_files())
    assert result["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    payloads = _voice_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["error_code"] == "server"


def _sam_payloads(seeded_db, case_id):
    events = AuditRepository().list_for_case(seeded_db, case_id)
    return [json.loads(event["payload_json"]) for event in events
            if event["event_type"] == "sam.evidence"]


def _delivery_files():
    return [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
            ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png"))]


def test_sam_empty_stream_never_confirms(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router(_clean_extraction_json(), "", "x")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _delivery_files())
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R7" in json.loads(result["verdict"]["rule_ids_json"])
    payloads = _sam_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "evaluated"
    assert payloads[0]["count"] == 0
    assert payloads[0]["frames"] == 0
    assert payloads[0]["adapter"] == "meta-sam"


def test_sam_delivery_unevaluated_when_extraction_fails(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router("not json{{", _lane(30), "x")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _delivery_files())
    assert result["verdict"]["verdict"] == "DENY"
    assert result["proposal"] is None
    payloads = _sam_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "not_evaluated"
    assert payloads[0]["artifact_sha256"]
    assert "count" not in payloads[0]


def test_sam_provider_failure_denies_r9(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if str(body.get("model", "")).startswith("sam-"):
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(200, json=responses_ok(
            _clean_extraction_json()))

    transport = httpx.MockTransport(handler)
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _delivery_files())
    assert result["verdict"]["verdict"] == "DENY"
    assert "R9" in json.loads(result["verdict"]["rule_ids_json"])
    payloads = _sam_payloads(seeded_db, result["case"]["id"])
    assert len(payloads) == 1
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["error_code"] == "server"


def test_multimodal_failure_marks_both_lanes(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.vision_provider = "sam"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router("not json{{", _lane(30), "purchase order PO-1001")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    files = [("invoice", "clean.pdf", fixture_bytes("invoices/clean.pdf")),
             ("delivery", "sam-ok.png", fixture_bytes("delivery/sam-ok.png")),
             ("voice", "note.wav", _wav())]
    result = _process(seeded_db, settings, store, files)
    assert result["verdict"]["verdict"] == "DENY"
    case_id = result["case"]["id"]
    assert _voice_payloads(seeded_db, case_id)[0]["status"] == "not_evaluated"
    assert _sam_payloads(seeded_db, case_id)[0]["status"] == "not_evaluated"


def test_voice_po_mismatch_escalates_r7(seeded_db, settings, store):
    settings.reader_provider = "spark"
    settings.voice_provider = "meta"
    settings.model_api_key = "tk"
    settings.provider_max_retries = 0
    transport = _router(_clean_extraction_json(), _lane(30),
                        "regarding purchase order PO-9999")
    POOL.set_test_transport("meta:180", transport)
    POOL.set_test_transport("meta:300", transport)
    result = _process(seeded_db, settings, store, _voice_files())
    assert result["verdict"]["verdict"] == "ESCALATE"
    assert "R7" in json.loads(result["verdict"]["rule_ids_json"])
    payloads = _voice_payloads(seeded_db, result["case"]["id"])
    assert payloads[0]["status"] == "evaluated"
    assert payloads[0]["conflict"] is True
    assert "PO-9999" in payloads[0]["conflict_detail"][0]

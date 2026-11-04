"""Adapter integration tests: request shapes + stubbed responses.

Every test runs offline via MockTransport at the network boundary.
Fake credentials are inert markers; assertions verify placement
(auth header, multipart field, chat vs Responses paths) without
ever printing secret values.
"""

from __future__ import annotations

import json
import struct

import httpx
import pytest

from app.core.errors import AppError
from app.providers.baseten import BasetenSparkReader
from app.providers.glimmer import GlimmerReader, preflight
from app.providers.sam import MetaSamSegmenter
from app.providers.spark import SparkReader
from app.providers.voice import MetaVoiceTranscriber
from tests.providers.helpers import (
    FAKE_KEY,
    chat_ok,
    error_envelope,
    provider_settings,
    responses_ok,
    stub_transport,
    valid_extraction_json,
)


def _pdf(pages: int = 1) -> bytes:
    body = b"%PDF-1.4\n"
    for _ in range(pages):
        body += b"1 0 obj<</Type /Page>>endobj\n"
    return body + b"trailer<<>>\n%%EOF\n"


def _png(width: int = 8, height: int = 8) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" +
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0) +
            b"\x00" * 4)


def _wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    frames = int(rate * seconds)
    data = b"\x00" * (frames * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    chunks = struct.pack("<4sI", b"fmt ", 16) + fmt
    chunks += struct.pack("<4sI", b"data", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def _sse_completed(lane: str, **kw) -> bytes:
    body = (
        "event: response.output_text.delta\n"
        f"data: {json.dumps({'delta': lane})}\n\n"
        "event: response.completed\n"
        f"data: {json.dumps({'response': responses_ok(lane, **kw)})}\n\n"
    )
    return body.encode()


BOX8 = "<|box;x1=0;y1=0;x2=7;y2=7;w=8;h=8|>"
# 1x1 one_bit mask decoding to [0] (hand-verified vector).
MASK = "<|mask;x=0;y=0;data=1,1,!!!!!&!!!!!|>"
MASK_BAD = "<|mask;x=0;y=0;data=1,1,~ABCD|>"  # grammar-valid, undecodable


# --- Spark reader -------------------------------------------------------


def test_spark_pdf_request_shape_and_success():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=responses_ok(valid_extraction_json()))

    reader = SparkReader(provider_settings(),
                         transport=stub_transport(handler))
    result = reader.read(_pdf())
    assert seen["url"].endswith("/responses")
    assert seen["auth"] == "Bearer " + FAKE_KEY
    body = seen["body"]
    assert body["model"] == "muse-spark-1.3"
    assert body["store"] is False
    assert "temperature" not in body
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is False
    assert body["max_output_tokens"] == 4096
    assert "Do NOT approve" in body["instructions"]
    content = body["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_file"
    assert content[1]["file_data"].startswith("data:application/pdf;base64,")
    assert content[1]["filename"] == "invoice.pdf"
    assert result.payload["total"] == "1240.00"
    assert result.model_id == "muse-spark-1.3"
    assert result.request_id == "resp_1"
    assert result.prompt_version == "airlock-extraction/5"
    assert result.usage["attempts"] == 1


def test_spark_image_uses_input_image():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=responses_ok(valid_extraction_json()))

    reader = SparkReader(provider_settings(),
                         transport=stub_transport(handler))
    reader.read(_png())
    content = seen["body"]["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("status,envelope,code", [
    (429, error_envelope("slow", code="rate_limit_exceeded"), "E_RATE_LIMIT"),
    (500, error_envelope("boom"), "E_API_UNAVAILABLE"),
    (401, error_envelope("no", code="invalid_api_key"), "E_API_UNAVAILABLE"),
])
def test_spark_http_errors_mapped(status, envelope, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=envelope)

    reader = SparkReader(provider_settings(),
                         transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        reader.read(_pdf())
    assert exc_info.value.code == code
    assert FAKE_KEY not in str(exc_info.value)


def test_spark_malformed_content_is_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses_ok("not json{{"))

    reader = SparkReader(provider_settings(),
                         transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        reader.read(_pdf())
    assert exc_info.value.code == "E_SCHEMA"


def test_spark_retries_transient_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json=error_envelope("boom"))
        return httpx.Response(200, json=responses_ok(valid_extraction_json()))

    settings = provider_settings(provider_max_retries=1)
    reader = SparkReader(settings, transport=stub_transport(handler))
    result = reader.read(_pdf())
    assert result.usage["attempts"] == 2
    assert result.payload["invoice_number"] == "INV-2026-0001"


# --- Baseten reader ------------------------------------------------------


def test_baseten_image_shape_and_pdf_refusal():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=chat_ok(valid_extraction_json()))

    reader = BasetenSparkReader(provider_settings(),
                                transport=stub_transport(handler))
    result = reader.read(_png())
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer " + FAKE_KEY
    body = seen["body"]
    assert body["model"] == "meta-models/muse-spark-open-1026"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"][1]["type"] == "image_url"
    assert result.payload["total"] == "1240.00"
    with pytest.raises(AppError) as exc_info:
        reader.read(_pdf())
    assert exc_info.value.code == "E_API_UNAVAILABLE"
    assert "images only" in exc_info.value.message


def test_baseten_truncation_is_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_ok('{"total": "1',
                                                finish="length"))

    reader = BasetenSparkReader(provider_settings(),
                                transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        reader.read(_png())
    # Protocol-level truncation is a retryable provider failure.
    assert exc_info.value.code == "E_API_UNAVAILABLE"


# --- Glimmer reader ------------------------------------------------------


def test_glimmer_image_shape_and_preflight():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "muse-glimmer"}]})
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=chat_ok(valid_extraction_json(),
                                                model="muse-glimmer"))

    settings = provider_settings(reader_provider="glimmer")
    transport = stub_transport(handler)
    probe = preflight(settings, transport=transport)
    assert probe == {"available": True, "models": ["muse-glimmer"],
                     "reason": "ok"}
    reader = GlimmerReader(settings, transport=transport)
    result = reader.read(_png())
    assert seen["body"]["model"] == "muse-glimmer"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is False
    assert result.model_id == "muse-glimmer"
    with pytest.raises(AppError):
        reader.read(_pdf())


def test_glimmer_preflight_pool_key_isolated(monkeypatch):
    from app.providers.http import POOL

    seen_keys: list[tuple[str, float]] = []
    real_get = POOL.get

    def spy(key, **kwargs):
        seen_keys.append((key, kwargs.get("read_timeout_s")))
        return real_get(key, **kwargs)

    monkeypatch.setattr(POOL, "get", spy)
    settings = provider_settings(reader_provider="glimmer")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "muse-glimmer"}]})

    preflight(settings, transport=stub_transport(handler))
    assert len(seen_keys) == 1
    key, read_timeout = seen_keys[0]
    assert key != f"glimmer:{settings.extraction_timeout_s}"
    assert key.startswith("glimmer-preflight:")
    assert read_timeout == settings.provider_connect_timeout_s


def test_glimmer_preflight_states():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    probe = preflight(provider_settings(),
                      transport=stub_transport(unreachable))
    assert probe["available"] is False
    assert "unreachable" in probe["reason"]

    def wrong_model(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "other"}]})

    probe = preflight(provider_settings(),
                      transport=stub_transport(wrong_model))
    assert probe["available"] is False
    assert "not served" in probe["reason"]

    def bad_status(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    probe = preflight(provider_settings(),
                      transport=stub_transport(bad_status))
    assert probe["available"] is False


# --- Voice ---------------------------------------------------------------


def test_voice_multipart_shape_and_turns():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["ctype"] = request.headers.get("content-type")
        seen["raw"] = bytes(request.content)
        return httpx.Response(200, json={
            "sessionId": "sess_1",
            "transcript": "ten boxes delivered",
            "audioDurationMs": 500,
            "turns": [{"turnId": 1, "startMs": 0, "endMs": 500,
                       "transcript": "ten boxes delivered",
                       "speaker": "SPEAKER_00"}]})

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    transcript = transcriber.transcribe(_wav())
    assert "/asr/transcribe" in seen["url"]
    assert "sessionId=" in seen["url"]
    assert seen["auth"] == "Bearer " + FAKE_KEY
    assert seen["ctype"].startswith("multipart/form-data")
    assert b"voice.wav" in seen["raw"]
    assert b"PUSH_TO_TALK" in seen["raw"]
    assert transcript.text == "ten boxes delivered"
    assert len(transcript.turns) == 1
    assert transcript.turns[0]["turn_id"] == "1"
    assert transcript.turns[0]["speaker"] == "SPEAKER_00"
    assert transcript.request_id == "sess_1"
    assert transcript.model_id == "muse-voice-transcribe-1.0"


def test_voice_string_turn_id_accepted_defensively():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "transcript": "x",
            "turns": [{"turnId": "t1", "startMs": 0, "endMs": 1,
                       "transcript": "x"}]})

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    transcript = transcriber.transcribe(_wav())
    assert transcript.turns[0]["turn_id"] == "t1"


def test_voice_duplicate_turn_id_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "transcript": "x",
            "turns": [{"turnId": 1, "startMs": 0, "endMs": 1,
                       "transcript": "x"},
                      {"turnId": "1", "startMs": 1, "endMs": 2,
                       "transcript": "x"}]})

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(_wav())
    assert exc_info.value.code == "E_SCHEMA"


def test_voice_rejects_non_wav_and_bad_format():
    transcriber = MetaVoiceTranscriber(
        provider_settings(), transport=stub_transport(
            lambda request: httpx.Response(200, json={})))
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(b"not audio")
    assert exc_info.value.code == "E_UPLOAD"
    stereo = _wav()
    bad = stereo[:22] + struct.pack("<H", 2) + stereo[24:]
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(bad)
    assert exc_info.value.code == "E_UPLOAD"


def test_voice_bad_turns_is_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": "x", "turns": [
            {"turnId": "t", "startMs": 9, "endMs": 1, "transcript": "x"}]})

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(_wav())
    assert exc_info.value.code == "E_SCHEMA"


def test_voice_empty_transcript_valid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": "", "turns": []})

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    transcript = transcriber.transcribe(_wav())
    assert transcript.text == ""
    assert "empty transcript returned" in transcript.warnings


@pytest.mark.parametrize(("status", "category", "code"), [
    (401, "auth", "E_API_UNAVAILABLE"),
    (429, "rate_limit", "E_RATE_LIMIT"),
    (500, "server", "E_API_UNAVAILABLE"),
])
def test_voice_http_errors_mapped(status, category, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=error_envelope("nope"))

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(_wav())
    assert exc_info.value.code == code
    assert exc_info.value.details == [{"code": category}]


def test_voice_malformed_body_is_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    transcriber = MetaVoiceTranscriber(provider_settings(),
                                       transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        transcriber.transcribe(_wav())
    assert exc_info.value.code == "E_SCHEMA"


# --- SAM -----------------------------------------------------------------


def test_sam_count_and_boxes():
    lane = f"<0f>1{BOX8}{MASK},2{BOX8}{MASK}"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["model"] == "sam-3.1"
        assert body["stream"] is True
        assert body["metadata"] == {"mask_encoding": "one_bit"}
        assert body["input"][0]["content"][0]["text"] == "flour bag"
        assert body["input"][0]["content"][1]["type"] == "input_image"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed(lane, model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    evidence = segmenter.count(_png(), catalogue_item_id="flour",
                               catalogue_label="flour bag")
    assert evidence.count == 2
    assert evidence.frames_observed == 1
    assert len(evidence.boxes) == 2
    assert evidence.boxes[0]["object_id"] == "1"
    assert evidence.boxes[0]["mask_area"] == 1
    assert evidence.boxes[0]["mask_pixels"] == 0
    assert evidence.model_id == "sam-3.1"
    assert evidence.request_id == "resp_1"


def test_sam_undecodable_mask_is_schema_error():
    lane = f"<0f>1{BOX8}{MASK_BAD}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed(lane, model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f",
                        catalogue_label="flour")
    assert exc_info.value.code == "E_SCHEMA"


def test_sam_tracking_dedupes_across_frames():
    lane = f"<0f>1{BOX8}{MASK}\n<3f>1{BOX8}{MASK}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed(lane, model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    evidence = segmenter.count(_png(), catalogue_item_id="flour",
                               catalogue_label="flour bag")
    assert evidence.count == 1  # same track, not per-frame sum
    assert evidence.frames_observed == 2


def test_sam_zero_matches_valid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed("", model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    evidence = segmenter.count(_png(), catalogue_item_id="flour",
                               catalogue_label="flour bag")
    assert evidence.count == 0
    assert evidence.frames_observed == 0


@pytest.mark.parametrize(("status", "category", "code"), [
    (401, "auth", "E_API_UNAVAILABLE"),
    (429, "rate_limit", "E_RATE_LIMIT"),
    (500, "server", "E_API_UNAVAILABLE"),
])
def test_sam_http_errors_mapped(status, category, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=error_envelope("nope"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f",
                        catalogue_label="flour")
    assert exc_info.value.code == code
    assert exc_info.value.details == [{"code": category}]


def test_sam_mid_stream_error_mapped():
    body = ("event: error\n"
            f"data: {json.dumps({'code': 'content_policy_violation'})}\n\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f",
                        catalogue_label="flour")
    # Stream refusal surfaces as a transport-level failure (retryable
    # ERROR state), never as fabricated evidence.
    assert exc_info.value.code == "E_API_UNAVAILABLE"


def test_sam_dim_mismatch_and_bad_grammar():
    bad_box = "<|box;x1=0;y1=0;x2=99;y2=99;w=640;h=480|>"

    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed(f"<0f>1{bad_box}{MASK}",
                                                     model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(mismatch))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f", catalogue_label="flour")
    assert exc_info.value.code == "E_SCHEMA"

    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed("definitely not a lane",
                                                     model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(garbage))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f", catalogue_label="flour")
    assert exc_info.value.code == "E_SCHEMA"


def test_sam_count_range_enforced():
    lane = f"<0f>1{BOX8}{MASK}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed(lane, model="sam-3.1"))

    settings = provider_settings(sam_count_min=5, sam_count_max=9)
    segmenter = MetaSamSegmenter(settings, transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        segmenter.count(_png(), catalogue_item_id="f", catalogue_label="flour")
    assert "outside configured range" in exc_info.value.message


def test_sam_concept_prompt_single_noun_phrase():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse_completed("", model="sam-3.1"))

    segmenter = MetaSamSegmenter(provider_settings(),
                                 transport=stub_transport(handler))
    segmenter.count(_png(), catalogue_item_id="f",
                    catalogue_label="flour bag, sugar; salt")
    prompt = seen["body"]["input"][0]["content"][0]["text"]
    assert prompt == "flour bag"


# --- Refusal routing -----------------------------------------------------


def test_spark_refusal_is_schema_error():
    body = {"id": "resp_9", "status": "failed", "model": "muse-spark-1.3",
            "output": [],
            "error": {"code": "content_policy_violation", "message": "no"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    reader = SparkReader(provider_settings(),
                         transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        reader.read(_pdf())
    # Deterministic for this content: R8 DENY, not a retryable error.
    assert exc_info.value.code == "E_SCHEMA"


def test_baseten_refusal_is_schema_error():
    body = {"id": "chatcmpl_9", "model": "meta-models/muse-spark-open-1026",
            "choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": None,
                                     "refusal": "I cannot help"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0,
                      "total_tokens": 1}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    reader = BasetenSparkReader(provider_settings(),
                                transport=stub_transport(handler))
    with pytest.raises(AppError) as exc_info:
        reader.read(_png())
    assert exc_info.value.code == "E_SCHEMA"

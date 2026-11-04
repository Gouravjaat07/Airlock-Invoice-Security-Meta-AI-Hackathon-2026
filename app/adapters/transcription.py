"""Mock ASR adapter: transcription of voice notes.

Transcripts are untrusted evidence (T2): they may contain malicious
instructions or wrong values. Voice never authenticates and never reaches
the planner as raw text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.evaluation.fixtures import safe_artifact_path, scenario_roots

ADAPTER_ID = "mock-asr"
ADAPTER_VERSION = "2.1.0"
MAX_TRANSCRIPT_CHARS = 4000


@dataclass(frozen=True)
class Transcript:
    text: str
    artifact_sha256: str
    # Live-provider provenance (empty/None for the mock adapter).
    turns: tuple[dict, ...] = ()
    request_id: str | None = None
    model_id: str | None = None
    usage: dict | None = None
    warnings: tuple[str, ...] = ()


class MockAsr:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings):
        self.settings = settings

    def scenario_for_voice(self, voice_bytes: bytes) -> dict | None:
        if not self.settings.fixture_reader_enabled:
            return None
        digest = hashlib.sha256(voice_bytes).hexdigest()
        for scenarios, root, kind in scenario_roots(self.settings):
            if not scenarios.is_dir():
                continue
            for path in sorted(scenarios.glob("*.json")):
                try:
                    spec = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(spec, dict) or not spec.get("voice_artifact"):
                    continue
                artifact_path = safe_artifact_path(
                    root, str(spec["voice_artifact"]))
                if artifact_path is None:
                    continue
                try:
                    file_digest = hashlib.sha256(
                        artifact_path.read_bytes()).hexdigest()
                except OSError:
                    continue
                if file_digest == digest:
                    spec["_fixture_kind"] = kind
                    return spec
        return None

    def transcribe(self, voice_bytes: bytes) -> Transcript:
        if not self.settings.fixture_reader_enabled:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           "Transcription unavailable: mock adapter is dev/test/demo only")
        digest = hashlib.sha256(voice_bytes).hexdigest()
        spec = self.scenario_for_voice(voice_bytes)
        if spec is not None:
            transcript = spec.get("transcript")
            if isinstance(transcript, dict) and transcript.get("error"):
                raise AppError(ErrorCode.API_UNAVAILABLE,
                               f"ASR error: {transcript['error']}")
            if isinstance(transcript, str):
                return Transcript(text=transcript[:MAX_TRANSCRIPT_CHARS],
                                  artifact_sha256=digest)
        raise AppError(ErrorCode.API_UNAVAILABLE,
                       "Voice artifact is not a registered synthetic fixture")

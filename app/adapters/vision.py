"""Mock SAM adapter: visible-instance counts for a catalogue label.

Scope is deliberately narrow: count instances of a trusted-registry label
in delivery evidence. The label always comes from the vendor registry,
never from invoice free text. Counts are untrusted evidence (T2) used
only for R7 tolerance comparison.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.evaluation.fixtures import safe_artifact_path, scenario_roots

ADAPTER_ID = "mock-sam"
ADAPTER_VERSION = "2.1.0"


@dataclass(frozen=True)
class SamEvidence:
    count: int
    catalogue_item_id: str
    catalogue_label: str
    artifact_sha256: str
    # Live-provider provenance (defaults for the mock adapter).
    frames_observed: int = 1
    boxes: tuple[dict, ...] = ()
    request_id: str | None = None
    model_id: str | None = None
    usage: dict | None = None
    warnings: tuple[str, ...] = ()


class MockSam:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings):
        self.settings = settings

    def scenario_for_delivery(self, delivery_bytes: bytes) -> dict | None:
        if not self.settings.fixture_reader_enabled:
            return None
        digest = hashlib.sha256(delivery_bytes).hexdigest()
        for scenarios, root, kind in scenario_roots(self.settings):
            if not scenarios.is_dir():
                continue
            for path in sorted(scenarios.glob("*.json")):
                try:
                    spec = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(spec, dict) or not spec.get("delivery_artifact"):
                    continue
                artifact_path = safe_artifact_path(
                    root, str(spec["delivery_artifact"]))
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

    def count(self, delivery_bytes: bytes, *, catalogue_item_id: str,
              catalogue_label: str) -> SamEvidence:
        if not self.settings.fixture_reader_enabled:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           "SAM evidence unavailable: mock adapter is dev/test/demo only")
        spec = self.scenario_for_delivery(delivery_bytes)
        if spec is None:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           "Delivery artifact is not a registered synthetic fixture")
        sam = spec.get("sam")
        if isinstance(sam, dict) and sam.get("error"):
            raise AppError(ErrorCode.API_UNAVAILABLE, f"SAM verifier error: {sam['error']}")
        if not isinstance(sam, dict) or not isinstance(sam.get("count"), int):
            raise AppError(ErrorCode.API_UNAVAILABLE, "SAM fixture has no count")
        count = int(sam["count"])
        if count < self.settings.sam_count_min or count > self.settings.sam_count_max:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           f"SAM count {count} outside configured range")
        return SamEvidence(count=count, catalogue_item_id=catalogue_item_id,
                           catalogue_label=catalogue_label,
                           artifact_sha256=hashlib.sha256(delivery_bytes).hexdigest())

    def evidence_record(self, evidence: SamEvidence) -> dict:
        return {
            "adapter": self.adapter_id,
            "adapter_version": self.adapter_version,
            "count": evidence.count,
            "catalogue_item_id": evidence.catalogue_item_id,
            "catalogue_label": evidence.catalogue_label,
            "artifact_sha256": evidence.artifact_sha256,
            "observed_at": SYSTEM_CLOCK.now().isoformat(),
            "limitations": "Count only; not authenticity, quality, ownership, or hidden goods.",
        }

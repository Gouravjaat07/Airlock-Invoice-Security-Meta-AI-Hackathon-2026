"""Reader adapters: protocol + synthetic fixture reader.

The reader receives only the artifact reference and returns structured
extraction (tainted T2). It has no registry/policy/payment access.

The fixture reader serves ONLY artifacts whose SHA-256 is explicitly
registered in the enabled fixtures directory (dev/test/demo). Any other
artifact yields E_READER_UNAVAILABLE. Live model readers
(spark/spark-open/glimmer) are selected via AIRLOCK_READER_PROVIDER;
see app/providers/registry.py.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.evaluation.fixtures import safe_artifact_path, scenario_roots

ADAPTER_ID = "fixture-reader"
ADAPTER_VERSION = "2.1.0"


@dataclass(frozen=True)
class ReaderResult:
    payload: dict[str, Any]
    artifact_sha256: str
    scenario: str
    # Live-provider provenance (None for the fixture reader).
    request_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    usage: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    # Grounded evidence page anchors (field name -> 1-based page).
    evidence_pages: dict[str, int] | None = None


class Reader(Protocol):
    adapter_id: str
    adapter_version: str

    def read(self, artifact_bytes: bytes) -> ReaderResult:
        ...


class FixtureReader:
    """Deterministic fixture reader for synthetic demonstration."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings):
        self.settings = settings
        self._index: dict[str, dict[str, Any]] | None = None

    def _build_index(self) -> dict[str, dict[str, Any]]:
        if self._index is not None:
            return self._index
        index: dict[str, dict[str, Any]] = {}
        for scenarios, root, kind in scenario_roots(self.settings):
            if not scenarios.is_dir():
                continue
            for path in sorted(scenarios.glob("*.json")):
                try:
                    spec = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(spec, dict):
                    continue
                invoice_rel = spec.get("invoice_artifact")
                if not invoice_rel:
                    continue
                artifact_path = safe_artifact_path(root, str(invoice_rel))
                if artifact_path is None:
                    continue
                try:
                    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                except OSError:
                    continue
                if digest in index and kind == "custom":
                    # Custom fixtures add new content hashes but never
                    # shadow canonical ones (canonical last-wins order
                    # within its own directory is preserved).
                    continue
                spec["_scenario_file"] = path.name
                spec["_fixture_kind"] = kind
                index[digest] = spec
        self._index = index
        return index

    def read(self, artifact_bytes: bytes) -> ReaderResult:
        if not self.settings.fixture_reader_enabled:
            raise AppError(ErrorCode.READER_UNAVAILABLE,
                           "No reader available: fixture reader is disabled; "
                           "enable it only in dev/test/demo, or select a live "
                           "reader via AIRLOCK_READER_PROVIDER")
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        spec = self._build_index().get(digest)
        if spec is None:
            raise AppError(ErrorCode.READER_UNAVAILABLE,
                           "Artifact is not a registered synthetic fixture "
                           f"(sha256 {digest[:16]}...). Upload registered fixture "
                           "bytes, or register this file with "
                           "`python -m app.cli fixtures register` (dev/test only)")
        if spec.get("reader_error"):
            err = spec["reader_error"]
            code = str(err.get("code", ErrorCode.READER_TIMEOUT))
            raise AppError(code, str(err.get("message", "Fixture reader error")))
        extraction = spec.get("extraction")
        if not isinstance(extraction, dict):
            # Dedicated failure fixtures exercise malformed-output handling.
            raise AppError(ErrorCode.SCHEMA,
                           "Fixture reader returned malformed output",
                           details=[{"code": "malformed-fixture"}])
        return ReaderResult(payload=extraction, artifact_sha256=digest,
                            scenario=str(spec.get("name", spec.get("_scenario_file", "?"))))

    def scenario_for_invoice(self, artifact_bytes: bytes) -> dict[str, Any] | None:
        if not self.settings.fixture_reader_enabled:
            return None
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        return self._build_index().get(digest)

"""Dev/test-only custom fixture registration (never production).

A custom fixture binds exact file bytes (SHA-256) to an owner-authored
extraction payload so the fixture reader can process a synthetic file
uploaded through the real UI. Registration is explicit, local, and
content-addressed:

- refused when AIRLOCK_ENV=production (no override flag exists);
- the extraction payload must pass the strict production schema;
- the artifact bytes must pass the same intake validation as uploads;
- custom fixtures live in a separate directory and can never shadow
  canonical fixtures or enter the offline evaluation gates.

Uploads never self-register: only bytes whose SHA-256 exactly matches a
registered fixture resolve. Filenames, form fields, PDF text, and model
output confer no trust.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.evaluation.fixtures import (
    ATTACK_RE,
    NAME_RE,
    VERDICTS,
    list_scenarios,
)

INVOICE_MEDIA = frozenset({"application/pdf", "image/png", "image/jpeg"})
DELIVERY_MEDIA = frozenset({"image/png", "image/jpeg", "video/mp4"})
VOICE_MEDIA = frozenset({"audio/wav"})
MAX_EXTRACTION_JSON_BYTES = 1024 * 1024


def _read_capped(path: Path, cap: int, label: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AppError(ErrorCode.SCHEMA,
                       f"Cannot read {label}: {path}") from exc
    if len(data) > cap:
        raise AppError(ErrorCode.UPLOAD,
                       f"{label} exceeds the {cap}-byte limit")
    return data


def _check_artifact(data: bytes, filename: str, settings: Settings, *,
                    label: str, allowed: frozenset[str]) -> tuple[str, str]:
    from app.storage.artifacts import (
        sniff_media,
        validate_resource_bounds,
    )
    if len(data) > settings.max_upload_bytes:
        raise AppError(ErrorCode.UPLOAD,
                       f"{label} exceeds the upload size limit")
    media_type, extension = sniff_media(data, filename)
    if media_type not in allowed:
        raise AppError(ErrorCode.UPLOAD,
                       f"{label} has media type {media_type}; "
                       f"expected one of {sorted(allowed)}")
    validate_resource_bounds(data, media_type, settings)
    return media_type, extension


def _resolve_target_dir(settings: Settings,
                        custom_dir: str | Path | None) -> Path:
    raw = str(custom_dir) if custom_dir else settings.custom_fixtures_dir
    if not raw:
        raise AppError(ErrorCode.SCHEMA,
                       "No custom fixtures directory: set "
                       "AIRLOCK_CUSTOM_FIXTURES_DIR or pass --dir")
    target = Path(raw)
    if not target.is_absolute():
        target = Path.cwd() / target
    return target


def register(settings: Settings, *, name: str, invoice: str | Path,
             extraction: str | Path, expected_verdict: str,
             attack_type: str | None = None, variant: str = "custom",
             notes: str = "", delivery: str | Path | None = None,
             voice: str | Path | None = None, transcript: str | None = None,
             sam_count: int | None = None,
             custom_dir: str | Path | None = None,
             force: bool = False) -> dict[str, Any]:
    """Register a synthetic fixture. Returns the registration summary."""
    if settings.environment == "production":
        raise AppError(ErrorCode.AUTH,
                       "Fixture registration is disabled in production",
                       status=403)
    if not settings.fixture_reader_enabled:
        raise AppError(ErrorCode.READER_UNAVAILABLE,
                       "Enable the fixture reader first "
                       "(AIRLOCK_FIXTURE_READER=1, dev/test only)")
    if not NAME_RE.match(name):
        raise AppError(ErrorCode.SCHEMA, f"Invalid scenario name: {name}")
    if attack_type is not None and not ATTACK_RE.match(str(attack_type)):
        raise AppError(ErrorCode.SCHEMA,
                       "attack_type must use the v2 vocabulary (A01-A16)")
    if expected_verdict not in VERDICTS:
        raise AppError(ErrorCode.SCHEMA,
                       "expected_verdict must be ALLOW_PROPOSAL, ESCALATE, "
                       f"or DENY (got {expected_verdict!r})")
    if not NAME_RE.match(variant):
        raise AppError(ErrorCode.SCHEMA, f"Invalid variant: {variant}")
    if name in list_scenarios(settings):
        raise AppError(ErrorCode.DUPLICATE,
                       f"Custom fixture {name!r} would shadow a canonical "
                       "scenario; choose another name")
    if voice is not None and transcript is None:
        raise AppError(ErrorCode.SCHEMA,
                       "Registering a voice artifact requires --transcript")
    if voice is None and transcript is not None:
        raise AppError(ErrorCode.SCHEMA,
                       "--transcript requires a --voice artifact")
    if delivery is not None and sam_count is None:
        raise AppError(ErrorCode.SCHEMA,
                       "Registering a delivery artifact requires --sam-count")
    if delivery is None and sam_count is not None:
        raise AppError(ErrorCode.SCHEMA,
                       "--sam-count requires a --delivery artifact")
    if sam_count is not None and not (
            settings.sam_count_min <= sam_count <= settings.sam_count_max):
        raise AppError(ErrorCode.SCHEMA,
                       f"--sam-count {sam_count} is outside the configured "
                       "SAM range")

    invoice_bytes = _read_capped(Path(invoice), settings.max_upload_bytes,
                                 "invoice file")
    _media, extension = _check_artifact(
        invoice_bytes, Path(invoice).name, settings, label="invoice file",
        allowed=INVOICE_MEDIA)
    raw_extraction = _read_capped(Path(extraction),
                                  MAX_EXTRACTION_JSON_BYTES,
                                  "extraction JSON")
    try:
        payload = json.loads(raw_extraction.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AppError(ErrorCode.SCHEMA,
                       f"Extraction file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.SCHEMA,
                       "Extraction file must contain a JSON object")

    from app.pipeline.validate import validate_extraction
    validate_extraction(payload)

    extras: dict[str, Any] = {}
    if delivery is not None:
        delivery_bytes = _read_capped(Path(delivery),
                                      settings.max_upload_bytes,
                                      "delivery file")
        _media, delivery_ext = _check_artifact(
            delivery_bytes, Path(delivery).name, settings,
            label="delivery file", allowed=DELIVERY_MEDIA)
        extras["delivery"] = (delivery_bytes, delivery_ext)
    if voice is not None:
        voice_bytes = _read_capped(Path(voice), settings.max_upload_bytes,
                                   "voice file")
        _media, voice_ext = _check_artifact(
            voice_bytes, Path(voice).name, settings, label="voice file",
            allowed=VOICE_MEDIA)
        extras["voice"] = (voice_bytes, voice_ext)

    target = _resolve_target_dir(settings, custom_dir)
    scenarios_dir = target / "scenarios"
    scenario_path = scenarios_dir / f"{name}.json"
    invoice_rel = f"invoices/{name}{extension}"
    invoice_path = target / invoice_rel
    if scenario_path.exists() and not force:
        raise AppError(ErrorCode.DUPLICATE,
                       f"Custom fixture {name!r} already exists "
                       "(pass --force to overwrite)")
    if invoice_path.exists() and not force:
        raise AppError(ErrorCode.DUPLICATE,
                       f"Custom artifact {invoice_rel} already exists "
                       "(pass --force to overwrite)")

    digest = hashlib.sha256(invoice_bytes).hexdigest()
    spec: dict[str, Any] = {
        "name": name,
        "variant": variant,
        "attack_type": attack_type,
        "expected_verdict": expected_verdict,
        "invoice_artifact": invoice_rel,
        "delivery_artifact": None,
        "voice_artifact": None,
        "extraction": payload,
        "sam": None,
        "transcript": None,
        "reader_error": None,
        "notes": notes,
        "registration": {
            "kind": "custom",
            "tool": "app.cli fixtures register",
            "registered_at": SYSTEM_CLOCK.now().isoformat(),
            "source_sha256": digest,
        },
    }
    try:
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        invoice_path.parent.mkdir(parents=True, exist_ok=True)
        invoice_path.write_bytes(invoice_bytes)
        if "delivery" in extras:
            delivery_bytes, delivery_ext = extras["delivery"]
            delivery_rel = f"delivery/{name}{delivery_ext}"
            (target / delivery_rel).parent.mkdir(parents=True, exist_ok=True)
            (target / delivery_rel).write_bytes(delivery_bytes)
            spec["delivery_artifact"] = delivery_rel
            spec["sam"] = {"count": sam_count}
            spec["registration"]["delivery_sha256"] = hashlib.sha256(
                delivery_bytes).hexdigest()
        if "voice" in extras:
            voice_bytes, voice_ext = extras["voice"]
            voice_rel = f"voice/{name}{voice_ext}"
            (target / voice_rel).parent.mkdir(parents=True, exist_ok=True)
            (target / voice_rel).write_bytes(voice_bytes)
            spec["voice_artifact"] = voice_rel
            spec["transcript"] = transcript
            spec["registration"]["voice_sha256"] = hashlib.sha256(
                voice_bytes).hexdigest()
        scenario_path.write_text(json.dumps(spec, indent=2, sort_keys=True)
                                 + "\n", encoding="utf-8")
    except OSError as exc:
        raise AppError(ErrorCode.STORAGE,
                       f"Cannot write custom fixture: {exc}") from exc

    backend_sees_it = False
    configured = settings.custom_fixtures_dir
    if configured:
        configured_path = Path(str(configured))
        if not configured_path.is_absolute():
            configured_path = Path.cwd() / configured_path
        try:
            backend_sees_it = configured_path.resolve() == target.resolve()
        except OSError:
            backend_sees_it = False
    return {
        "name": name,
        "scenario_path": str(scenario_path),
        "invoice_artifact": invoice_rel,
        "sha256": digest,
        "expected_verdict": expected_verdict,
        "custom_dir": str(target),
        "backend_configured": backend_sees_it,
        "hint": ("Upload the exact registered bytes through the UI and "
                 "process the case."
                 if backend_sees_it else
                 "Set AIRLOCK_CUSTOM_FIXTURES_DIR to the custom dir for "
                 "the backend session (restart it if already running), "
                 "then upload the exact registered bytes."),
    }


def list_fixtures(settings: Settings) -> dict[str, Any]:
    """List canonical scenarios plus registered custom fixtures."""
    from app.evaluation.fixtures import safe_artifact_path, scenario_roots
    entries = []
    for scenarios_dir, root, kind in scenario_roots(settings):
        if not scenarios_dir.is_dir():
            continue
        for path in sorted(scenarios_dir.glob("*.json")):
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(spec, dict):
                continue
            invoice_rel = spec.get("invoice_artifact")
            digest = None
            if invoice_rel:
                artifact_path = safe_artifact_path(root, str(invoice_rel))
                if artifact_path is not None:
                    try:
                        digest = hashlib.sha256(
                            artifact_path.read_bytes()).hexdigest()
                    except OSError:
                        digest = None
            entries.append({
                "name": spec.get("name", path.stem),
                "kind": kind,
                "scenario": path.name,
                "expected_verdict": spec.get("expected_verdict"),
                "invoice_artifact": invoice_rel,
                "sha256": digest,
            })
    entries.sort(key=lambda item: (item["kind"], str(item["name"])))
    return {
        "canonical": sum(1 for item in entries if item["kind"] == "canonical"),
        "custom": sum(1 for item in entries if item["kind"] == "custom"),
        "custom_dir": settings.custom_fixtures_dir,
        "fixtures": entries,
    }


def verify_bytes(settings: Settings, path: str | Path) -> dict[str, Any]:
    """Check whether a file's bytes resolve to a registered fixture."""
    from app.adapters.readers import FixtureReader
    from app.adapters.transcription import MockAsr
    from app.adapters.vision import MockSam
    data = _read_capped(Path(path), settings.max_upload_bytes, "file")
    digest = hashlib.sha256(data).hexdigest()
    if not settings.fixture_reader_enabled:
        return {"registered": False, "sha256": digest,
                "reason": "fixture reader is not enabled"}
    spec = FixtureReader(settings).scenario_for_invoice(data)
    if spec is not None:
        return {"registered": True, "role": "invoice", "sha256": digest,
                "scenario": spec.get("name"),
                "kind": spec.get("_fixture_kind", "canonical"),
                "expected_verdict": spec.get("expected_verdict")}
    voice_spec = MockAsr(settings).scenario_for_voice(data)
    if voice_spec is not None:
        return {"registered": True, "role": "voice", "sha256": digest,
                "scenario": voice_spec.get("name"),
                "kind": voice_spec.get("_fixture_kind", "canonical")}
    delivery_spec = MockSam(settings).scenario_for_delivery(data)
    if delivery_spec is not None:
        return {"registered": True, "role": "delivery", "sha256": digest,
                "scenario": delivery_spec.get("name"),
                "kind": delivery_spec.get("_fixture_kind", "canonical")}
    return {"registered": False, "sha256": digest,
            "reason": "no scenario references these bytes"}

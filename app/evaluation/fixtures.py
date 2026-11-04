"""Scenario fixture loading for synthetic evaluation.

Scenario files (`fixtures/scenarios/<name>.json`) use the Phase 1
manifest v2 vocabulary: `attack_type` (A01-A16, canonical) and
`expected_verdict` (ALLOW_PROPOSAL/ESCALATE/DENY). No competing schema.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import Settings
from app.core.errors import AppError, ErrorCode

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
ATTACK_RE = re.compile(r"^A(0[1-9]|1[0-6])$")
VERDICTS = frozenset({"ALLOW_PROPOSAL", "ESCALATE", "DENY"})


def scenario_path(settings: Settings, name: str) -> Path:
    if not NAME_RE.match(name):
        raise AppError(ErrorCode.SCHEMA, f"Invalid scenario name: {name}")
    path = Path(settings.fixtures_dir) / "scenarios" / f"{name}.json"
    if not path.is_file():
        raise AppError(ErrorCode.SCHEMA, f"Unknown scenario: {name}")
    return path


def load_scenario(settings: Settings, name: str) -> dict:
    path = scenario_path(settings, name)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError(ErrorCode.SCHEMA, f"Cannot read scenario {name}: {exc}") from exc
    if not isinstance(spec, dict):
        raise AppError(ErrorCode.SCHEMA, f"Scenario {name} must be an object")
    attack_type = spec.get("attack_type")
    if attack_type is not None and not ATTACK_RE.match(str(attack_type)):
        raise AppError(ErrorCode.SCHEMA,
                       f"Scenario {name} has invalid attack_type (v2 A01-A16)")
    if spec.get("attack_id") is not None:
        raise AppError(ErrorCode.SCHEMA,
                       f"Scenario {name} uses retired v1 field attack_id")
    if spec.get("expected_verdict") not in VERDICTS:
        raise AppError(ErrorCode.SCHEMA,
                       f"Scenario {name} has invalid expected_verdict")
    return spec


def list_scenarios(settings: Settings) -> list[str]:
    root = Path(settings.fixtures_dir) / "scenarios"
    if not root.is_dir():
        return []
    return sorted(path.stem for path in root.glob("*.json")
                  if NAME_RE.match(path.stem))


def scenario_roots(settings: Settings) -> list[tuple[Path, Path, str]]:
    """Scenario directories scanned by the fixture/mock adapters.

    Returns (scenarios_dir, fixtures_root, kind) with the canonical
    fixtures first. A configured custom directory is appended: it can
    only add new content hashes, never shadow canonical fixtures.
    Offline evaluation gates do not use this helper; they stay pinned
    to the canonical directory via list_scenarios/load_scenario.
    """
    roots = [(Path(settings.fixtures_dir), "canonical")]
    custom = getattr(settings, "custom_fixtures_dir", None)
    if custom:
        roots.append((Path(custom), "custom"))
    return [(root / "scenarios", root, kind) for root, kind in roots]


def safe_artifact_path(root: Path, rel_path: str) -> Path | None:
    """Confine a scenario's artifact reference to its fixtures root.

    Returns None for absolute paths, traversal attempts, or missing
    files; callers skip such specs instead of failing the whole index.
    """
    try:
        base = root.resolve()
        candidate = (root / rel_path).resolve()
    except (OSError, ValueError):
        return None
    if candidate == base or base not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def read_artifact_bytes(settings: Settings, rel_path: str) -> bytes:
    """Read a fixture artifact, confined to the fixtures directory."""
    root = Path(settings.fixtures_dir).resolve()
    candidate = (root / rel_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise AppError(ErrorCode.SCHEMA, "Fixture path escapes fixtures directory")
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise AppError(ErrorCode.SCHEMA, f"Cannot read fixture {rel_path}") from exc

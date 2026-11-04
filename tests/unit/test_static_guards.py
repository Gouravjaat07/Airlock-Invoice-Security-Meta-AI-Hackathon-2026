"""Static security guards: SQL parameterization + parser fail-open pins.

All app SQL must be parameterized. Two constant-only interpolations in
`app/storage/database.py` are explicitly allowlisted (PRAGMA timeout
from a module constant; migration version row from an int-parsed
filename stem + ISO timestamp). Anything new fails loudly here.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.storage.artifacts import (
    jpeg_dimensions,
    mp4_duration_seconds,
    wav_duration_seconds,
)

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"

_DYNAMIC_SQL_RE = re.compile(
    r"execute\s*\(\s*f[\"']|executescript\s*\(\s*f[\"']|"
    r"execute\s*\([^)]*%\s|SELECT.{0,80}\.format\("
)

ALLOWLISTED_SUBSTRINGS = (
    "PRAGMA busy_timeout=",  # module-constant int only
    "INSERT INTO schema_migrations (version, applied_at) VALUES (",  # int + ISO ts
)


def test_no_unallowlisted_dynamic_sql():
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if _DYNAMIC_SQL_RE.search(line) and not any(
                    safe in line for safe in ALLOWLISTED_SUBSTRINGS):
                offenders.append(f"{path.name}:{lineno}: {line.strip()[:100]}")
    assert offenders == []


def test_allowlist_still_covers_known_sites():
    """The allowlist must match real lines (no dead exceptions)."""
    text = (APP_ROOT / "storage" / "database.py").read_text(encoding="utf-8")
    for safe in ALLOWLISTED_SUBSTRINGS:
        assert safe in text


def test_corrupt_dims_fail_open_to_none():
    """Documented fail-open: unparseable dims yield None (caps still bound)."""
    assert jpeg_dimensions(b"not-a-jpeg" * 40) is None
    assert jpeg_dimensions(b"") is None
    assert mp4_duration_seconds(b"not-an-mp4" * 40) is None
    assert mp4_duration_seconds(b"") is None
    assert wav_duration_seconds(b"not-a-wav" * 40) is None
    assert wav_duration_seconds(b"") is None

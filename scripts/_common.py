"""Shared Phase 1 helpers: version, atomic JSON writes, provenance.

Small on purpose: every Phase 1 report writer uses these so evidence files
are never left truncated and every report carries the same provenance
envelope (tool, version, command, timestamp, commit). No network, no
secrets: argv values are commands/paths only — secret-bearing arguments
must never be introduced to these CLIs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

# Must match [project] version in pyproject.toml (parity test:
# tests/test_orchestrator_cli.py::test_tool_version_matches_pyproject).
TOOL_VERSION = "0.1.0"

GIT_TIMEOUT_S = 10


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Nearest directory at or above `start` (default: cwd) holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def default_audit_root() -> Path:
    """Project root for audit entry points: script location first, cwd second.

    The tools audit the Airlock checkout they ship in, no matter where the
    user invokes them from. Falls back to cwd discovery when the scripts
    are not inside a project checkout (e.g. copied elsewhere).
    """
    script_root = Path(__file__).resolve().parent.parent
    if (script_root / "pyproject.toml").is_file():
        return script_root
    return find_project_root() or Path.cwd()


def atomic_write_json(path: str | Path, obj: dict) -> str:
    """Write JSON atomically: temp file in the same directory + fsync + replace.

    A crash mid-write leaves the old file intact (or no file), never a
    truncated one. Raises OSError on failure; callers convert to exit 1.
    """
    target = Path(path)
    parent = target.parent
    if str(parent) not in (".", ""):
        parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{target.name}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return str(target)


def git_commit(root: Optional[Path] = None) -> Optional[str]:
    """Best-effort HEAD sha; None when git is unavailable, unsafe, or unborn.

    Never mutates git configuration (no safe.directory injection): in a
    sandbox with a directory-ownership mismatch this honestly returns None.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S,
            cwd=str(root) if root else None)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    sha = completed.stdout.strip().splitlines()
    return sha[0].strip() if sha and sha[0].strip() else None


def provenance_envelope(tool: str, argv: Optional[Sequence[str]] = None,
                        root: Optional[Path] = None,
                        extra: Optional[dict] = None) -> dict:
    """Provenance block embedded in every Phase 1 JSON report."""
    envelope = {
        "tool": tool,
        "tool_version": TOOL_VERSION,
        "argv": list(argv) if argv is not None else sys.argv[1:],
        "timestamp_utc": utc_now_iso(),
        "git_commit": git_commit(root),
        "python": sys.version.split()[0],
    }
    if extra:
        envelope.update(extra)
    return envelope

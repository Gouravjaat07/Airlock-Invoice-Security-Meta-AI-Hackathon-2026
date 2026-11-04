"""Secret-hygiene check for the Airlock repository (Phase 1).

Scans ONLY files under the project root:
  * tracked source files (or a directory walk when git is unavailable), and
  * pending git changes (staged + unstaged diffs).

Limitation: pattern scanning catches common accidents; it is NOT a guarantee
that every secret has been detected. Absence of findings is not proof of
absence of secrets.

Findings never include secret values — only file, line, and pattern name.
Exit codes: 0 when clean; 1 when findings or ignore-rule problems exist.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    atomic_write_json, default_audit_root,
    find_project_root as _common_find_root, provenance_envelope,
)

COMMAND_TIMEOUT_S = 15

# (pattern_name, compiled_regex). Assignment patterns match only VALUE-looking
# right-hand sides (quoted literals, bare tokens) and deliberately ignore code
# shapes such as `api_key: str`, `x = None`, `x = ""`, or `x = func(...)`.
# Pattern definitions do not match themselves; the scanner additionally skips
# its own file (see SELF_SKIP).
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("generic-api-key-assignment", re.compile(
        r"(?i)\bapi[_-]?key\b\s*=\s*(?!\s*(?:None\b|['\"]\s*['\"]|[A-Za-z_][\w.]*\s*\(|\())\S+")),
    ("generic-api-key-json", re.compile(r"(?i)\"api[_-]?key\"\s*:\s*\"\S+")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}=*")),
    ("sk-prefixed-token", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key-block", re.compile(r"-----[A-Z ]*PRIVATE KEY-----")),
    ("connection-string-with-password", re.compile(r"(?i)://[^/\s:]+:[^/\s@]+@")),
    ("pin-assignment", re.compile(r"(?i)\bairlock_pin\b\s*[:=]\s*['\"]?\d{4,8}['\"]?")),
    ("session-secret-assignment", re.compile(
        r"(?i)\bsession[_-]?secret\b\s*=\s*['\"][^'\"\s]{3,}['\"]")),
)

# The scanner skips itself: its pattern table is source code, not credentials.
SELF_SKIP = {"scripts/check_secret_hygiene.py"}

SKIP_DIRS = {".git", ".hg", ".sl", ".eden", ".agents", ".muse", ".venv", "venv",
             "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             "node_modules", "results", "data", "htmlcov", "dist", "build"}
# Ephemeral local pytest temp dirs (pytest-of-<user>/pytest-N). These hold
# synthetic test artifacts by construction, never source; skipping them keeps
# the scan focused on real files. They are also git-ignored (see .gitignore).
SKIP_DIR_PREFIXES = ("pytest-of-",)
SKIP_SUFFIXES = {".pyc", ".pyo", ".gguf", ".safetensors", ".bin", ".pt", ".pth",
                 ".onnx", ".wav", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".pdf"}
SKIP_NAMES = {".gitkeep"}
MAX_FILE_BYTES = 1_000_000


def run_command(argv: list[str], cwd: Optional[Path] = None) -> tuple[bool, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=COMMAND_TIMEOUT_S, cwd=str(cwd) if cwd else None)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, ""
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return False, output
    return True, output


def find_project_root() -> Optional[Path]:
    return _common_find_root()


def scan_text(text: str) -> list[tuple[str, int]]:
    """Return [(pattern_name, line_number)] for each matching line (1-based)."""
    findings: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # Skip comments: docs legitimately name variables like MODEL_API_KEY.
            # Assignments with values in comments are still suspicious, so only
            # skip comments WITHOUT a value-looking token after = or :.
            if not re.search(r"[:=]\s*\S", stripped):
                continue
        for name, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((name, lineno))
                break  # one finding per line is enough
    return findings


def _design_skip_reason(path: Path, root: Path) -> Optional[str]:
    """Non-size skip reason, or None if no design rule skips this file."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return "outside-root"
    if rel in SELF_SKIP or rel in SKIP_NAMES or path.name in SKIP_NAMES:
        return "self-or-keep"
    parts = path.relative_to(root).parts
    if any(part in SKIP_DIRS for part in parts):
        return "skipped-dir"
    if any(part.startswith(prefix) for part in parts for prefix in SKIP_DIR_PREFIXES):
        return "skipped-dir"
    if path.suffix.lower() in SKIP_SUFFIXES:
        return "skipped-suffix"
    return None


def is_scannable(path: Path, root: Path) -> bool:
    if _design_skip_reason(path, root) is not None:
        return False
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def repo_toplevel(root: Path) -> Optional[Path]:
    """Repository top level containing `root`, or None when unavailable."""
    ok, output = run_command(["git", "rev-parse", "--show-toplevel"], cwd=root)
    if not ok or not output.strip():
        return None
    try:
        return Path(output.strip().splitlines()[0]).resolve()
    except (OSError, ValueError):
        return None


def _too_large_skip(path: Path) -> bool:
    try:
        return path.stat().st_size > MAX_FILE_BYTES
    except OSError:
        return False


def iter_candidate_files(root: Path) -> tuple[list[Path], list[dict]]:
    """Tracked + untracked (non-ignored) files via git at the repo top level;
    otherwise a bounded walk (git paths are only valid at the top level).

    Returns (files, skipped). By-design skips (suffix/dir/self/pytest-temp)
    stay silent; oversized files and escaping symlinks are logged in
    `skipped` as {"file", "reason"} — paths only, never values.
    """
    if repo_toplevel(root) != root.resolve():
        return _walk_files(root)
    ok, output = run_command(["git", "ls-files"], cwd=root)
    if ok:
        tracked = output.splitlines()
        untracked_ok, untracked_out = run_command(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=root)
        if untracked_ok:
            tracked += untracked_out.splitlines()
        files: list[Path] = []
        skipped: list[dict] = []
        for line in tracked:
            if not line.strip():
                continue
            candidate = (root / line.strip()).resolve()
            # resolve() may escape via symlink; containment re-checked below
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                skipped.append({"file": line.strip(), "reason": "outside-root-symlink"})
                continue
            if not candidate.is_file():
                continue
            if is_scannable(candidate, root.resolve()):
                files.append(candidate)
            elif (_design_skip_reason(candidate, root.resolve()) is None
                    and _too_large_skip(candidate)):
                skipped.append({"file": line.strip(), "reason": "too-large"})
        return sorted(set(files)), skipped
    return _walk_files(root)


def _walk_files(root: Path) -> tuple[list[Path], list[dict]]:
    walked: list[Path] = []
    skipped: list[dict] = []
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue  # outside the project root: never read
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError:
            skipped.append({"file": rel, "reason": "outside-root-symlink"})
            continue
        if is_scannable(path, root):
            walked.append(path)
        elif (_design_skip_reason(path, root) is None
                and _too_large_skip(path)):
            skipped.append({"file": rel, "reason": "too-large"})
    return walked, skipped


def scan_files(files: list[Path], root: Path) -> tuple[list[dict], list[dict]]:
    """Scan files; returns (findings, skipped). Findings carry no values."""
    findings: list[dict] = []
    skipped: list[dict] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.name
            skipped.append({"file": rel, "reason": "non-utf8-or-unreadable"})
            continue
        for pattern_name, lineno in scan_text(text):
            findings.append({"file": path.relative_to(root).as_posix(),
                             "line": lineno, "pattern": pattern_name,
                             "source": "working-tree"})
    return findings, skipped


def scan_pending_changes(root: Path) -> tuple[list[dict], str]:
    """Scan staged + unstaged diffs. Returns (findings, note)."""
    toplevel = repo_toplevel(root)
    if toplevel is None:
        return [], "not a git repository; pending-change scan skipped"
    if toplevel != root.resolve():
        return [], "not at repository top level; pending-change scan skipped"
    findings: list[dict] = []
    for args, label in ((["git", "diff", "--cached", "--", "."], "staged"),
                        (["git", "diff", "--", "."], "unstaged")):
        ok, output = run_command(args, cwd=root)
        if not ok:
            continue
        current_file = ""
        for line in output.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[len("+++ b/"):]
                continue
            if line.startswith("+") and not line.startswith("+++"):
                for name, pattern in PATTERNS:
                    if pattern.search(line[1:]):
                        findings.append({"file": current_file or "(unknown)",
                                         "line": 0, "pattern": name,
                                         "source": f"diff-{label}"})
                        break
    return findings, "pending changes scanned (staged + unstaged)"


def check_ignore_rules(root: Path) -> list[dict]:
    """Verify .env is ignored and .env.example stays trackable."""
    results: list[dict] = []
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        results.append({"check": "gitignore-present", "ok": False,
                        "detail": ".gitignore is missing"})
        return results
    text = gitignore.read_text(encoding="utf-8", errors="replace")
    has_env = any(line.strip().lstrip("/") == ".env" for line in text.splitlines())
    has_example_exception = any(line.strip() == "!.env.example" for line in text.splitlines())
    results.append({"check": "gitignore-ignores-env", "ok": has_env,
                    "detail": "'.env' rule present" if has_env else "'.env' rule MISSING"})
    results.append({"check": "gitignore-keeps-example", "ok": has_example_exception,
                    "detail": "'!.env.example' rule present" if has_example_exception
                    else "'!.env.example' rule MISSING"})

    # Behavioral check at the repository top level only.
    toplevel = repo_toplevel(root)
    if toplevel is not None and toplevel == root.resolve():
        ignored_ok, _ = run_command(["git", "check-ignore", "-q", ".env"], cwd=root)
        results.append({"check": "git-ignores-env", "ok": ignored_ok,
                        "detail": ".env is ignored by git" if ignored_ok
                        else ".env is NOT ignored by git"})
        example_ok, _ = run_command(["git", "check-ignore", "-q", ".env.example"], cwd=root)
        results.append({"check": "git-keeps-example", "ok": not example_ok,
                        "detail": ".env.example is trackable" if not example_ok
                        else ".env.example is IGNORED (must stay trackable)"})
        tracked_ok, tracked_out = run_command(["git", "ls-files", ".env"], cwd=root)
        env_tracked = tracked_ok and bool(tracked_out.strip())
        results.append({"check": "env-not-tracked", "ok": not env_tracked,
                        "detail": ".env is not tracked" if not env_tracked
                        else ".env IS TRACKED (credential leak risk)"})
    else:
        results.append({"check": "git-behavioral", "ok": True,
                        "detail": "git unavailable or not at repo top level; "
                                  "textual .gitignore rules only"})
    return results


def run_hygiene_checks(root: Optional[Path] = None) -> dict:
    root = (root or default_audit_root()).resolve()
    files, list_skipped = iter_candidate_files(root)
    file_findings, scan_skipped = scan_files(files, root)
    diff_findings, diff_note = scan_pending_changes(root)
    ignore_results = check_ignore_rules(root)
    ignore_problems = [r for r in ignore_results if not r["ok"]]
    skipped = sorted(list_skipped + scan_skipped, key=lambda e: e["file"])
    return {
        "root": str(root),
        "files_scanned": len(files),
        "diff_note": diff_note,
        "findings": file_findings + diff_findings,
        "ignore_rules": ignore_results,
        "clean": not file_findings and not diff_findings and not ignore_problems,
        "skipped": skipped[:100],
        "skipped_count": len(skipped),
        "limitation": "Pattern scanning catches common accidents only; absence of "
                      "findings is not proof that no secret is present. "
                      "Oversized (>1MB), non-UTF8/unreadable, and escaping-symlink "
                      "files are listed under skipped, not scanned.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check the repo for leaked secrets (values never printed).")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the structured report as JSON to this path.")
    args = parser.parse_args(argv)

    root = default_audit_root()
    report = run_hygiene_checks(root)
    print(f"Airlock secret hygiene ({report['files_scanned']} files, root: {report['root']})")
    print(f"  {report['diff_note']}")
    if report["skipped_count"]:
        print(f"  skipped (not scanned): {report['skipped_count']}")
        for entry in report["skipped"][:10]:
            print(f"    - {entry['file']} [{entry['reason']}]")
    for rule in report["ignore_rules"]:
        print(f"  [{'OK' if rule['ok'] else 'PROBLEM'}] {rule['check']}: {rule['detail']}")
    if report["findings"]:
        print(f"  FINDINGS: {len(report['findings'])} (values never shown)")
        for finding in report["findings"][:50]:
            print(f"    - {finding['file']}:{finding['line']} [{finding['pattern']}] via {finding['source']}")
    else:
        print("  No credential patterns found in scanned files or pending changes.")
    print(f"  Limitation: {report['limitation']}")

    exit_code = 0 if report["clean"] else 1
    if args.json_path:
        report["provenance"] = provenance_envelope(
            "check_secret_hygiene", argv=argv, root=root,
            extra={"exit_code": exit_code})
        try:
            atomic_write_json(args.json_path, report)
            print(f"  JSON report written to {args.json_path}")
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}", file=sys.stderr)
            return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

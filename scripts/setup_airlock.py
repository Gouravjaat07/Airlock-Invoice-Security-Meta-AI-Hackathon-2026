"""Interactive Airlock setup: secrets, PIN hash, local configuration.

Writes `.env` (git-ignored) at the project root. Never prints secrets,
never overwrites existing secrets silently, never invents a fallback PIN.

Only six application-managed keys are updated; every unrelated variable,
comment, Meta/Baseten/Glimmer setting and Phase 2 runtime flag is
preserved byte-for-byte (except newline normalization):
  AIRLOCK_PIN_HASH, AIRLOCK_SESSION_SECRET, AIRLOCK_BANK_HASH_KEY,
  AIRLOCK_DB_PATH, AIRLOCK_BLOB_DIR, AIRLOCK_ENV.
Duplicate managed assignments fail safely. Writes are atomic (temp file,
flush, fsync, atomic replace) so an interrupted write never truncates
the previous file. Restrictive permissions (POSIX 0600) are applied
where supported.

Usage:
  python scripts/setup_airlock.py [--non-interactive] [--env-file .env] [--overwrite]
Non-interactive mode (tests/automation only) reads the PIN from the
AIRLOCK_SETUP_PIN environment variable, which the caller injects.
Overwriting an existing PIN hash requires explicit authorization:
  interactive: type OVERWRITE at the prompt, or pass --overwrite;
  non-interactive: pass --overwrite or set AIRLOCK_SETUP_OVERWRITE=OVERWRITE.

Hidden PIN entry uses getpass. If the terminal cannot hide input, use the
safe Windows PowerShell alternative (never hardcode or echo the PIN):
  $SecurePin = Read-Host -AsSecureString 'Create owner PIN (min 4 chars)'
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePin)
  try { $env:AIRLOCK_SETUP_PIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto($Bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr); $SecurePin.Dispose() }
  python scripts/setup_airlock.py --non-interactive
  Remove-Item Env:AIRLOCK_SETUP_PIN
  Clear-History
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import find_project_root  # noqa: E402

try:
    from app.auth.pin import hash_pin
except ImportError:  # pragma: no cover
    hash_pin = None  # type: ignore[assignment]

MANAGED_KEYS = (
    "AIRLOCK_PIN_HASH",
    "AIRLOCK_SESSION_SECRET",
    "AIRLOCK_BANK_HASH_KEY",
    "AIRLOCK_DB_PATH",
    "AIRLOCK_BLOB_DIR",
    "AIRLOCK_ENV",
)

OVERWRITE_TOKEN = "OVERWRITE"


class DuplicateEnvKeyError(ValueError):
    """Duplicate assignment of a managed key (names the key, never values)."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"duplicate assignment of managed key: {key}")


def _parse_env_assignment(line: str) -> tuple[str, str, str, str] | None:
    """Parse one .env line or return None when not an assignment.

    Returns (key, export_prefix, value, trailing_comment). Value excludes
    any trailing ' #...' comment; trailing_comment keeps it (with leading
    whitespace) so writers can preserve it. Never raises on odd lines.
    """
    if "=" not in line:
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    left, _, right = line.partition("=")
    left_stripped = left.strip()
    export_prefix = ""
    key = left_stripped
    if (left_stripped.startswith("export")
            and len(left_stripped) > 6
            and left_stripped[6].isspace()):
        key = left_stripped[6:].strip()
        export_prefix = "export "
    if not key or any(ch.isspace() for ch in key) or "#" in key:
        return None
    comment = ""
    value = right.strip()
    marker = -1
    idx_space = right.find(" #")
    idx_tab = right.find("\t#")
    if idx_space != -1 and idx_tab != -1:
        marker = idx_space if idx_space < idx_tab else idx_tab
    elif idx_space != -1:
        marker = idx_space
    elif idx_tab != -1:
        marker = idx_tab
    if marker != -1:
        comment = right[marker:]
        # Normalize tab-led comments to a single leading space.
        if comment.startswith("\t"):
            comment = " " + comment[1:]
        value = right[:marker].strip()
    return (key, export_prefix, value, comment)


def _read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    text = path.read_text(encoding="utf-8")
    seen_managed: set[str] = set()
    for line in text.splitlines():
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, _, value, _ = parsed
        if key in MANAGED_KEYS:
            if key in seen_managed:
                raise DuplicateEnvKeyError(key)
            seen_managed.add(key)
        data[key] = value
    return data


def _atomic_write_text(path: Path, content: str) -> None:
    parent = path.parent
    if str(parent) not in (".", ""):
        parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            dir_fd = os.open(str(parent if str(parent) not in (".", "") else "."),
                             os.O_RDONLY)
        except OSError:
            dir_fd = -1
        else:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                try:
                    os.close(dir_fd)
                except OSError:
                    pass
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except BaseException:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    managed_values = {k: values[k] for k in MANAGED_KEYS if k in values}
    if not path.is_file():
        lines = ["# Airlock local configuration (generated by setup_airlock.py).",
                 "# Never commit this file. Never share its contents.",
                 ""]
        for key in MANAGED_KEYS:
            if key in managed_values:
                lines.append(f"{key}={managed_values[key]}")
        _atomic_write_text(path, "\n".join(lines) + "\n")
        return
    original = path.read_text(encoding="utf-8").splitlines()
    occurrences: dict[str, list[tuple[int, str, str]]] = {}
    for index, line in enumerate(original):
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, export_prefix, _, comment = parsed
        if key in MANAGED_KEYS:
            occurrences.setdefault(key, []).append((index, export_prefix,
                                                    comment))
    for key, hits in occurrences.items():
        if len(hits) > 1:
            raise DuplicateEnvKeyError(key)
    updated = list(original)
    for key in MANAGED_KEYS:
        if key not in managed_values:
            continue
        hits = occurrences.get(key, [])
        new_value = managed_values[key]
        if hits:
            index, export_prefix, comment = hits[0]
            updated[index] = f"{export_prefix}{key}={new_value}{comment}"
        else:
            updated.append(f"{key}={new_value}")
    _atomic_write_text(path, "\n".join(updated) + "\n")


def _print_hidden_input_help() -> None:
    print("ERROR: hidden PIN entry is unavailable in this terminal.",
          file=sys.stderr)
    print("Aborted without writing any file. No secrets were read or stored.",
          file=sys.stderr)
    print("Safe Windows PowerShell alternative (PIN never echoed, "
          "never hardcoded):", file=sys.stderr)
    print("  $SecurePin = Read-Host -AsSecureString "
          "'Create owner PIN (min 4 chars)'", file=sys.stderr)
    print("  $Bstr = [Runtime.InteropServices.Marshal]::"
          "SecureStringToBSTR($SecurePin)", file=sys.stderr)
    print("  try { $env:AIRLOCK_SETUP_PIN = [Runtime.InteropServices.Marshal]"
          "::PtrToStringAuto($Bstr) }", file=sys.stderr)
    print("  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr);"
          " $SecurePin.Dispose() }", file=sys.stderr)
    print("  python scripts/setup_airlock.py --non-interactive",
          file=sys.stderr)
    print("  Remove-Item Env:AIRLOCK_SETUP_PIN", file=sys.stderr)
    print("  Clear-History  # also clear PSReadLine history if enabled",
          file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up Airlock local configuration.")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Read PIN from AIRLOCK_SETUP_PIN (automation only).")
    parser.add_argument("--env-file", default=".env",
                        help="Target env file relative to project root.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Explicitly authorize replacing an existing PIN hash.")
    args = parser.parse_args(argv)

    if hash_pin is None:
        print("ERROR: app dependencies are not installed. Run: "
              ".\\.venv\\Scripts\\python.exe -m pip install -e \".[dev]\"",
              file=sys.stderr)
        return 1

    root = find_project_root() or Path.cwd()
    env_path = root / args.env_file
    try:
        existing = _read_env_file(env_path)
    except DuplicateEnvKeyError as exc:
        print(f"ERROR: {env_path} has a duplicate assignment of managed key "
              f"{exc.key}. Fix the file manually (keep one value) and rerun.",
              file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError):
        print(f"ERROR: cannot read {env_path}; existing file preserved.",
              file=sys.stderr)
        return 1

    if (existing.get("AIRLOCK_PIN_HASH") or "").strip():
        if args.overwrite:
            pass
        elif not args.non_interactive:
            try:
                answer = input(f"{env_path} already has AIRLOCK_PIN_HASH. "
                               "Overwrite? Type OVERWRITE to confirm: ").strip()
            except (EOFError, OSError, KeyboardInterrupt):
                print("Aborted: existing configuration preserved.")
                return 0
            if answer != OVERWRITE_TOKEN:
                print("Aborted: existing configuration preserved.")
                return 0
        else:
            if os.environ.get("AIRLOCK_SETUP_OVERWRITE", "") != OVERWRITE_TOKEN:
                print(f"ERROR: {env_path} already has AIRLOCK_PIN_HASH. "
                      "Refusing to overwrite without explicit authorization "
                      "(pass --overwrite or set AIRLOCK_SETUP_OVERWRITE="
                      "OVERWRITE).", file=sys.stderr)
                return 1

    session_secret = existing.get("AIRLOCK_SESSION_SECRET") or secrets.token_urlsafe(32)
    bank_key = existing.get("AIRLOCK_BANK_HASH_KEY") or secrets.token_urlsafe(32)

    if args.non_interactive:
        pin = os.environ.get("AIRLOCK_SETUP_PIN", "")
        if len(pin) < 4:
            print("ERROR: AIRLOCK_SETUP_PIN must be injected (min 4 chars).",
                  file=sys.stderr)
            return 1
    else:
        try:
            stdin_is_tty = sys.stdin.isatty()
        except (OSError, ValueError):
            stdin_is_tty = False
        if not stdin_is_tty:
            _print_hidden_input_help()
            return 1
        try:
            pin = getpass.getpass("Create owner PIN (min 4 chars, input hidden): ")
            confirm = getpass.getpass("Confirm owner PIN: ")
        except KeyboardInterrupt:
            print("Aborted: existing configuration preserved.", file=sys.stderr)
            return 1
        except (EOFError, OSError):
            _print_hidden_input_help()
            return 1
        if pin != confirm:
            print("ERROR: PIN entries do not match.", file=sys.stderr)
            return 1
        if len(pin) < 4:
            print("ERROR: PIN must be at least 4 characters.", file=sys.stderr)
            return 1

    values = {
        "AIRLOCK_PIN_HASH": hash_pin(pin),
        "AIRLOCK_SESSION_SECRET": session_secret,
        "AIRLOCK_BANK_HASH_KEY": bank_key,
        "AIRLOCK_DB_PATH": existing.get("AIRLOCK_DB_PATH", "./data/airlock.db"),
        "AIRLOCK_BLOB_DIR": existing.get("AIRLOCK_BLOB_DIR", "./data/blobs"),
        "AIRLOCK_ENV": existing.get("AIRLOCK_ENV", "development"),
    }
    try:
        _write_env_file(env_path, values)
    except DuplicateEnvKeyError as exc:
        print(f"ERROR: {env_path} has a duplicate assignment of managed key "
              f"{exc.key}. Fix the file manually (keep one value) and rerun.",
              file=sys.stderr)
        return 1
    except OSError:
        print(f"ERROR: cannot write {env_path}; existing file preserved.",
              file=sys.stderr)
        return 1
    print(f"Wrote {env_path} (PIN hash + generated secrets; values not shown).")
    print("Restrictive permissions set where supported (POSIX 0600).")
    print("Windows note: NTFS ACLs are not modified; keep this checkout "
          "private to the owner account (right-click > Properties > Security "
          "to restrict access).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reset local demo data (database + blobs). Destructive: explicit opt-in.

Only operates inside the configured Airlock data roots and only when they
resolve under the project root. Never touches source, results, or fixtures.

Usage: python scripts/reset_demo.py --yes
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset local demo data.")
    parser.add_argument("--yes", action="store_true",
                        help="Required confirmation flag.")
    args = parser.parse_args(argv)
    if not args.yes:
        print("Refusing to reset without --yes.", file=sys.stderr)
        return 1
    try:
        settings = load_settings()
    except Exception as exc:
        print(f"ERROR: invalid configuration: {exc}", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    db_path = Path(settings.db_path)
    blob_dir = Path(settings.blob_dir)
    if not _inside(db_path.parent if str(db_path.parent) not in (".", "") else root, root):
        print("ERROR: refusing to delete a database outside the project root.",
              file=sys.stderr)
        return 1
    if not _inside(blob_dir, root):
        print("ERROR: refusing to delete blobs outside the project root.",
              file=sys.stderr)
        return 1
    removed: list[str] = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(db_path) + suffix)
        if candidate.is_file():
            candidate.unlink()
            removed.append(str(candidate))
    if blob_dir.is_dir():
        for child in sorted(blob_dir.iterdir()):
            if child.is_file() or child.is_symlink():
                child.unlink()
                removed.append(str(child))
            elif child.is_dir():
                shutil.rmtree(child)
                removed.append(str(child) + "/")
    print(f"Reset complete: removed {len(removed)} path(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

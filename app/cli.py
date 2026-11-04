"""Application CLI: `python -m app.cli db upgrade` / `health`. (Phase 1
convention: argparse entry, exit codes, no secrets printed.)"""

from __future__ import annotations

import argparse
import json
import sys

from app import __version__
from app.config import load_settings
from app.storage import database


def cmd_db_upgrade(_: argparse.Namespace) -> int:
    settings = load_settings()
    result = database.upgrade(settings)
    print(json.dumps({"applied": result["applied"],
                      "current_version": result["current_version"]}))
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    settings = load_settings()
    ok, detail = database.is_integrity_ok(settings)
    print(json.dumps({"status": "ok" if ok else "degraded",
                      "version": __version__,
                      "database": detail,
                      "policy_version": settings.policy_version}))
    return 0 if ok else 1


def cmd_storage_sweep(_: argparse.Namespace) -> int:
    from app.storage.artifacts import LocalBlobStore
    settings = load_settings()
    database.upgrade(settings)
    conn = database.connect(settings)
    try:
        removed = LocalBlobStore(settings).sweep_orphans(conn)
    finally:
        conn.close()
    print(json.dumps({"removed": removed}))
    return 0


def cmd_fixtures_register(args: argparse.Namespace) -> int:
    from app import cli_fixtures
    settings = load_settings()
    result = cli_fixtures.register(
        settings, name=args.name, invoice=args.invoice,
        extraction=args.extraction, expected_verdict=args.expected_verdict,
        attack_type=args.attack_type, variant=args.variant, notes=args.notes,
        delivery=args.delivery, voice=args.voice, transcript=args.transcript,
        sam_count=args.sam_count, custom_dir=args.dir, force=args.force)
    print(json.dumps(result, indent=2))
    return 0


def cmd_fixtures_list(_: argparse.Namespace) -> int:
    from app import cli_fixtures
    settings = load_settings()
    print(json.dumps(cli_fixtures.list_fixtures(settings), indent=2))
    return 0


def cmd_fixtures_verify(args: argparse.Namespace) -> int:
    from app import cli_fixtures
    settings = load_settings()
    result = cli_fixtures.verify_bytes(settings, args.file)
    print(json.dumps(result, indent=2))
    return 0 if result["registered"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Airlock application CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    db = sub.add_parser("db", help="Database operations")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_upgrade = db_sub.add_parser("upgrade", help="Apply pending migrations")
    db_upgrade.set_defaults(func=cmd_db_upgrade)
    health = sub.add_parser("health", help="Local health check")
    health.set_defaults(func=cmd_health)
    storage = sub.add_parser("storage", help="Blob storage operations")
    storage_sub = storage.add_subparsers(dest="storage_command", required=True)
    sweep = storage_sub.add_parser("sweep", help="Delete orphaned blob files")
    sweep.set_defaults(func=cmd_storage_sweep)
    fixtures = sub.add_parser(
        "fixtures",
        help="Custom synthetic fixtures (dev/test only, never production)")
    fixtures_sub = fixtures.add_subparsers(dest="fixtures_command",
                                           required=True)
    register = fixtures_sub.add_parser(
        "register", help="Register a synthetic fixture from local files")
    register.add_argument("--name", required=True,
                          help="Scenario name (letters, digits, _/-)")
    register.add_argument("--invoice", required=True,
                          help="Invoice file to register (PDF/PNG/JPEG)")
    register.add_argument("--extraction", required=True,
                          help="JSON file with the expected extraction")
    register.add_argument("--expected-verdict", required=True,
                          choices=["ALLOW_PROPOSAL", "ESCALATE", "DENY"],
                          help="Owner-declared expectation (pipeline decides)")
    register.add_argument("--attack-type", default=None,
                          help="Optional v2 attack label (A01-A16)")
    register.add_argument("--variant", default="custom")
    register.add_argument("--notes", default="")
    register.add_argument("--delivery", default=None,
                          help="Optional delivery evidence file")
    register.add_argument("--voice", default=None,
                          help="Optional voice note file (WAV)")
    register.add_argument("--transcript", default=None,
                          help="Transcript for --voice (required with it)")
    register.add_argument("--sam-count", default=None, type=int,
                          help="Observed count for --delivery (required with it)")
    register.add_argument("--dir", default=None,
                          help="Custom fixtures dir (else "
                               "AIRLOCK_CUSTOM_FIXTURES_DIR)")
    register.add_argument("--force", action="store_true",
                          help="Overwrite an existing custom fixture")
    register.set_defaults(func=cmd_fixtures_register)
    fixtures_list = fixtures_sub.add_parser(
        "list", help="List canonical and custom fixtures")
    fixtures_list.set_defaults(func=cmd_fixtures_list)
    verify = fixtures_sub.add_parser(
        "verify", help="Check whether a file resolves to a fixture")
    verify.add_argument("--file", required=True)
    verify.set_defaults(func=cmd_fixtures_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

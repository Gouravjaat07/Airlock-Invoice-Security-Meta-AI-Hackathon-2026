"""Typed Airlock configuration validator (Phase 1).

Reads configuration from a provided environment mapping (default: os.environ).
Never prints secret values, never loads `.env` automatically, never sends
network requests.

Exit codes: 0 when no ERROR issues; 1 when any ERROR issue exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    atomic_write_json, default_audit_root, provenance_envelope,
)

CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
EXPECTED_SPARK_MODEL = "muse-spark-1.3"

# Default endpoints (project dossier values; must be verified before live use).
DEFAULT_META_API_BASE = "https://api.meta.ai/v1"
DEFAULT_BASETEN_BASE_URL = "https://inference.baseten.co/v1"
DEFAULT_BASETEN_SPARK_OPEN_MODEL = "meta-models/muse-spark-open-1026"
DEFAULT_GLIMMER_BASE_URL = "http://127.0.0.1:8081/v1"

# Variables whose values are secret and must never appear in output.
SECRET_VARS = frozenset({
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "AIRLOCK_PIN_HASH",
    "AIRLOCK_SESSION_SECRET",
})

# All recognised variables (used for presence reporting).
KNOWN_VARS = (
    "MODEL_API_KEY",
    "META_API_BASE",
    "SPARK_MODEL",
    "BASETEN_API_KEY",
    "BASETEN_BASE_URL",
    "BASETEN_SPARK_OPEN_MODEL",
    "GLIMMER_BASE_URL",
    "AIRLOCK_PIN_HASH",
    "AIRLOCK_SESSION_SECRET",
    "AIRLOCK_DB_PATH",
    "AIRLOCK_BLOB_DIR",
)

# Settings reserved for later application phases.
FUTURE_PHASE_VARS = frozenset({
    "AIRLOCK_PIN_HASH",
    "AIRLOCK_SESSION_SECRET",
    "AIRLOCK_DB_PATH",
    "AIRLOCK_BLOB_DIR",
})


@dataclass
class Issue:
    level: str  # "ERROR", "WARNING", or "INFO"
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass
class AirlockConfig:
    """Typed configuration. Secret fields hold values only in memory."""

    model_api_key: Optional[str] = None
    meta_api_base: str = DEFAULT_META_API_BASE
    spark_model: str = EXPECTED_SPARK_MODEL
    baseten_api_key: Optional[str] = None
    baseten_base_url: str = DEFAULT_BASETEN_BASE_URL
    baseten_spark_open_model: str = DEFAULT_BASETEN_SPARK_OPEN_MODEL
    glimmer_base_url: str = DEFAULT_GLIMMER_BASE_URL
    airlock_pin_hash: Optional[str] = None
    airlock_session_secret: Optional[str] = None
    airlock_db_path: str = "./data/airlock.db"
    airlock_blob_dir: str = "./data/blobs"

    def redacted_dict(self) -> dict:
        """Presence-only view safe for reports: secrets shown as set/unset.

        Secret fields are driven by SECRET_VARS (lowercased to field names)
        so a newly added secret variable cannot silently leak into reports.
        """
        redacted = {
            "meta_api_base": self.meta_api_base,
            "spark_model": self.spark_model,
            "baseten_base_url": self.baseten_base_url,
            "baseten_spark_open_model": self.baseten_spark_open_model,
            "glimmer_base_url": self.glimmer_base_url,
            "airlock_db_path": self.airlock_db_path,
            "airlock_blob_dir": self.airlock_blob_dir,
        }
        for var in sorted(SECRET_VARS):
            redacted[var.lower()] = _presence(getattr(self, var.lower()))
        return redacted


def _presence(value: Optional[str]) -> str:
    return "set" if value else "unset"


def _non_empty(env: Mapping[str, str], name: str) -> Optional[str]:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def is_valid_http_url(value: str) -> bool:
    """Syntax-only URL check. Performs no network I/O."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def load_config(env: Optional[Mapping[str, str]] = None) -> tuple[AirlockConfig, list[Issue]]:
    """Build a typed config from `env` and collect validation issues."""
    env = env if env is not None else os.environ
    issues: list[Issue] = []

    model_api_key = _non_empty(env, "MODEL_API_KEY")
    baseten_api_key = _non_empty(env, "BASETEN_API_KEY")
    meta_api_base = _non_empty(env, "META_API_BASE") or DEFAULT_META_API_BASE
    spark_model = _non_empty(env, "SPARK_MODEL") or EXPECTED_SPARK_MODEL
    baseten_base_url = _non_empty(env, "BASETEN_BASE_URL") or DEFAULT_BASETEN_BASE_URL
    baseten_model = _non_empty(env, "BASETEN_SPARK_OPEN_MODEL") or DEFAULT_BASETEN_SPARK_OPEN_MODEL
    glimmer_base_url = _non_empty(env, "GLIMMER_BASE_URL") or DEFAULT_GLIMMER_BASE_URL
    pin_hash = _non_empty(env, "AIRLOCK_PIN_HASH")
    session_secret = _non_empty(env, "AIRLOCK_SESSION_SECRET")
    db_path = _non_empty(env, "AIRLOCK_DB_PATH") or "./data/airlock.db"
    blob_dir = _non_empty(env, "AIRLOCK_BLOB_DIR") or "./data/blobs"

    config = AirlockConfig(
        model_api_key=model_api_key,
        meta_api_base=meta_api_base,
        spark_model=spark_model,
        baseten_api_key=baseten_api_key,
        baseten_base_url=baseten_base_url,
        baseten_spark_open_model=baseten_model,
        glimmer_base_url=glimmer_base_url,
        airlock_pin_hash=pin_hash,
        airlock_session_secret=session_secret,
        airlock_db_path=db_path,
        airlock_blob_dir=blob_dir,
    )

    # --- URL syntax (unset vs invalid are distinct states) ---
    for var_name, value, was_set in (
        ("META_API_BASE", meta_api_base, "META_API_BASE" in env and bool(_non_empty(env, "META_API_BASE"))),
        ("BASETEN_BASE_URL", baseten_base_url, "BASETEN_BASE_URL" in env and bool(_non_empty(env, "BASETEN_BASE_URL"))),
        ("GLIMMER_BASE_URL", glimmer_base_url, "GLIMMER_BASE_URL" in env and bool(_non_empty(env, "GLIMMER_BASE_URL"))),
    ):
        if not is_valid_http_url(value):
            if was_set:
                issues.append(Issue("ERROR", f"invalid-url:{var_name}",
                                    f"{var_name} is set but is not a valid http(s) URL."))
            else:
                issues.append(Issue("ERROR", f"invalid-url:{var_name}",
                                    f"{var_name} default is not a valid http(s) URL (internal error)."))

    # --- Runtime model must not be the Contributor variant ---
    if spark_model == CONTRIBUTOR_MODEL:
        issues.append(Issue(
            "ERROR", "contributor-as-runtime",
            "SPARK_MODEL is `muse-spark-1.3-contributor`, which is for development "
            "assistance only and must not be used for real or confidential Airlock data. "
            "Set SPARK_MODEL=muse-spark-1.3 for the runtime."))
    elif spark_model != EXPECTED_SPARK_MODEL:
        issues.append(Issue(
            "WARNING", "unexpected-spark-model",
            f"SPARK_MODEL is `{spark_model}`; expected `{EXPECTED_SPARK_MODEL}`. "
            "Verify this is intentional before live use."))

    # --- Credential separation: Meta and Baseten keys must differ ---
    if model_api_key and baseten_api_key and model_api_key == baseten_api_key:
        issues.append(Issue(
            "ERROR", "shared-credential",
            "MODEL_API_KEY and BASETEN_API_KEY have the same value. Keys must not be "
            "shared or silently substituted between providers."))

    # --- Key presence is informational in Phase 1 (live tests are opt-in) ---
    if not model_api_key:
        issues.append(Issue("INFO", "unset:MODEL_API_KEY",
                            "MODEL_API_KEY is unset: Meta live smoke tests are disabled (preflight only)."))
    if not baseten_api_key:
        issues.append(Issue("INFO", "unset:BASETEN_API_KEY",
                            "BASETEN_API_KEY is unset: Baseten live smoke tests are disabled (preflight only)."))

    # --- Future-phase settings must not be required now ---
    for var_name in sorted(FUTURE_PHASE_VARS):
        if _non_empty(env, var_name):
            issues.append(Issue(
                "INFO", f"future-phase-set:{var_name}",
                f"{var_name} is set; it is reserved for later application phases "
                "and is not used by Phase 1 tooling."))
        else:
            issues.append(Issue(
                "INFO", f"future-phase-unset:{var_name}",
                f"{var_name} is unset, as expected in Phase 1 (later-phase setting)."))

    return config, issues


def validate_environment(env: Optional[Mapping[str, str]] = None) -> dict:
    """Presence report: which known variables are set (values never included)."""
    env = env if env is not None else os.environ
    return {name: bool(_non_empty(env, name)) for name in KNOWN_VARS}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Airlock configuration (no network, no secrets printed).")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the validation report as JSON to this path.")
    parser.add_argument("--env-file", dest="env_file", default=None,
                        help="Optional: validate KEY=VALUE pairs from this file instead of the process environment. "
                             "The file is never printed.")
    args = parser.parse_args(argv)

    env: Mapping[str, str]
    if args.env_file:
        env = _read_env_file(args.env_file)
        if env is None:
            print(f"ERROR: cannot read env file: {args.env_file}", file=sys.stderr)
            return 1
    else:
        env = os.environ

    config, issues = load_config(env)
    errors = [i for i in issues if i.level == "ERROR"]
    warnings = [i for i in issues if i.level == "WARNING"]

    print("Airlock configuration validation")
    print(f"  errors: {len(errors)}  warnings: {len(warnings)}  info: {len(issues) - len(errors) - len(warnings)}")
    for issue in issues:
        print(f"  [{issue.level}] {issue.code}: {issue.message}")
    print("  config (redacted): " + json.dumps(config.redacted_dict()))

    exit_code = 1 if errors else 0
    if args.json_path:
        report = {
            "config_redacted": config.redacted_dict(),
            "issues": [i.to_dict() for i in issues],
            "valid": not errors,
            "provenance": provenance_envelope(
                "validate_config", argv=argv, root=default_audit_root(),
                extra={"exit_code": exit_code}),
        }
        try:
            atomic_write_json(args.json_path, report)
            print(f"  JSON report written to {args.json_path}")
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}", file=sys.stderr)
            return 1

    return exit_code


def _read_env_file(path: str) -> Optional[dict[str, str]]:
    """Parse a KEY=VALUE file without printing it. Returns None on failure."""
    data: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                data[key.strip()] = value.strip().strip("'\"")
    except (OSError, UnicodeDecodeError):
        return None
    return data


if __name__ == "__main__":
    raise SystemExit(main())

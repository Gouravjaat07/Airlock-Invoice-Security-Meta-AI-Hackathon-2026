"""Central validated configuration (env + policy TOML).

Conventions follow Phase 1 `validate_config.py`: process environment is
the only credential source, `.env` is never auto-loaded, secrets are
presence-only in every report. Business thresholds live in
`policy/rules.toml`; operational settings come from `AIRLOCK_*` env vars.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from app.core.errors import AppError, ErrorCode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = PROJECT_ROOT / "policy" / "rules.toml"

SECRET_VARS = frozenset({
    "AIRLOCK_PIN_HASH",
    "AIRLOCK_SESSION_SECRET",
    "AIRLOCK_BANK_HASH_KEY",
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "GLIMMER_API_KEY",
})

# Provider/model identifiers: printable, no whitespace/controls/URL metachars.
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
CONTRIBUTOR_SUFFIX = "-contributor"

READER_PROVIDERS = frozenset({"fixture", "spark", "spark-open", "glimmer"})
VOICE_PROVIDERS = frozenset({"mock", "meta"})
VISION_PROVIDERS = frozenset({"mock", "sam"})


def _non_empty(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _non_empty(env, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.INTERNAL, f"Invalid integer for {name}: {raw!r}") from exc


def _get_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _non_empty(env, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.INTERNAL, f"Invalid number for {name}: {raw!r}") from exc


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _non_empty(env, name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- secrets (never logged, never in reports) ---
    pin_hash: str | None = None
    # Reserved for future HMAC binding of opaque tokens: sessions and
    # challenges are 256-bit random values whose SHA-256 is stored, which
    # needs no key. Generated at setup, validated as set/unset only.
    session_secret: str | None = None
    bank_hash_key: bytes | None = None

    # --- storage ---
    db_path: str = "./data/airlock.db"
    blob_dir: str = "./data/blobs"
    policy_path: str = str(DEFAULT_POLICY_PATH)

    # --- runtime mode ---
    environment: str = "development"  # development | production | test
    allow_insecure_cookies: bool = False  # loopback-only dev escape hatch
    fixture_reader_enabled: bool = False  # synthetic fixtures (dev/test/demo)
    fixtures_dir: str = "./fixtures"
    # Owner-registered extra fixtures (dev/test only; never production).
    # Scanned alongside fixtures_dir by the fixture/mock adapters; never by
    # the offline evaluation gates, which stay pinned to canonical fixtures.
    custom_fixtures_dir: str | None = None
    enable_eval_api: bool = False  # dev-only evaluation endpoints

    # --- uploads / artifacts ---
    max_upload_bytes: int = 10 * 1024 * 1024
    max_files_per_case: int = 5
    max_pdf_pages: int = 20
    max_image_pixels: int = 40_000_000
    max_audio_seconds: int = 300
    max_video_seconds: int = 300
    accepted_invoice_extensions: tuple = (".pdf", ".png", ".jpg", ".jpeg")
    accepted_audio_extensions: tuple = (".wav",)
    accepted_video_extensions: tuple = (".mp4",)

    # --- processing ---
    processing_timeout_seconds: int = 120
    max_concurrent_processing: int = 2

    # --- auth / sessions ---
    session_duration_minutes: int = 30
    challenge_duration_minutes: int = 5
    proposal_ttl_minutes: int = 60
    login_max_attempts: int = 5
    lockout_minutes: int = 15
    per_session_requests_per_minute: int = 30

    # --- policy (defaults; policy/rules.toml is authoritative when present) ---
    policy_version: str = "2.0.0"
    per_invoice_cap_default: str = "10000.00"
    currency_precision: int = 2
    due_date_max_days: int = 120
    sam_count_min: int = 0
    sam_count_max: int = 100000
    catalogue_tolerance_default: int = 0
    bank_change_cooldown_hours: int = 24

    # --- model providers (Phase 3; keys are secrets, never logged) ---
    model_api_key: str | None = None  # MODEL_API_KEY (Meta Model API)
    meta_api_base: str = "https://api.meta.ai/v1"
    spark_model: str = "muse-spark-1.3"
    voice_model: str = "muse-voice-transcribe-1.0"  # VOICE_MODEL
    sam_model: str = "sam-3.1"  # SAM_MODEL
    baseten_api_key: str | None = None
    baseten_base_url: str = "https://inference.baseten.co/v1"
    baseten_spark_open_model: str = "meta-models/muse-spark-open-1026"
    glimmer_base_url: str = "http://127.0.0.1:8081/v1"
    glimmer_model: str = "muse-glimmer"  # GLIMMER_MODEL
    glimmer_api_key: str | None = None  # optional; some runtimes need none
    # Explicit per-task selection; fixture/mock are dev/test only (never prod).
    reader_provider: str = "fixture"  # fixture | spark | spark-open | glimmer
    voice_provider: str = "mock"  # mock | meta
    vision_provider: str = "mock"  # mock | sam
    # Bounded per-task timeout profiles (seconds; sync client).
    provider_connect_timeout_s: int = 10
    extraction_timeout_s: int = 180
    voice_timeout_s: int = 300
    sam_timeout_s: int = 300
    provider_max_inflight: int = 2  # per-provider concurrent calls
    provider_max_retries: int = 2  # retries after the first attempt
    spark_max_output_tokens: int = 4096  # structured-extraction cap (>=16)

    # --- misc ---
    log_level: str = "INFO"
    audit_retention_days: int = 0  # 0 = retain indefinitely (prototype)

    def redacted_dict(self) -> dict:
        secrets = ("pin_hash", "session_secret", "bank_hash_key",
                   "model_api_key", "baseten_api_key", "glimmer_api_key")
        data = {k: v for k, v in self.__dict__.items() if k not in secrets}
        for name in secrets:
            value = getattr(self, name)
            data[name] = "set" if value else "unset"
        return data


def load_policy_file(path: str | Path) -> dict:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise AppError(ErrorCode.INTERNAL,
                       f"Policy file not found: {path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AppError(ErrorCode.INTERNAL,
                       f"Invalid policy file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AppError(ErrorCode.INTERNAL, f"Invalid policy file {path}")
    return data


def _policy_int(rules: dict, key: str) -> int | None:
    """Strict integer for one policy key; AppError (fail closed) on garbage."""
    if rules.get(key) is None:
        return None
    value = rules[key]
    if isinstance(value, (bool, float)):
        raise AppError(ErrorCode.INTERNAL,
                       f"Invalid policy value for {key}: expected an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.INTERNAL,
                       f"Invalid policy value for {key}: expected an integer"
                       ) from exc


def apply_policy(settings: Settings, policy: dict) -> Settings:
    rules = policy.get("rules", {})
    meta = policy.get("meta", {})
    if meta.get("version"):
        settings.policy_version = str(meta["version"])
    if rules.get("per_invoice_cap_default") is not None:
        raw = str(rules["per_invoice_cap_default"])
        try:
            parsed = Decimal(raw)
        except InvalidOperation as exc:
            raise AppError(ErrorCode.INTERNAL,
                           "Invalid policy value for per_invoice_cap_default:"
                           " not a decimal") from exc
        if parsed <= 0:
            raise AppError(ErrorCode.INTERNAL,
                           "Invalid policy value for per_invoice_cap_default:"
                           " must be positive")
        settings.per_invoice_cap_default = str(parsed)
    for key in ("currency_precision", "due_date_max_days", "sam_count_min",
                "sam_count_max", "catalogue_tolerance_default",
                "bank_change_cooldown_hours"):
        parsed_int = _policy_int(rules, key)
        if parsed_int is not None:
            setattr(settings, key, parsed_int)
    # Rule on/off switches are intentionally NOT configurable: R1-R10 are
    # fixed security invariants. Unknown keys are ignored (forward compat).
    return settings


def load_settings(env: Mapping[str, str] | None = None,
                  policy_path: str | Path | None = None) -> Settings:
    env = env if env is not None else os.environ
    settings = Settings(
        pin_hash=_non_empty(env, "AIRLOCK_PIN_HASH"),
        session_secret=_non_empty(env, "AIRLOCK_SESSION_SECRET"),
        bank_hash_key=(_non_empty(env, "AIRLOCK_BANK_HASH_KEY") or "").encode("utf-8") or None,
        db_path=_non_empty(env, "AIRLOCK_DB_PATH") or "./data/airlock.db",
        blob_dir=_non_empty(env, "AIRLOCK_BLOB_DIR") or "./data/blobs",
        environment=(_non_empty(env, "AIRLOCK_ENV") or "development").lower(),
        allow_insecure_cookies=_get_bool(env, "AIRLOCK_ALLOW_INSECURE_COOKIES", False),
        fixture_reader_enabled=_get_bool(env, "AIRLOCK_FIXTURE_READER", False),
        fixtures_dir=_non_empty(env, "AIRLOCK_FIXTURES_DIR") or "./fixtures",
        custom_fixtures_dir=_non_empty(env, "AIRLOCK_CUSTOM_FIXTURES_DIR"),
        enable_eval_api=_get_bool(env, "AIRLOCK_ENABLE_EVAL_API", False),
        max_upload_bytes=_get_int(env, "AIRLOCK_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_files_per_case=_get_int(env, "AIRLOCK_MAX_FILES_PER_CASE", 5),
        max_pdf_pages=_get_int(env, "AIRLOCK_MAX_PDF_PAGES", 20),
        max_image_pixels=_get_int(env, "AIRLOCK_MAX_IMAGE_PIXELS", 40_000_000),
        max_audio_seconds=_get_int(env, "AIRLOCK_MAX_AUDIO_SECONDS", 300),
        max_video_seconds=_get_int(env, "AIRLOCK_MAX_VIDEO_SECONDS", 300),
        processing_timeout_seconds=_get_int(env, "AIRLOCK_PROCESSING_TIMEOUT_S", 120),
        max_concurrent_processing=_get_int(env, "AIRLOCK_MAX_CONCURRENT", 2),
        session_duration_minutes=_get_int(env, "AIRLOCK_SESSION_MINUTES", 30),
        challenge_duration_minutes=_get_int(env, "AIRLOCK_CHALLENGE_MINUTES", 5),
        proposal_ttl_minutes=_get_int(env, "AIRLOCK_PROPOSAL_TTL_MINUTES", 60),
        login_max_attempts=_get_int(env, "AIRLOCK_LOGIN_MAX_ATTEMPTS", 5),
        lockout_minutes=_get_int(env, "AIRLOCK_LOCKOUT_MINUTES", 15),
        per_session_requests_per_minute=_get_int(env, "AIRLOCK_RATE_PER_MINUTE", 30),
        log_level=_non_empty(env, "AIRLOCK_LOG_LEVEL") or "INFO",
        audit_retention_days=_get_int(env, "AIRLOCK_AUDIT_RETENTION_DAYS", 0),
        model_api_key=_non_empty(env, "MODEL_API_KEY"),
        meta_api_base=_non_empty(env, "META_API_BASE") or "https://api.meta.ai/v1",
        spark_model=_non_empty(env, "SPARK_MODEL") or "muse-spark-1.3",
        voice_model=_non_empty(env, "VOICE_MODEL") or "muse-voice-transcribe-1.0",
        sam_model=_non_empty(env, "SAM_MODEL") or "sam-3.1",
        baseten_api_key=_non_empty(env, "BASETEN_API_KEY"),
        baseten_base_url=_non_empty(env, "BASETEN_BASE_URL") or "https://inference.baseten.co/v1",
        baseten_spark_open_model=(_non_empty(env, "BASETEN_SPARK_OPEN_MODEL")
                                  or "meta-models/muse-spark-open-1026"),
        glimmer_base_url=_non_empty(env, "GLIMMER_BASE_URL") or "http://127.0.0.1:8081/v1",
        glimmer_model=_non_empty(env, "GLIMMER_MODEL") or "muse-glimmer",
        glimmer_api_key=_non_empty(env, "GLIMMER_API_KEY"),
        reader_provider=(_non_empty(env, "AIRLOCK_READER_PROVIDER") or "fixture").lower(),
        voice_provider=(_non_empty(env, "AIRLOCK_VOICE_PROVIDER") or "mock").lower(),
        vision_provider=(_non_empty(env, "AIRLOCK_VISION_PROVIDER") or "mock").lower(),
        provider_connect_timeout_s=_get_int(env, "AIRLOCK_PROVIDER_CONNECT_TIMEOUT_S", 10),
        extraction_timeout_s=_get_int(env, "AIRLOCK_EXTRACTION_TIMEOUT_S", 180),
        voice_timeout_s=_get_int(env, "AIRLOCK_VOICE_TIMEOUT_S", 300),
        sam_timeout_s=_get_int(env, "AIRLOCK_SAM_TIMEOUT_S", 300),
        provider_max_inflight=_get_int(env, "AIRLOCK_PROVIDER_MAX_INFLIGHT", 2),
        provider_max_retries=_get_int(env, "AIRLOCK_PROVIDER_MAX_RETRIES", 2),
        spark_max_output_tokens=_get_int(env, "AIRLOCK_SPARK_MAX_OUTPUT_TOKENS", 4096),
    )
    resolved_policy = str(policy_path or settings.policy_path)
    settings.policy_path = resolved_policy
    policy = load_policy_file(resolved_policy)
    apply_policy(settings, policy)
    _validate_safety(settings)
    return settings


def _validate_base_url(value: str, name: str, *, https_only: bool,
                       problems: list[str]) -> None:
    try:
        parts = urlsplit(value)
    except ValueError:
        problems.append(f"{name} is not a valid URL")
        return
    if parts.scheme not in ("http", "https") or not parts.hostname:
        problems.append(f"{name} must be an http(s) URL with a host")
        return
    if parts.username or parts.password:
        problems.append(f"{name} must not embed credentials")
        return
    if https_only and parts.scheme != "https":
        problems.append(f"{name} must use https")
        return
    if (not https_only and parts.scheme == "http"
            and parts.hostname not in ("127.0.0.1", "localhost", "::1")):
        problems.append(f"{name} may use plain http for loopback only")


def _validate_model_id(value: str, name: str, problems: list[str]) -> None:
    if not _MODEL_ID_RE.match(value):
        problems.append(f"{name} is not a valid model identifier")
    elif value.lower().endswith(CONTRIBUTOR_SUFFIX):
        problems.append(f"{name} must not be a contributor/dev-only model")


def _validate_safety(settings: Settings) -> None:
    problems: list[str] = []
    if settings.environment == "production" and settings.allow_insecure_cookies:
        problems.append("allow_insecure_cookies must be false in production")
    if settings.environment == "production" and settings.fixture_reader_enabled:
        problems.append("fixture reader must be disabled in production")
    if settings.environment == "production" and settings.custom_fixtures_dir:
        problems.append("custom fixtures must not be configured in production")
    if settings.environment == "production" and settings.reader_provider == "fixture":
        problems.append("fixture reader provider must not be used in production")
    if settings.environment == "production" and settings.voice_provider == "mock":
        problems.append("mock voice provider must not be used in production")
    if settings.environment == "production" and settings.vision_provider == "mock":
        problems.append("mock vision provider must not be used in production")
    if settings.reader_provider not in READER_PROVIDERS:
        problems.append(f"unknown reader provider: {settings.reader_provider}")
    if settings.voice_provider not in VOICE_PROVIDERS:
        problems.append(f"unknown voice provider: {settings.voice_provider}")
    if settings.vision_provider not in VISION_PROVIDERS:
        problems.append(f"unknown vision provider: {settings.vision_provider}")
    _validate_base_url(settings.meta_api_base, "META_API_BASE",
                       https_only=True, problems=problems)
    _validate_base_url(settings.baseten_base_url, "BASETEN_BASE_URL",
                       https_only=True, problems=problems)
    _validate_base_url(settings.glimmer_base_url, "GLIMMER_BASE_URL",
                       https_only=False, problems=problems)
    _validate_model_id(settings.spark_model, "SPARK_MODEL", problems)
    _validate_model_id(settings.voice_model, "VOICE_MODEL", problems)
    _validate_model_id(settings.sam_model, "SAM_MODEL", problems)
    _validate_model_id(settings.baseten_spark_open_model,
                       "BASETEN_SPARK_OPEN_MODEL", problems)
    _validate_model_id(settings.glimmer_model, "GLIMMER_MODEL", problems)
    if (settings.model_api_key and settings.baseten_api_key
            and settings.model_api_key == settings.baseten_api_key):
        problems.append("MODEL_API_KEY and BASETEN_API_KEY must differ")
    if not 1 <= settings.provider_connect_timeout_s <= 120:
        problems.append("provider connect timeout out of range (1..120s)")
    for name in ("extraction_timeout_s", "voice_timeout_s", "sam_timeout_s"):
        if not 5 <= getattr(settings, name) <= 1800:
            problems.append(f"{name} out of range (5..1800s)")
    if not 1 <= settings.provider_max_inflight <= 16:
        problems.append("provider max inflight out of range (1..16)")
    if not 0 <= settings.provider_max_retries <= 5:
        problems.append("provider max retries out of range (0..5)")
    if settings.spark_max_output_tokens < 16:
        problems.append("spark max output tokens below provider minimum (16)")
    if settings.max_upload_bytes <= 0 or settings.max_files_per_case <= 0:
        problems.append("upload limits must be positive")
    if settings.login_max_attempts <= 0 or settings.lockout_minutes <= 0:
        problems.append("lockout settings must be positive")
    if settings.session_duration_minutes <= 0 or settings.challenge_duration_minutes <= 0:
        problems.append("session/challenge durations must be positive")
    if settings.due_date_max_days <= 0 or settings.currency_precision < 0:
        problems.append("policy date/currency settings invalid")
    try:
        cap = Decimal(str(settings.per_invoice_cap_default))
    except InvalidOperation:
        problems.append("per-invoice cap is not a valid decimal")
    else:
        if cap <= 0:
            problems.append("per-invoice cap must be positive")
    if settings.sam_count_min < 0 or settings.sam_count_max < settings.sam_count_min:
        problems.append("SAM count range invalid")
    if settings.enable_eval_api and settings.environment == "production":
        problems.append("evaluation API must not be enabled in production")
    if problems:
        raise AppError(ErrorCode.INTERNAL,
                       "Unsafe configuration: " + "; ".join(problems))


_settings_override: Settings | None = None


def get_settings() -> Settings:
    if _settings_override is not None:
        return _settings_override
    return load_settings()


def override_settings(settings: Settings | None) -> None:
    """Test hook: inject settings (never a committed secret)."""
    global _settings_override
    _settings_override = settings

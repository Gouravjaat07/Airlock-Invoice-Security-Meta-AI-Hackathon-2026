"""Validate an Airlock benchmark manifest (Phase 1, schema v2.0.0).

Standard-library only: mirrors eval/manifest.schema.json field-for-field so
validation runs with zero dependencies. Canonical contract is v2.0.0
(`attack_type`; see docs/phase1/MANIFEST_MIGRATION_v2.md).

Supported-subset + parity note: this validator does NOT implement full JSON
Schema Draft 2020-12. It enforces exactly the subset the contract uses
(required, type, enum, pattern, minLength, minItems, minimum,
additionalProperties:false) plus two intentional strict extensions
(duplicate case_id rejection, safe artifact paths, duplicate artifact
rejection). Pattern/enum/required parity with the schema file is enforced by
tests/test_manifest_schema.py::test_validator_schema_pattern_parity, which
fails if either side drifts. Patterns are stored unanchored and applied with
re.fullmatch, matching ECMA `^...$` semantics exactly (a trailing newline
fails here just as it fails a compliant JSON Schema validator).

Hash rule: for non-template manifests, `sha256` must be the hex digest of
canonical_hash(cases); malformed digests and mismatches fail. The template
placeholder `template-placeholder-replaced-at-generation` warns (does not
fail) so the template validates while carrying no fabricated hash.

Behavior:
  * Parses the JSON file (malformed JSON / invalid UTF-8 fail).
  * Checks required fields, types, enums, attack types, unique case_ids.
  * Rejects duplicate artifact paths within a case.
  * Enforces safe artifact path rules without reading artifact files.
  * Deterministic, human-readable output; nonzero exit on failure.
  * Never modifies the manifest.

Safe artifact path rules: relative POSIX-style path, no drive/UNC/URL, no
parent traversal (raw or percent-encoded), no empty/dot segments, no
backslashes, no null bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from typing import Any, Optional
from urllib.parse import unquote

# Unanchored patterns applied with fullmatch (ECMA ^...$ parity).
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
CASE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
ATTACK_TYPE_RE = re.compile(r"A(0[1-9]|1[0-6])")
CURRENCY_RE = re.compile(r"[A-Z]{3}")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")

TOP_REQUIRED = ("manifest_version", "seed", "split", "generator_commit", "cases", "sha256")
TOP_ALLOWED = set(TOP_REQUIRED)
CASE_REQUIRED = ("case_id", "base_doc_id", "variant", "artifacts", "ground_truth", "expected_verdict")
CASE_ALLOWED = set(CASE_REQUIRED) | {"attack_type", "notes"}
GT_REQUIRED = ("vendor_id", "invoice_total", "currency")
GT_ALLOWED = set(GT_REQUIRED) | {"due_date", "line_item_count"}

SPLITS = ("dev", "test")
VARIANTS = ("clean", "attack", "ambiguous", "failure")
VERDICTS = ("ALLOW_PROPOSAL", "ESCALATE", "DENY")

SHA_PLACEHOLDER = "template-placeholder-replaced-at-generation"


def canonical_hash(cases: list) -> str:
    """Hex SHA-256 over the canonical case payload (see eval/README.md).

    Canonical bytes: json.dumps(cases, sort_keys=True,
    separators=(",", ":"), ensure_ascii=True).encode("utf-8"). The recorded
    `sha256` field itself is never part of the hashed payload.
    """
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def is_safe_artifact_path(value: Any) -> Optional[str]:
    """Return None if safe, else a human-readable reason."""
    if not isinstance(value, str) or not value:
        return "artifact path must be a non-empty string"
    if value.startswith("\\\\"):
        return f"UNC path not allowed: {value}"
    if "\\" in value:
        return f"backslashes not allowed: {value}"
    if value.startswith("/"):
        return f"absolute path not allowed: {value}"
    if ":" in value:
        return f"drive letters and URLs not allowed: {value}"
    if "\x00" in value:
        return "null bytes not allowed in artifact path"
    lowered = value.lower()
    if "%00" in lowered:
        return "percent-encoded null byte not allowed in artifact path"
    if "%2f" in lowered or "%5c" in lowered:
        return f"percent-encoded separators not allowed: {value}"
    decoded = value
    for _ in range(3):  # catch double-encoded traversal (e.g. %252e)
        once = unquote(decoded)
        if once == decoded:
            break
        decoded = once
    segments = decoded.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return f"empty, '.', or '..' segment not allowed: {value}"
    return None


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate_manifest(data: Any) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Deterministic order: document order."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ["manifest root must be an object"], warnings

    for key in TOP_REQUIRED:
        if key not in data:
            errors.append(f"missing required property: {key}")
    for key in data:
        if key not in TOP_ALLOWED:
            errors.append(f"unknown top-level property: {key}")

    if "manifest_version" in data:
        value = data["manifest_version"]
        if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
            errors.append("manifest_version must be a semver string like '2.0.0'")
    if "seed" in data:
        value = data["seed"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append("seed must be an integer >= 0")
    if "split" in data and data["split"] not in SPLITS:
        errors.append(f"split must be one of {list(SPLITS)}; got {data['split']!r}")
    if "generator_commit" in data:
        value = data["generator_commit"]
        if not isinstance(value, str) or not value:
            errors.append("generator_commit must be a non-empty string")

    sha_value = data.get("sha256")
    sha_is_hex = False
    if "sha256" in data:
        if not isinstance(sha_value, str) or not sha_value:
            errors.append("sha256 must be a non-empty string")
        elif sha_value == SHA_PLACEHOLDER:
            warnings.append("sha256 carries the template placeholder; the generator must "
                            "replace it with the canonical hash (see eval/README.md)")
        elif not SHA256_RE.fullmatch(sha_value):
            errors.append("sha256 must be 64 lowercase hex characters (or the documented "
                          "template placeholder)")
        else:
            sha_is_hex = True

    cases = data.get("cases")
    if "cases" in data:
        if not isinstance(cases, list) or not cases:
            errors.append("cases must be a non-empty array")
        else:
            seen: set[str] = set()
            for index, case in enumerate(cases):
                where = f"cases[{index}]"
                if not isinstance(case, dict):
                    errors.append(f"{where}: must be an object")
                    continue
                for key in CASE_REQUIRED:
                    if key not in case:
                        errors.append(f"{where}: missing required property: {key}")
                for key in case:
                    if key not in CASE_ALLOWED:
                        errors.append(f"{where}: unknown property: {key}")

                case_id = case.get("case_id")
                if "case_id" in case:
                    if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
                        errors.append(f"{where}: case_id must match ^[A-Za-z0-9][A-Za-z0-9_-]*$")
                    elif case_id in seen:
                        errors.append(f"{where}: duplicate case_id: {case_id}")
                    else:
                        seen.add(case_id)
                if "base_doc_id" in case:
                    value = case["base_doc_id"]
                    if not isinstance(value, str) or not value:
                        errors.append(f"{where}: base_doc_id must be a non-empty string")
                if "variant" in case and case["variant"] not in VARIANTS:
                    errors.append(f"{where}: variant must be one of {list(VARIANTS)}; "
                                  f"got {case['variant']!r}")
                if "attack_type" in case:
                    attack = case["attack_type"]
                    if attack is not None and (not isinstance(attack, str)
                                               or not ATTACK_TYPE_RE.fullmatch(attack)):
                        errors.append(f"{where}: attack_type must be A01-A16 or null; "
                                      f"got {attack!r}")
                if "artifacts" in case:
                    artifacts = case["artifacts"]
                    if not isinstance(artifacts, list) or not artifacts:
                        errors.append(f"{where}: artifacts must be a non-empty array")
                    else:
                        seen_artifacts: set[str] = set()
                        for artifact in artifacts:
                            reason = is_safe_artifact_path(artifact)
                            if reason:
                                errors.append(f"{where}: unsafe artifact path: {reason}")
                            elif artifact in seen_artifacts:
                                errors.append(f"{where}: duplicate artifact path: {artifact}")
                            else:
                                seen_artifacts.add(artifact)
                if "ground_truth" in case:
                    gt = case["ground_truth"]
                    if not isinstance(gt, dict):
                        errors.append(f"{where}: ground_truth must be an object "
                                      f"(got {_type_name(gt)})")
                    else:
                        for key in GT_REQUIRED:
                            if key not in gt:
                                errors.append(f"{where}: ground_truth missing: {key}")
                        for key in gt:
                            if key not in GT_ALLOWED:
                                errors.append(f"{where}: ground_truth unknown property: {key}")
                        if "vendor_id" in gt and (not isinstance(gt["vendor_id"], str)
                                                  or not gt["vendor_id"]):
                            errors.append(f"{where}: ground_truth.vendor_id must be non-empty")
                        if "invoice_total" in gt and (
                                isinstance(gt["invoice_total"], bool)
                                or not isinstance(gt["invoice_total"], (int, float))):
                            errors.append(f"{where}: ground_truth.invoice_total must be a number")
                        if "currency" in gt and (not isinstance(gt["currency"], str)
                                                 or not CURRENCY_RE.fullmatch(gt["currency"])):
                            errors.append(f"{where}: ground_truth.currency must match ^[A-Z]{{3}}$")
                        if "due_date" in gt and (not isinstance(gt["due_date"], str)
                                                 or not DATE_RE.fullmatch(gt["due_date"])):
                            errors.append(f"{where}: ground_truth.due_date must match YYYY-MM-DD")
                        if "line_item_count" in gt and (
                                isinstance(gt["line_item_count"], bool)
                                or not isinstance(gt["line_item_count"], int)
                                or gt["line_item_count"] < 0):
                            errors.append(f"{where}: ground_truth.line_item_count must be int >= 0")
                if "expected_verdict" in case and case["expected_verdict"] not in VERDICTS:
                    errors.append(f"{where}: expected_verdict must be one of {list(VERDICTS)}; "
                                  f"got {case['expected_verdict']!r}")
                if "notes" in case and not isinstance(case["notes"], str):
                    errors.append(f"{where}: notes must be a string")

    if sha_is_hex and isinstance(cases, list) and cases:
        expected = canonical_hash(cases)
        if sha_value != expected:
            errors.append("sha256 mismatch: the recorded digest does not match the "
                          f"canonical hash over cases (recorded {sha_value}, computed "
                          f"{expected}; see eval/README.md)")

    return errors, warnings


def validate_file(path: str) -> tuple[Optional[list[str]], Optional[list[str]], Optional[str]]:
    """Load + validate. Returns (errors, warnings, fatal) where fatal is a load error."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, None, f"file not found: {path}"
    except UnicodeDecodeError as exc:
        return None, None, f"invalid UTF-8 in {path}: {exc}"
    except json.JSONDecodeError as exc:
        return None, None, f"malformed JSON in {path}: {exc}"
    except OSError as exc:
        return None, None, f"cannot read {path}: {exc}"
    errors, warnings = validate_manifest(data)
    return errors, warnings, None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an Airlock benchmark manifest.")
    parser.add_argument("manifest", help="Path to the manifest JSON file.")
    args = parser.parse_args(argv)

    errors, warnings, fatal = validate_file(args.manifest)
    if fatal:
        print(f"INVALID: {fatal}")
        return 1
    assert errors is not None and warnings is not None
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        print(f"INVALID: {args.manifest} ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    case_count = 0
    try:
        with open(args.manifest, encoding="utf-8") as fh:
            loaded = json.load(fh)
            case_count = len(loaded.get("cases", [])) if isinstance(loaded, dict) else 0
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    print(f"VALID: {args.manifest} ({case_count} case(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

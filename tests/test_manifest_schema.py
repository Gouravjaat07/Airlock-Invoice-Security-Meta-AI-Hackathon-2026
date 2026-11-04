"""Tests for scripts/validate_manifest.py and the eval contract (schema v2.0.0).

Canonical field is `attack_type` (see docs/phase1/MANIFEST_MIGRATION_v2.md).
The legacy v1 name `attack_id` must be rejected, never silently accepted.
"""

import hashlib
import json
from pathlib import Path

import validate_manifest as vm

ROOT = Path(__file__).resolve().parent.parent


def valid_case(case_id="DEV-001", variant="clean", attack_type=None,
               verdict="ALLOW_PROPOSAL", artifacts=None):
    return {
        "case_id": case_id,
        "base_doc_id": "SYN-INV-0001",
        "variant": variant,
        "attack_type": attack_type,
        "artifacts": artifacts if artifacts is not None else ["cases/SYN-INV-0001/invoice.pdf"],
        "ground_truth": {"vendor_id": "V-1", "invoice_total": 10.0, "currency": "USD"},
        "expected_verdict": verdict,
    }


def valid_manifest():
    cases = [valid_case()]
    return {
        "manifest_version": "2.0.0",
        "seed": 7,
        "split": "dev",
        "generator_commit": "abc123",
        "sha256": vm.canonical_hash(cases),
        "cases": cases,
    }


def with_fresh_hash(manifest):
    manifest["sha256"] = vm.canonical_hash(manifest["cases"])
    return manifest


def test_valid_synthetic_manifest_passes():
    errors, warnings = vm.validate_manifest(valid_manifest())
    assert errors == []
    assert warnings == []


def test_template_file_validates_with_placeholder_warning():
    errors, warnings, fatal = vm.validate_file(str(ROOT / "eval" / "manifest.dev.template.json"))
    assert fatal is None
    assert errors == []
    assert any("placeholder" in w for w in warnings)


def test_missing_required_property_fails():
    for key in ("manifest_version", "seed", "split", "generator_commit", "cases", "sha256"):
        manifest = valid_manifest()
        del manifest[key]
        errors, _ = vm.validate_manifest(manifest)
        assert any(key in e for e in errors), key


def test_invalid_split_fails():
    manifest = valid_manifest()
    manifest["split"] = "prod"
    errors, _ = vm.validate_manifest(manifest)
    assert any("split" in e for e in errors)


def test_invalid_variant_fails():
    manifest = with_fresh_hash(valid_manifest())
    manifest["cases"] = [valid_case(variant="sneaky")]
    manifest = with_fresh_hash(manifest)
    errors, _ = vm.validate_manifest(manifest)
    assert any("variant" in e for e in errors)


def test_invalid_attack_type_fails():
    for bad in ("A00", "A17", "B01", "A1", ""):
        manifest = valid_manifest()
        manifest["cases"] = [valid_case(variant="attack", attack_type=bad, verdict="DENY")]
        manifest = with_fresh_hash(manifest)
        errors, _ = vm.validate_manifest(manifest)
        assert any("attack_type" in e for e in errors), bad


def test_attack_type_boundaries_pass():
    for good in ("A01", "A09", "A10", "A16", None):
        manifest = valid_manifest()
        manifest["cases"] = [valid_case(variant="attack", attack_type=good, verdict="DENY")]
        manifest = with_fresh_hash(manifest)
        errors, _ = vm.validate_manifest(manifest)
        assert errors == [], good


def test_legacy_attack_id_field_rejected():
    """Regression (v1 -> v2 migration): the old field name must fail."""
    manifest = valid_manifest()
    case = manifest["cases"][0]
    del case["attack_type"]
    case["attack_id"] = "A01"
    manifest = with_fresh_hash(manifest)
    errors, _ = vm.validate_manifest(manifest)
    assert any("attack_id" in e and "unknown property" in e for e in errors)


def test_invalid_verdict_fails():
    manifest = valid_manifest()
    manifest["cases"] = [valid_case(verdict="MAYBE")]
    manifest = with_fresh_hash(manifest)
    errors, _ = vm.validate_manifest(manifest)
    assert any("expected_verdict" in e for e in errors)


def test_duplicate_case_ids_fail():
    manifest = valid_manifest()
    manifest["cases"] = [valid_case("DUP-1"), valid_case("DUP-1")]
    manifest = with_fresh_hash(manifest)
    errors, _ = vm.validate_manifest(manifest)
    assert any("duplicate case_id" in e for e in errors)


def test_duplicate_artifacts_rejected():
    manifest = valid_manifest()
    manifest["cases"] = [valid_case(artifacts=["cases/a/x.pdf", "cases/a/x.pdf"])]
    manifest = with_fresh_hash(manifest)
    errors, _ = vm.validate_manifest(manifest)
    assert any("duplicate artifact" in e for e in errors)


def test_malformed_json_fails(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    errors, warnings, fatal = vm.validate_file(str(bad))
    assert fatal is not None and "malformed" in fatal.lower()
    assert errors is None


def test_invalid_utf8_file_is_fatal_not_crash(tmp_path):
    bad = tmp_path / "latin1.json"
    bad.write_bytes(b'{"manifest_version": "caf\xe9"}')
    errors, warnings, fatal = vm.validate_file(str(bad))
    assert fatal is not None and "utf-8" in fatal.lower().replace("_", "-")
    assert errors is None
    assert vm.main([str(bad)]) == 1


def test_absent_file_is_not_success(tmp_path):
    errors, warnings, fatal = vm.validate_file(str(tmp_path / "missing.json"))
    assert fatal is not None
    assert errors is None
    assert vm.main([str(tmp_path / "missing.json")]) == 1


def test_unsafe_artifact_references_fail():
    for bad in ("../escape.pdf", "/abs/path.pdf", "C:/win.pdf", "D:\\abs\\x.pdf",
                "a\\b.pdf", "https://example.com/x.pdf", "cases//dup.pdf",
                "cases/./x.pdf", "", "cases/\x00x.pdf", "cases/%2e%2e/escape.pdf",
                "cases/%2Fescape.pdf", "cases/%5cwin.pdf", "cases/%00x.pdf",
                "\\\\server\\share\\x.pdf", "C:x.pdf"):
        manifest = valid_manifest()
        manifest["cases"] = [valid_case(artifacts=[bad])]
        manifest = with_fresh_hash(manifest)
        errors, _ = vm.validate_manifest(manifest)
        assert any("artifact" in e for e in errors), bad


def test_unc_path_rejected_with_unc_reason():
    reason = vm.is_safe_artifact_path("\\\\server\\share\\x.pdf")
    assert reason is not None and "UNC" in reason


def test_safe_artifact_paths_pass():
    for good in ("cases/SYN-INV-0001/invoice.pdf", "x.pdf",
                 "a/b/c-d_e.1.pdf", "cases/100%/x.pdf"):
        assert vm.is_safe_artifact_path(good) is None, good


def test_unknown_properties_fail():
    manifest = valid_manifest()
    manifest["surprise"] = 1
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"][0]["surprise"] = 1
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"][0]["ground_truth"]["surprise"] = 1
    assert vm.validate_manifest(manifest)[0]


def test_ground_truth_field_types():
    manifest = valid_manifest()
    manifest["cases"][0]["ground_truth"]["currency"] = "usd"
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"][0]["ground_truth"]["invoice_total"] = "ten"
    assert vm.validate_manifest(manifest)[0]


def test_root_and_cases_shapes_rejected():
    assert vm.validate_manifest([])[0]
    assert vm.validate_manifest("nope")[0]
    manifest = valid_manifest()
    manifest["cases"] = []
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"] = "nope"
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"] = ["nope"]
    assert vm.validate_manifest(manifest)[0]


def test_validator_never_modifies_manifest(tmp_path):
    path = tmp_path / "m.json"
    manifest = valid_manifest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert vm.main([str(path)]) == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_main_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(valid_manifest()), encoding="utf-8")
    assert vm.main([str(good)]) == 0
    bad_manifest = valid_manifest()
    bad_manifest["split"] = "nope"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_manifest), encoding="utf-8")
    assert vm.main([str(bad)]) == 1


def test_schema_file_declares_draft_2020_12():
    schema = json.loads((ROOT / "eval" / "manifest.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("draft/2020-12/schema")
    assert schema["additionalProperties"] is False
    case_props = schema["$defs"]["case"]["properties"]
    assert "attack_type" in case_props
    assert "attack_id" not in case_props


def test_validator_schema_pattern_parity():
    """The stdlib validator must mirror the JSON Schema patterns/enums/requireds."""
    schema = json.loads((ROOT / "eval" / "manifest.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert schema["required"] == list(vm.TOP_REQUIRED)
    assert props["manifest_version"]["pattern"].strip("^$") == vm.SEMVER_RE.pattern
    assert props["split"]["enum"] == list(vm.SPLITS)
    case = schema["$defs"]["case"]
    assert case["required"] == list(vm.CASE_REQUIRED)
    assert case["properties"]["case_id"]["pattern"].strip("^$") == vm.CASE_ID_RE.pattern
    assert case["properties"]["variant"]["enum"] == list(vm.VARIANTS)
    assert case["properties"]["attack_type"]["pattern"].strip("^$") == vm.ATTACK_TYPE_RE.pattern
    assert case["properties"]["expected_verdict"]["enum"] == list(vm.VERDICTS)
    gt = case["properties"]["ground_truth"]["properties"]
    assert gt["currency"]["pattern"].strip("^$") == vm.CURRENCY_RE.pattern
    assert gt["due_date"]["pattern"].strip("^$") == vm.DATE_RE.pattern


def test_trailing_newline_values_rejected():
    """ECMA `$` (schema) and `fullmatch` (validator) both reject trailing newlines."""
    manifest = valid_manifest()
    manifest["manifest_version"] = "2.0.0\n"
    assert vm.validate_manifest(manifest)[0]
    manifest = valid_manifest()
    manifest["cases"][0]["ground_truth"]["currency"] = "USD\n"
    manifest = with_fresh_hash(manifest)
    assert vm.validate_manifest(manifest)[0]


def test_hash_mismatch_rejected():
    manifest = valid_manifest()
    manifest["cases"][0]["ground_truth"]["invoice_total"] = 999.99
    errors, _ = vm.validate_manifest(manifest)
    assert any("mismatch" in e for e in errors)


def test_malformed_hash_rejected():
    for bad in ("not-hex", "0" * 63, "0" * 65, "zz" * 32, ""):
        manifest = valid_manifest()
        manifest["sha256"] = bad
        errors, _ = vm.validate_manifest(manifest)
        assert any("sha256" in e for e in errors), bad


def test_whitespace_variants_share_canonical_hash():
    compact = '{"cases": [{"b": 2, "a": 1}]}'
    pretty = '{\n  "cases": [\n    {"a": 1, "b": 2}\n  ]\n}\n'
    first = vm.canonical_hash(json.loads(compact)["cases"])
    second = vm.canonical_hash(json.loads(pretty)["cases"])
    assert first == second
    # Independent pin: hand-derived canonical bytes for this payload.
    assert first == hashlib.sha256(b'[{"a":1,"b":2}]').hexdigest()


def test_canonical_hash_uses_documented_formula():
    cases = valid_manifest()["cases"]
    expected = hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")).hexdigest()
    assert vm.canonical_hash(cases) == expected


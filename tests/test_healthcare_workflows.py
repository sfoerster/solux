"""Tests for healthcare workflow YAMLs — schema, prompts, and meta blocks."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HEALTHCARE_DIR = ROOT / "docs" / "examples" / "workflows" / "healthcare"

EXPECTED_WORKFLOWS = {
    "clinical_doc_triage",
    "clinical_doc_summary",
    "claims_classification",
}

EXPECTED_META = {
    "clinical_doc_triage": {"manual_estimate_minutes": 45},
    "clinical_doc_summary": {"manual_estimate_minutes": 30},
    "claims_classification": {"manual_estimate_minutes": 20},
}


def _load_yaml(name: str) -> dict:
    path = HEALTHCARE_DIR / f"{name}.yaml"
    assert path.exists(), f"{name}.yaml not found in {HEALTHCARE_DIR}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── File presence ─────────────────────────────────────────────────────


class TestHealthcareWorkflowFiles:
    def test_all_expected_files_exist(self) -> None:
        for name in EXPECTED_WORKFLOWS:
            path = HEALTHCARE_DIR / f"{name}.yaml"
            assert path.exists(), f"Missing: {path}"

    def test_all_files_are_valid_yaml(self) -> None:
        for path in HEALTHCARE_DIR.glob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"{path.name} is not a YAML mapping"
            assert "name" in data, f"{path.name} missing 'name' key"
            assert "steps" in data, f"{path.name} missing 'steps' key"

    def test_no_unexpected_files(self) -> None:
        names = {p.stem for p in HEALTHCARE_DIR.glob("*.yaml")}
        assert names == EXPECTED_WORKFLOWS, f"Unexpected workflow files: {names - EXPECTED_WORKFLOWS}"


# ── Meta blocks (P3) ─────────────────────────────────────────────────


class TestMetaBlocks:
    def test_all_workflows_have_meta(self) -> None:
        for name in EXPECTED_WORKFLOWS:
            data = _load_yaml(name)
            assert "meta" in data, f"{name} missing meta block"
            assert isinstance(data["meta"], dict), f"{name} meta should be a dict"

    def test_meta_has_manual_estimate_minutes(self) -> None:
        for name in EXPECTED_WORKFLOWS:
            data = _load_yaml(name)
            meta = data["meta"]
            assert "manual_estimate_minutes" in meta, f"{name} meta missing manual_estimate_minutes"
            assert isinstance(meta["manual_estimate_minutes"], int), f"{name} manual_estimate_minutes should be int"
            assert meta["manual_estimate_minutes"] > 0, f"{name} manual_estimate_minutes should be positive"

    def test_meta_has_manual_estimate_label(self) -> None:
        for name in EXPECTED_WORKFLOWS:
            data = _load_yaml(name)
            meta = data["meta"]
            assert "manual_estimate_label" in meta, f"{name} meta missing manual_estimate_label"
            assert isinstance(meta["manual_estimate_label"], str)
            assert len(meta["manual_estimate_label"]) > 5

    def test_meta_values_match_expected(self) -> None:
        for name, expected in EXPECTED_META.items():
            data = _load_yaml(name)
            for key, value in expected.items():
                assert data["meta"][key] == value, f"{name} meta.{key} expected {value}, got {data['meta'][key]}"


# ── Clinical Doc Triage prompts ──────────────────────────────────────


class TestClinicalDocTriagePrompts:
    def setup_method(self) -> None:
        self.data = _load_yaml("clinical_doc_triage")
        self.steps = {s["name"]: s for s in self.data["steps"]}

    def test_has_expected_steps(self) -> None:
        expected = {
            "ingest_document",
            "clean_text",
            "classify_doc_type",
            "classify_urgency",
            "summarize",
            "extract_entities",
            "write_summary",
        }
        assert set(self.steps.keys()) == expected

    def test_classify_doc_type_has_him_context(self) -> None:
        prompt = self.steps["classify_doc_type"]["config"]["system_prompt"]
        assert "HIM" in prompt or "Health Information Management" in prompt

    def test_classify_doc_type_returns_only_label(self) -> None:
        prompt = self.steps["classify_doc_type"]["config"]["system_prompt"]
        assert "ONLY" in prompt.upper()

    def test_classify_urgency_has_explicit_criteria(self) -> None:
        prompt = self.steps["classify_urgency"]["config"]["system_prompt"]
        # Should mention specific clinical criteria
        assert "K+" in prompt or "potassium" in prompt.lower()
        assert "hemoglobin" in prompt.lower() or "Hgb" in prompt
        assert "24" in prompt  # 24-48 hours for urgent

    def test_classify_urgency_has_all_four_levels(self) -> None:
        prompt = self.steps["classify_urgency"]["config"]["system_prompt"]
        for level in ["CRITICAL", "URGENT", "ROUTINE", "INFORMATIONAL"]:
            assert level in prompt.upper()

    def test_summarize_has_structured_format(self) -> None:
        prompt = self.steps["summarize"]["config"]["system_prompt"]
        assert "ASSESSMENT" in prompt
        assert "KEY FINDINGS" in prompt
        assert "MEDICATIONS" in prompt
        assert "FOLLOW-UP" in prompt

    def test_summarize_has_word_cap(self) -> None:
        prompt = self.steps["summarize"]["config"]["system_prompt"]
        assert "150" in prompt

    def test_extract_entities_has_strict_json_schema(self) -> None:
        prompt = self.steps["extract_entities"]["config"]["prompt_template"]
        assert "diagnoses" in prompt
        assert "icd10" in prompt
        assert "medications" in prompt
        assert "dosage" in prompt
        assert "frequency" in prompt
        assert "phi_detected" in prompt

    def test_extract_entities_no_markdown_instruction(self) -> None:
        prompt = self.steps["extract_entities"]["config"]["prompt_template"]
        assert "no markdown" in prompt.lower() or "no code fences" in prompt.lower()

    def test_categories_include_all_doc_types(self) -> None:
        cats = self.steps["classify_doc_type"]["config"]["categories"]
        expected = {
            "discharge_summary",
            "radiology_report",
            "lab_result",
            "progress_note",
            "referral_letter",
            "prescription",
        }
        assert set(cats) == expected


# ── Clinical Doc Summary prompts ─────────────────────────────────────


class TestClinicalDocSummaryPrompts:
    def setup_method(self) -> None:
        self.data = _load_yaml("clinical_doc_summary")
        self.steps = {s["name"]: s for s in self.data["steps"]}

    def test_has_structured_summary_prompt(self) -> None:
        prompt = self.steps["summarize"]["config"]["system_prompt"]
        assert "ASSESSMENT" in prompt
        assert "KEY FINDINGS" in prompt

    def test_extract_entities_includes_vitals(self) -> None:
        prompt = self.steps["extract_entities"]["config"]["prompt_template"]
        assert "vitals" in prompt

    def test_extract_entities_has_phi_detected(self) -> None:
        prompt = self.steps["extract_entities"]["config"]["prompt_template"]
        assert "phi_detected" in prompt

    def test_classifier_has_him_context(self) -> None:
        prompt = self.steps["classify_document"]["config"]["system_prompt"]
        assert "HIM" in prompt or "Health Information Management" in prompt


# ── Claims Classification prompts ────────────────────────────────────


class TestClaimsClassificationPrompts:
    def setup_method(self) -> None:
        self.data = _load_yaml("claims_classification")
        self.steps = {s["name"]: s for s in self.data["steps"]}

    def test_classify_claim_has_adjudication_criteria(self) -> None:
        prompt = self.steps["classify_claim"]["config"]["system_prompt"]
        for keyword in ["APPROVED", "DENIED", "PENDING_REVIEW", "NEEDS_ADDITIONAL_INFO"]:
            assert keyword in prompt.upper()

    def test_classify_claim_mentions_medical_necessity(self) -> None:
        prompt = self.steps["classify_claim"]["config"]["system_prompt"]
        assert "medical necessity" in prompt.lower()

    def test_classify_claim_mentions_prior_authorization(self) -> None:
        prompt = self.steps["classify_claim"]["config"]["system_prompt"]
        assert "prior authorization" in prompt.lower()

    def test_categories_match_expected(self) -> None:
        cats = self.steps["classify_claim"]["config"]["categories"]
        expected = {"approved", "denied", "pending_review", "needs_additional_info"}
        assert set(cats) == expected

"""Tests for demo clinical document files and PDF generation script."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # vinsium root
DEMO_DIR = ROOT / "docs" / "demo"
SCRIPTS_DIR = ROOT / "scripts"

EXPECTED_TXT_FILES = {
    "sample_discharge_summary",
    "sample_radiology_report",
    "sample_lab_result_critical",
    "sample_lab_result_routine",
    "sample_progress_note",
    "sample_referral_letter",
    "sample_prescription",
    "sample_radiology_mri",
    "sample_discharge_cardiac",
    "sample_er_visit_note",
}


class TestDemoTextFiles:
    def test_all_expected_files_exist(self) -> None:
        for name in EXPECTED_TXT_FILES:
            path = DEMO_DIR / f"{name}.txt"
            assert path.exists(), f"Missing demo file: {path}"

    def test_all_files_are_non_empty(self) -> None:
        for name in EXPECTED_TXT_FILES:
            path = DEMO_DIR / f"{name}.txt"
            content = path.read_text(encoding="utf-8")
            assert len(content) > 100, f"{name}.txt is too short ({len(content)} chars)"

    def test_all_files_have_disclaimer(self) -> None:
        for name in EXPECTED_TXT_FILES:
            path = DEMO_DIR / f"{name}.txt"
            content = path.read_text(encoding="utf-8")
            assert "SYNTHETIC" in content or "DEMO DATA" in content, f"{name}.txt missing synthetic data disclaimer"

    def test_all_files_have_redacted_identifiers(self) -> None:
        for name in EXPECTED_TXT_FILES:
            path = DEMO_DIR / f"{name}.txt"
            content = path.read_text(encoding="utf-8")
            assert "REDACTED" in content or "DEMO-" in content, f"{name}.txt missing redacted identifiers"

    def test_no_real_patient_data(self) -> None:
        """Verify demo files contain only synthetic data markers."""
        for name in EXPECTED_TXT_FILES:
            path = DEMO_DIR / f"{name}.txt"
            content = path.read_text(encoding="utf-8")
            assert "NOT A REAL PATIENT" in content, f"{name}.txt missing 'NOT A REAL PATIENT' disclaimer"

    def test_critical_lab_has_critical_values(self) -> None:
        content = (DEMO_DIR / "sample_lab_result_critical.txt").read_text()
        assert "6.8" in content  # K+ critical value
        assert "6.2" in content  # Hgb critical value
        assert "CRITICAL" in content

    def test_routine_lab_has_normal_values(self) -> None:
        content = (DEMO_DIR / "sample_lab_result_routine.txt").read_text()
        assert "NORMAL" in content

    def test_radiology_mri_has_suspicious_mass(self) -> None:
        content = (DEMO_DIR / "sample_radiology_mri.txt").read_text()
        assert "mass" in content.lower() or "carcinoma" in content.lower()

    def test_discharge_cardiac_has_nstemi(self) -> None:
        content = (DEMO_DIR / "sample_discharge_cardiac.txt").read_text()
        assert "NSTEMI" in content or "myocardial infarction" in content.lower()

    def test_referral_has_urgency(self) -> None:
        content = (DEMO_DIR / "sample_referral_letter.txt").read_text()
        assert "urgent" in content.lower() or "Urgent" in content

    def test_er_visit_is_informational(self) -> None:
        """ER visit for ankle sprain should be minor/informational."""
        content = (DEMO_DIR / "sample_er_visit_note.txt").read_text()
        assert "sprain" in content.lower()
        assert "ESI Level 4" in content or "Less Urgent" in content

    def test_file_count_matches_expected(self) -> None:
        txt_files = list(DEMO_DIR.glob("*.txt"))
        assert len(txt_files) == len(EXPECTED_TXT_FILES), (
            f"Expected {len(EXPECTED_TXT_FILES)} txt files, found {len(txt_files)}"
        )


class TestGenerateDemoPdfsScript:
    def test_script_exists(self) -> None:
        path = SCRIPTS_DIR / "generate-demo-pdfs.py"
        assert path.exists()

    def test_script_syntax_valid(self) -> None:
        path = SCRIPTS_DIR / "generate-demo-pdfs.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)

    def test_script_lists_all_txt_files(self) -> None:
        """FILES list in the script should reference all expected demo txt files."""
        path = SCRIPTS_DIR / "generate-demo-pdfs.py"
        source = path.read_text(encoding="utf-8")
        for name in EXPECTED_TXT_FILES:
            assert f"{name}.txt" in source, f"generate-demo-pdfs.py missing {name}.txt"

    def test_script_maps_txt_to_pdf(self) -> None:
        """Each txt entry should have a corresponding pdf output."""
        path = SCRIPTS_DIR / "generate-demo-pdfs.py"
        source = path.read_text(encoding="utf-8")
        for name in EXPECTED_TXT_FILES:
            assert f"{name}.pdf" in source, f"generate-demo-pdfs.py missing {name}.pdf"


class TestDemoBatchScript:
    def test_script_exists(self) -> None:
        path = SCRIPTS_DIR / "demo-batch.sh"
        assert path.exists()

    def test_script_is_executable(self) -> None:
        import os

        path = SCRIPTS_DIR / "demo-batch.sh"
        assert os.access(path, os.X_OK), "demo-batch.sh should be executable"

    def test_script_has_shebang(self) -> None:
        path = SCRIPTS_DIR / "demo-batch.sh"
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!/"), "demo-batch.sh missing shebang"

    def test_script_references_clinical_doc_triage(self) -> None:
        path = SCRIPTS_DIR / "demo-batch.sh"
        content = path.read_text(encoding="utf-8")
        assert "clinical_doc_triage" in content

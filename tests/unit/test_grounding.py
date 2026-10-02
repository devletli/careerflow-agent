"""T3 grounding-validator tests (offline, deterministic).

Fake LLM output containing unprofiled skills/metrics must produce
violations; profile-faithful rephrasing must pass. No MinIO, no LLM.
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("docx")

from shared.profile.grounding import Violation, extract_numbers, validate_grounding  # noqa: E402

PROFILE = {
    "name": "Test Candidate",
    "experience_years": 8,
    "languages": {"German": "B2", "English": "C1"},
    "education": [{"degree": "Computer Science", "institution": "Example University"}],
    "certifications": [],
    "skills": ["Python", "Docker", "Git", "CI/CD"],
}


def test_extract_numbers():
    assert "15" in extract_numbers("15 years of experience")
    assert "40%" in extract_numbers("40% faster deployments")


def test_unprofiled_skill_is_violation():
    violations = validate_grounding(
        "Expert in Kubernetes with 8 years of experience.", PROFILE
    )
    assert any(v.kind == "skill" and v.claim == "kubernetes" for v in violations)


def test_unprofiled_metric_is_violation():
    violations = validate_grounding(
        "Delivered 40% faster deployments with Python.", PROFILE
    )
    assert any(v.kind == "metric" and "40%" in v.claim for v in violations)


def test_profile_numbers_do_not_violate():
    violations = validate_grounding(
        "Python developer with 8 years of professional experience.", PROFILE
    )
    assert violations == []


def test_profile_faithful_rephrase_passes():
    text = (
        "Test Candidate: Python developer with 8 years of professional "
        "experience. Verified skills: Python, Docker, Git, CI/CD. "
        "Education: Computer Science, Example University. "
        "Languages: German (B2), English (C1)."
    )
    assert validate_grounding(text, PROFILE) == []


def test_fabricated_degree_is_violation():
    violations = validate_grounding(
        "Test Candidate holds a PhD in Physics and knows Python.", PROFILE
    )
    assert any(v.kind == "degree" for v in violations)


def test_fabricated_employer_is_violation():
    violations = validate_grounding(
        "Previously employed at FictionalCorp GmbH as Python developer.", PROFILE
    )
    assert any(v.kind == "employer" for v in violations)


def test_fabricated_employment_dates_are_violations():
    violations = validate_grounding(
        "Worked 2019-2022 as Python developer with 8 years of experience.", PROFILE
    )
    assert any(v.kind == "date" for v in violations)


def test_allowlisted_company_and_title_pass():
    text = "Application: DevOps Engineer - Acme GmbH. Python developer."
    violations = validate_grounding(text, PROFILE, allow=["Acme GmbH", "DevOps Engineer"])
    assert violations == []


def test_multiline_company_name_is_allowlisted():
    # PDF extraction inserts line breaks mid-name; allowlist still applies.
    text = "Application: Developer - Omilia Natural Language\nSolutions Ua Ltd."
    violations = validate_grounding(
        text, PROFILE, allow=["Omilia Natural Language Solutions Ua Ltd", "Developer"]
    )
    assert violations == []


def test_violation_shape():
    violation = Violation("skill", "kubernetes")
    assert violation.kind == "skill" and violation.claim == "kubernetes"


def test_production_templates_pass_the_gate():
    """Real template output must never be blocked (fail-closed safety)."""
    from shared.profile.loader import CanonicalProfile

    root = Path(__file__).resolve().parents[2]
    path = root / "services" / "cv-generator" / "app" / "generator.py"
    spec = importlib.util.spec_from_file_location("careerflow_docgen_gate", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_docgen_gate"] = module
    spec.loader.exec_module(module)

    profile = CanonicalProfile(
        facts={
            "name": "Gate Candidate",
            "email": "gate@example.com",
            "experience_years": 8,
            "languages": {"German": "B2"},
            "location": {"city": "Berlin", "country": "Germany"},
            "education": [{"degree": "Computer Science", "institution": "Example University"}],
            "certifications": ["ISTQB Certified Tester"],
            "skills": ["Python", "Docker", "Git"],
        },
        preferences={},
    )
    gen = module.DocumentGenerator.__new__(module.DocumentGenerator)
    tailoring = {"skills": ["Python", "Docker"], "keywords": ["AI"], "target_role": "DevOps Engineer"}
    built = [
        ("cv.pdf", gen._build_pdf_cv(profile, "Acme GmbH", "DevOps Engineer", "en", tailoring)),
        ("cv.docx", gen._build_docx_cv(profile, "Acme GmbH", "DevOps Engineer", "en", tailoring)),
        ("cl.pdf", gen._build_pdf_cover_letter(profile, "Acme GmbH", "DevOps Engineer", "en", tailoring)),
    ]
    allow = ["Acme GmbH", "DevOps Engineer",
             date.today().strftime("%B %d, %Y"), date.today().strftime("%d.%m.%Y")]
    for filename, content in built:
        text = module.DocumentGenerator._extract_text(filename, content)
        assert text, f"no extractable text in {filename}"
        assert validate_grounding(text, profile.facts, allow=allow) == [], filename

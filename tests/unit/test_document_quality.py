"""Document generation quality regression tests (offline).

Renders the production templates (services/cv-generator/app/generator.py)
with a synthetic profile and asserts portfolio/demo quality properties:
- CV and cover letter are non-empty, structured, professional artifacts;
- contact lines contain only verified non-empty facts (no "|  |" gaps,
  no placeholder phone);
- cover letter names the company/role plus concrete role-relevant skills
  (not generic filler);
- no non-WinAnsi risky characters (em dash) that render as boxes;
- DOCX output is a valid document containing the candidate name.
"""
import importlib.util
import io
import sys
from pathlib import Path

import pytest

reportlab = importlib.util.find_spec("reportlab")
docx_spec = importlib.util.find_spec("docx")
pytestmark = pytest.mark.skipif(
    reportlab is None or docx_spec is None, reason="reportlab/python-docx not installed"
)

ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    path = ROOT / "services" / "cv-generator" / "app" / "generator.py"
    spec = importlib.util.spec_from_file_location("careerflow_doc_generator", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_doc_generator"] = module
    spec.loader.exec_module(module)
    return module


_gen = _load_generator()

from shared.profile.loader import CanonicalProfile  # noqa: E402


def _profile(**overrides):
    facts = {
        "candidate_id": "doc-candidate",
        "name": "Doc Candidate",
        "email": "doc@example.com",
        "phone": "+49 170 1111111",
        "website": "https://example.com",
        "experience_years": 15,
        "languages": {"German": "C1", "English": "C1"},
        "location": {"city": "Berlin", "country": "Germany"},
        "education": [{"degree": "Computer Engineering", "institution": "Eval University"}],
        "certifications": ["ISTQB Certified Tester"],
        "skills": ["Python", "Kubernetes", "Docker", "Terraform", "Jenkins", "Git"],
    }
    facts.update(overrides)
    return CanonicalProfile(
        facts=facts,
        preferences={"preferred_roles": ["DevOps Engineer"], "locations": ["Berlin"]},
    )


def _tailoring():
    return {"skills": ["Python", "Kubernetes", "Docker"], "keywords": ["AI", "Automation"], "target_role": "DevOps Engineer"}


def _pdf_text(data: bytes) -> str:
    from PyPDF2 import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def _generator():
    return _gen.DocumentGenerator.__new__(_gen.DocumentGenerator)  # skip MinIO init


def test_pdf_cv_is_structured_and_factual():
    text = _pdf_text(_generator()._build_pdf_cv(_profile(), "Acme GmbH", "DevOps Engineer", "en", _tailoring()))
    for section in ["Profile Summary", "Role-Relevant Verified Skills", "Education", "Languages"]:
        assert section in text, f"CV missing section: {section}"
    assert "Doc Candidate" in text
    assert "doc@example.com" in text and "+49 170 1111111" in text
    assert "15 years of professional experience" in text
    assert "Python" in text and "Acme GmbH" in text and "DevOps Engineer" in text


def test_contact_line_has_no_gaps_or_placeholders():
    bare = _profile(email="", phone=None)
    text = _pdf_text(_generator()._build_pdf_cv(bare, "Acme GmbH", "DevOps Engineer", "en", _tailoring()))
    assert "|  |" not in text and "•  •" not in text.replace("•", "•")
    assert "+49 176 00000000" not in text  # loader dummy phone must never print
    assert "https://example.com" in text and "Berlin" in text


def test_pdf_uses_safe_characters():
    text = _pdf_text(_generator()._build_pdf_cv(_profile(), "Acme GmbH", "DevOps Engineer", "en", _tailoring()))
    assert "—" not in text, "em dash risks WinAnsi rendering gaps; use '-'"
    assert "�" not in text


def test_cover_letter_is_specific_not_generic():
    text = _pdf_text(
        _generator()._build_pdf_cover_letter(_profile(), "Acme GmbH", "DevOps Engineer", "en", _tailoring())
    )
    assert "Dear Hiring Team at Acme GmbH" in text
    assert "DevOps Engineer" in text
    assert "Python" in text  # concrete role-relevant skill, not filler
    assert "Doc Candidate" in text  # signature
    assert "I am excited" not in text
    assert "My profile contains 15 years" not in text  # old generic template retired


def test_docx_cv_is_valid_and_factual():
    from docx import Document
    data = _generator()._build_docx_cv(_profile(), "Acme GmbH", "DevOps Engineer", "en", _tailoring())
    assert len(data) > 10000
    full = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "Doc Candidate" in full
    assert "Profile Summary" in full
    assert "doc@example.com" in full and "+49 170 1111111" in full


def test_german_templates_render():
    gen = _generator()
    for text in [
        _pdf_text(gen._build_pdf_cv(_profile(), "Acme GmbH", "DevOps Engineer", "de", _tailoring())),
        _pdf_text(gen._build_pdf_cover_letter(_profile(), "Acme GmbH", "DevOps Engineer", "de", _tailoring())),
    ]:
        assert "Doc Candidate" in text
        assert "�" not in text

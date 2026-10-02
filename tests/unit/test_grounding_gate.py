"""T3 gate: ungrounded artifacts are never persisted (no local file, no MinIO).

Offline: loads the production DocumentGenerator from file (hyphenated
package path is not importable), bypasses MinIO init, fakes upload +
local disk via tmp_path.
"""
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def _load_generator_module():
    path = ROOT / "services" / "cv-generator" / "app" / "generator.py"
    spec = importlib.util.spec_from_file_location("careerflow_docgen_gate2", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_docgen_gate2"] = module
    spec.loader.exec_module(module)
    return module


def _profile():
    from shared.profile.loader import CanonicalProfile

    return CanonicalProfile(
        facts={
            "name": "Gate Candidate",
            "email": "gate@example.com",
            "experience_years": 8,
            "languages": {"German": "B2"},
            "location": {"city": "Berlin", "country": "Germany"},
            "education": [{"degree": "Computer Science", "institution": "Example University"}],
            "certifications": [],
            "skills": ["Python", "Docker", "Git"],
        },
        preferences={"preferred_roles": ["Backend Engineer"]},
    )


def _generator(module, monkeypatch, tmp_path):
    gen = module.DocumentGenerator.__new__(module.DocumentGenerator)

    class FakeMinIO:
        def __init__(self):
            self.uploads = []

        def upload_bytes(self, content, key, content_type=None):
            self.uploads.append((key, content_type))

    fake = FakeMinIO()
    gen.minio = fake
    monkeypatch.setattr(module, "ARTIFACT_DIRECTORY", tmp_path)
    return gen, fake


def test_violating_artifact_never_persisted(monkeypatch, tmp_path):
    """Injected ungrounded text blocks persistence (fail-closed)."""
    module = _load_generator_module()
    gen, fake = _generator(module, monkeypatch, tmp_path)

    # Force extracted text to contain unprofiled skill + metric.
    monkeypatch.setattr(
        module.DocumentGenerator,
        "_extract_text",
        staticmethod(lambda filename, content: "Expert in Kubernetes, 40% faster. Python."),
    )
    docs, violations = gen.generate_tailored_documents(
        job_id=uuid4(),
        company="Acme GmbH",
        title="Backend Engineer",
        description="Python role",
        matching_skills=["Python"],
        profile=_profile(),
    )
    assert violations, "expected grounding violations"
    assert docs == []
    assert fake.uploads == []
    assert list(tmp_path.rglob("*")) == []


def test_clean_output_persists_idempotently(monkeypatch, tmp_path):
    """Profile-faithful production templates persist; rerun overwrites, no dupes."""
    module = _load_generator_module()
    gen, fake = _generator(module, monkeypatch, tmp_path)
    job_id = uuid4()
    kwargs = dict(
        job_id=job_id,
        company="Acme GmbH",
        title="Backend Engineer",
        description="Python role",
        matching_skills=["Python"],
        profile=_profile(),
    )
    docs1, v1 = gen.generate_tailored_documents(**kwargs)
    assert v1 == []
    assert len(docs1) == 3
    assert len(fake.uploads) == 3

    docs2, v2 = gen.generate_tailored_documents(**kwargs)
    assert v2 == []
    # PDF metadata embeds build timestamps, so bytes/hashes vary per run.
    # Idempotency = same logical keys/paths overwritten, still exactly 3 files.
    assert [d.minio_key for d in docs1] == [d.minio_key for d in docs2]
    assert [d.file_path for d in docs1] == [d.file_path for d in docs2]
    # Same keys overwritten -> no duplicate keys on disk beyond the 3 files.
    assert len(list(tmp_path.rglob("*.pdf"))) + len(list(tmp_path.rglob("*.docx"))) == 3

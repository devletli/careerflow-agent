"""T7 matching golden-set regression (offline, deterministic).

tests/golden/jobs.jsonl pins 25 adverts with their expected
QUALIFIED/REVIEW/NOT_QUALIFIED outcome at a fixed threshold. Any weight
or threshold change that alters pipeline decisions fails here first —
update the golden file deliberately, never to hide a regression.
"""
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "jobs.jsonl"


def _load_matcher():
    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("careerflow_job_matcher_golden", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_job_matcher_golden"] = module
    spec.loader.exec_module(module)
    return module


_matcher = _load_matcher()

from shared.profile.loader import CanonicalProfile  # noqa: E402


def _profile() -> CanonicalProfile:
    return CanonicalProfile(
        facts={
            "candidate_id": "eval-candidate",
            "name": "Eval Candidate",
            "email": "eval@example.com",
            "experience_years": 15,
            "languages": {"German": "C1", "English": "C1", "Turkish": "native"},
            "education": [{"degree": "Computer Engineering"}],
            "skills": [
                "DevOps", "ALM", "Test Automation", "CI/CD", "Jenkins", "Git",
                "Terraform", "Ansible", "Docker", "Kubernetes", "AWS",
                "Microservices", "Jira", "Python", "Linux", "Bash", "REST",
                "API", "Monitoring", "RAG", "LLM", "LangGraph", "MCP",
                "Application Lifecycle Management",
            ],
        },
        preferences={
            "preferred_roles": [
                "DevOps Engineer", "AI Automation Engineer", "ALM Consultant",
                "Test Automation Engineer", "Platform Engineer", "MLOps Engineer",
            ],
            "excluded_roles": ["Junior Developer", "Manual Tester", "Pure Sales", "Pure Customer Support"],
            "locations": ["Berlin", "Brandenburg", "Germany", "Remote"],
            "remote": True,
            "relocation": False,
        },
    )


def _rows():
    with open(GOLDEN, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_golden_row_count():
    rows = _rows()
    assert 20 <= len(rows) <= 30, f"golden set must hold 20-30 adverts, has {len(rows)}"


def test_golden_qualifications_pinned():
    engine = _matcher.JobMatchingEngine()
    profile = _profile()
    failures = []
    for row in _rows():
        result = engine.evaluate_match(
            job_id=uuid4(),
            title=row["title"],
            description=row["description"],
            requirements=row.get("requirements") or [],
            location=row.get("location"),
            remote_status=row.get("remote_status"),
            profile=profile,
            min_threshold=row["threshold"],
        )
        if result.qualification.value != row["expected"]:
            failures.append(
                f"[{row['id']}] got {result.qualification.value} "
                f"(score {result.overall_score}), golden pins {row['expected']}"
            )
    assert not failures, "golden regressions (weight/threshold change?):\n" + "\n".join(failures)

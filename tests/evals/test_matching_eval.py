"""Automated matching evaluation.

Runs the EXISTING production matcher (services/job-matching/app/matcher.py)
over evals/matching_cases.json. No LLM/API access: only the deterministic
evaluate_match() is used (add_llm_explanation is never called).
"""
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def _load_matcher():
    # Loaded under a unique module name: services/job-matching/app and
    # services/application-analyzer/app share the bare `app` package name,
    # so plain sys.path imports collide when both test modules run together.
    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("careerflow_job_matcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_job_matcher"] = module
    spec.loader.exec_module(module)
    return module


_matcher = _load_matcher()
DEFAULT_WEIGHTS = _matcher.DEFAULT_WEIGHTS
JobMatchingEngine = _matcher.JobMatchingEngine

from shared.profile.loader import CanonicalProfile  # noqa: E402

DATASET = Path(__file__).resolve().parents[2] / "evals" / "matching_cases.json"

EXPECTED_COMPONENTS = set(DEFAULT_WEIGHTS)


def _base_profile() -> CanonicalProfile:
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


def _profile_for(case) -> CanonicalProfile:
    base = _base_profile()
    override = (case.get("profile_override") or {}).get("languages")
    if override:
        facts = dict(base.facts)
        facts["languages"] = override
        return CanonicalProfile(facts=facts, preferences=base.preferences)
    return base


def _run_case(engine, case, threshold):
    result = engine.evaluate_match(
        job_id=uuid4(),
        title=case["title"],
        description=case["description"],
        requirements=case.get("requirements") or [],
        location=case.get("location"),
        remote_status=case.get("remote_status"),
        profile=_profile_for(case),
        min_threshold=threshold,
    )
    return result


def test_matching_eval_dataset():
    """Every eval case scores inside its expected range with an expected qualification."""
    with open(DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    threshold = dataset["min_threshold"]
    engine = JobMatchingEngine()
    failures = []

    assert len(dataset["cases"]) >= 20, "eval dataset must hold 20-30 cases"

    for case in dataset["cases"]:
        result = _run_case(engine, case, threshold)
        exp = case["expected"]
        problems = []
        if not (exp["min_score"] <= result.overall_score <= exp["max_score"]):
            problems.append(f"score {result.overall_score} outside [{exp['min_score']}, {exp['max_score']}]")
        if result.qualification.value not in exp["qualifications"]:
            problems.append(
                f"qualification {result.qualification.value} not in {exp['qualifications']}"
            )
        for comp, value in (exp.get("components") or {}).items():
            if result.component_scores.get(comp) != value:
                problems.append(
                    f"component {comp}={result.component_scores.get(comp)} != pinned {value}"
                )
        if len(result.hard_requirements) < exp.get("min_hard_requirements", 0):
            problems.append(f"only {len(result.hard_requirements)} hard requirements detected")
        if set(result.component_scores) != EXPECTED_COMPONENTS:
            problems.append(f"component keys changed: {sorted(result.component_scores)}")
        if result.confidence not in (0.75, 0.94):
            problems.append(f"unexpected confidence {result.confidence}")
        if "Overall Match Score" not in result.explanation:
            problems.append("explanation missing score header")
        if problems:
            failures.append(f"[{case['id']}] ({case['category']}): " + "; ".join(problems))

    assert not failures, "matching eval failures:\n" + "\n".join(failures)


def test_matching_eval_ordering():
    """Relative ordering must hold: strong > medium/partial > weak/unrelated."""
    with open(DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    threshold = dataset["min_threshold"]
    engine = JobMatchingEngine()
    by_id = {c["id"]: c for c in dataset["cases"]}
    scores = {cid: _run_case(engine, by_id[cid], threshold).overall_score for cid in by_id}

    failures = []
    for chain in dataset["ordering"]:
        for higher, lower in zip(chain, chain[1:]):
            if not scores[higher] > scores[lower]:
                failures.append(f"{higher} ({scores[higher]}) not above {lower} ({scores[lower]})")
    assert not failures, "ordering violations:\n" + "\n".join(failures)

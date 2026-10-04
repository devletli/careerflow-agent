"""B5: gercek etiketli kalibrasyon (dosya yoksa acikca atlanir)."""
from pathlib import Path

import pytest

REAL = Path(__file__).resolve().parents[1] / "golden" / "real_labeled.jsonl"


def test_real_calibration_heldout_precision():
    import importlib.util
    import json
    import random
    import sys
    from uuid import uuid4

    if not REAL.exists():
        pytest.skip("real_labeled.jsonl yok: kullanici 20-30 gercek ilani elle etiketlemeli")

    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shared.profile.loader import load_canonical_profile

    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("realcal_matcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["realcal_matcher"] = module
    spec.loader.exec_module(module)

    rows = [json.loads(line) for line in REAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 10, "anlamli kalibrasyon icin en az 10 etiketli ilan gerekli"
    engine = module.JobMatchingEngine()
    profile = load_canonical_profile()
    scored = []
    for row in rows:
        result = engine.evaluate_match(
            job_id=uuid4(),
            title=row.get("title", ""),
            description=row.get("description", ""),
            requirements=row.get("requirements") or [],
            location=row.get("location"),
            remote_status=row.get("remote_status"),
            profile=profile,
            min_threshold=90,
        )
        scored.append((row.get("label", "?"), result.overall_score))
    random.Random(42).shuffle(scored)
    held = scored[int(len(scored) * 0.7):]
    assert held, "held-out bos olmamali"

    def band(score, t):
        return "QUALIFIED" if score >= t else "REVIEW" if score >= t - 10 else "NOT_QUALIFIED"

    qualified = [(label, s) for label, s in held if band(s, 90) == "QUALIFIED"]
    assert qualified, "held-out'ta QUALIFIED tahmini yok; esik/kapi gozden gecirilmeli"
    precision = sum(1 for label, _ in qualified if label == "QUALIFIED") / len(qualified)
    assert precision >= 0.9, f"held-out QUALIFIED precision {precision:.2f} < 0.90"

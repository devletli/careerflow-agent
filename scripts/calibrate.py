"""Gercek etiketli ilanlarla esik kalibrasyonu (B5).

AJAN ilan etiketlemez; etiketleri kullanici verir:
tests/golden/real_labeled.jsonl (sema icin real_labeled.example.jsonl).
Dosya %70 kalibrasyon / %30 held-out ayrilir (sabit seed 42); her esik
icin QUALIFIED precision basilir.

Kullanim:  python scripts/calibrate.py [dosya]   (veya: make calibrate)
"""
import importlib.util
import json
import random
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_matcher():
    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("calibrate_matcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_matcher"] = module
    spec.loader.exec_module(module)
    return module


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def band(score, t):  # QUALIFIED >= t, REVIEW [t-10, t)
    return "QUALIFIED" if score >= t else "REVIEW" if score >= t - 10 else "NOT_QUALIFIED"


def main(path="tests/golden/real_labeled.jsonl"):
    from shared.profile.loader import load_canonical_profile

    if not Path(path).exists():
        print(  # noqa: T201 - CLI
            f"{path} yok: once 20-30 gercek ilani elle etiketleyin "
            "(sema: tests/golden/real_labeled.example.jsonl)"
        )
        return 2
    rows = [r for r in load(path) if r.get("label") in ("QUALIFIED", "REVIEW", "NOT_QUALIFIED")]
    if len(rows) < 15:
        print(  # noqa: T201 - CLI
            f"yetersiz veri ({len(rows)} etiketli, en az 15 gerekli): once real_labeled.jsonl "
            'icindeki "label" alanlarini doldurun'
        )
        return 2
    try:
        profile = load_canonical_profile()
    except Exception as exc:
        print(  # noqa: T201 - CLI
            f"profil yuklenemedi (profile/profile.yaml + preferences.yaml gerekli): {exc}"
        )
        return 2
    print(f"profil: satisfies={profile.satisfies}")  # noqa: T201 - CLI
    engine = _load_matcher().JobMatchingEngine()
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
        scored.append((row.get("id", "?"), row.get("label", "?"), result.overall_score))
    random.Random(42).shuffle(scored)
    cut = int(len(scored) * 0.7)
    subsets = (("cal", scored[:cut]), ("held", scored[cut:]))
    for t in range(70, 96, 5):
        for name, subset in subsets:
            qualified = [(label, s) for _, label, s in subset if band(s, t) == "QUALIFIED"]
            hits = sum(1 for label, _ in qualified if label == "QUALIFIED")
            prec = (hits / len(qualified)) if qualified else float("nan")
            print(f"T={t} {name}: qualified_precision={prec:.2f} n_qualified={len(qualified)}")  # noqa: T201 - CLI raporu
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

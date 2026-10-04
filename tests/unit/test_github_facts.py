"""GOREV 2b: GitHub kaynagi testleri (offline, tum HTTP sahte istemciyle).

Kapsar: fork/arsivli/baskasina-ait repo atlama, metrics'in bos kalmasi,
README'de olmayan teknolojinin skills'e girmemesi, token'in loglara sizmamasi,
evidence birebir tutmazsa onerinin atilmasi, SSRF korumasi, rate limit saygisi,
onay adiminda role sorusu, ai_assisted durustluk kapisi.
"""
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "ghp_sahte_token_12345"


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingest = _load("ingest_facts_under_test", "scripts/ingest_facts.py")
review = _load("review_facts_under_test", "scripts/review_facts.py")

pytest.importorskip("httpx")
import httpx


README = """# demo-proje

Python ile yazilmis kucuk bir API servisi. Docker ile paketlenir.

Kurulum: pip install -r requirements.txt
"""

OTHER_README = "# baska-proje\n\nGo ile yazilmis deneme.\n"


def _readme_payload(text):
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}


def _meta(name="demo-proje", owner="ben", fork=False, archived=False):
    return {
        "name": name,
        "owner": {"login": owner},
        "fork": fork,
        "archived": archived,
        "languages_url": f"https://api.github.com/repos/{owner}/{name}/languages",
        "created_at": "2021-03-01T00:00:00Z",
        "pushed_at": "2024-06-01T00:00:00Z",
        "html_url": f"https://github.com/{owner}/{name}",
        "stargazers_count": 999,
        "watchers_count": 999,
        "forks_count": 999,
        "subscribers_count": 999,
    }


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok_handler(request, meta=None, langs=None, readme_text=README):
    meta = meta if meta is not None else _meta()
    langs = langs if langs is not None else {"Python": 1000}
    if request.url.path.endswith("/languages"):
        return httpx.Response(200, json=langs)
    if request.url.path.endswith("/readme"):
        return httpx.Response(200, json=_readme_payload(readme_text))
    return httpx.Response(200, json=meta)


async def _fetch(handler, owner="ben", repo="demo-proje"):
    async with _client(handler) as client:
        return await ingest.fetch_repo_facts(client, owner, repo)


def test_fork_repo_atlanir():
    facts = __import__("asyncio").run(_fetch(lambda r: _ok_handler(r, meta=_meta(fork=True))))
    assert facts is None


def test_arsivli_repo_atlanir():
    facts = __import__("asyncio").run(_fetch(lambda r: _ok_handler(r, meta=_meta(archived=True))))
    assert facts is None


def test_baskasina_ait_repo_atlanir():
    facts = __import__("asyncio").run(_fetch(lambda r: _ok_handler(r, meta=_meta(owner="baskasi"))))
    assert facts is None


def test_metrikler_metrics_girmez():
    import asyncio

    facts = asyncio.run(_fetch(lambda r: _ok_handler(r)))
    proposal = ingest.build_github_project_proposal(facts)
    assert proposal["metrics"] == {}
    blob = json.dumps(proposal)
    for metric in ("999", "stargazers", "watchers", "forks_count", "subscribers", "followers"):
        assert metric not in blob
    assert proposal["source"] == "github"
    assert proposal["period"] == "2021–2024"
    assert "Python" in proposal["skills"]


def test_readmede_olmayan_teknoloji_skillse_girmez():
    import asyncio

    facts = asyncio.run(_fetch(lambda r: _ok_handler(r)))
    proposal = ingest.build_github_project_proposal(facts)
    assert "Rust" not in proposal["skills"]
    assert "Kubernetes" not in proposal["skills"]
    # README'de GECEN teknoloji girer (docker + python).
    assert "Docker" in proposal["skills"] or "docker" in [s.lower() for s in proposal["skills"]]


def test_evidence_birebir_yoksa_oneri_atilir():
    proposal = {
        "title": "demo-proje",
        "repo": "ben/demo-proje",
        "evidence": "README'de hic gecmeyen uydurma cumle",
    }
    accepted, rejected = ingest.validate_proposals([proposal], {"ben/demo-proje": README})
    assert accepted == [] and len(rejected) == 1


def test_evidence_birebirse_kabul():
    import asyncio

    facts = asyncio.run(_fetch(lambda r: _ok_handler(r)))
    proposal = ingest.build_github_project_proposal(facts)
    accepted, _ = ingest.validate_proposals([proposal], {facts["full_name"]: facts["readme"]})
    assert len(accepted) == 1
    assert accepted[0]["evidence"] in facts["readme"]


def test_token_loglara_sizmiyor(caplog, monkeypatch):
    import asyncio
    import logging

    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    assert TOKEN in ingest.github_headers()["Authorization"]
    with caplog.at_level(logging.INFO, logger="ingest_facts"):
        asyncio.run(_fetch(lambda r: _ok_handler(r)))
    assert TOKEN not in caplog.text


def test_token_ciktiya_yazilmaz(monkeypatch):
    import asyncio

    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    facts = asyncio.run(_fetch(lambda r: _ok_handler(r)))
    proposal = ingest.build_github_project_proposal(facts)
    assert TOKEN not in json.dumps(proposal)
    assert TOKEN not in json.dumps(facts)


def test_ssrf_kotu_owner_istek_yapmaz():
    import asyncio

    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=_meta())

    with pytest.raises(ValueError):
        asyncio.run(_fetch(handler, owner="evil.com/x"))
    with pytest.raises(ValueError):
        asyncio.run(_fetch(handler, owner=".."))
    assert seen == []


def test_rate_limit_zarifce_durur():
    import asyncio

    def handler(request):
        return httpx.Response(429, json={"message": "rate limited"})

    with pytest.raises(ingest.RateLimited):
        asyncio.run(_fetch(handler))


def test_rate_limitte_listeleme_durur():
    import asyncio

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if "/users/" in request.url.path:
            return httpx.Response(200, json=[{"name": "a"}, {"name": "b"}])
        return httpx.Response(429, json={"message": "rate limited"})

    async def go():
        async with _client(handler) as client:
            return await ingest.ingest_github_projects(client, "ben")

    assert asyncio.run(go()) == []


def test_review_role_sorusu():
    answers = iter(["", "ai_assisted"])
    role = review.prompt_role({"title": "demo", "role": "owner"}, input_fn=lambda _: next(answers))
    assert role == "owner"
    role = review.prompt_role({"title": "demo", "role": "owner"}, input_fn=lambda _: next(answers))
    assert role == "ai_assisted"


def test_review_gecersiz_rol_tekrar_sorar():
    answers = iter(["superstar", "owner"])
    role = review.prompt_role({"title": "demo"}, input_fn=lambda _: next(answers))
    assert role == "owner"


def test_ai_assisted_tek_yazarlik_reddi():
    from shared.profile.grounding import validate_grounding

    profile = {"skills": ["Python"], "education": []}
    honest = "Architecture designed and built with AI-assisted development."
    assert validate_grounding(honest, profile, ai_assisted=True) == []
    bad = "Bu projeyi tamamen elle yazdım, hicbir yardim almadim."
    violations = validate_grounding(bad, profile, ai_assisted=True)
    assert any(v.kind == "authorship" for v in violations)
    # ai_assisted yoksa yazarlik kapisi calismaz.
    assert all(v.kind != "authorship" for v in validate_grounding(bad, profile))


def test_ureteci_durust_ifade_kapidan_gecer():
    import sys as _sys

    path = ROOT / "services" / "cv-generator" / "app" / "generator.py"
    spec = importlib.util.spec_from_file_location("cvgen_github_facts", path)
    module = importlib.util.module_from_spec(spec)
    _sys.modules["cvgen_github_facts"] = module
    spec.loader.exec_module(module)
    line = module.DocumentGenerator._project_line(
        {"title": "demo-proje", "period": "2021–2024", "role": "ai_assisted"}, "en"
    )
    assert "AI-assisted" in line
    from shared.profile.grounding import validate_grounding

    # Uretim akisinda render edilen satir allow'a eklenir (tarih/beceri
    # kendi ifadesini ihlal saymaz); yazarlik kapisi yine de calisir.
    assert validate_grounding(line, {"skills": [], "education": []}, allow=[line], ai_assisted=True) == []
    bad = line + " Tamamen elle yazdım."
    assert any(
        v.kind == "authorship"
        for v in validate_grounding(bad, {"skills": [], "education": []}, allow=[line], ai_assisted=True)
    )

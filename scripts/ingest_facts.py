"""Aday fact'leri icin kaynak ingestion (GOREV 2b: GitHub kaynagi).

Kullanim:
    GITHUB_USERNAME=kullanici [GITHUB_REPOS=a,b] [GITHUB_TOKEN=...] \
        python scripts/ingest_facts.py [cikti.jsonl]

Kurallar (ajan fact UYDURMAZ):
- Yalnizca KULLANICIYA AIT, fork OLMAYAN, arsivlenmemis repolar.
- Her repo icin tek bir `project` onerisi; skills = diller + README'de ADI
  GECEN teknolojiler (kapali vocab, kelime sinirli). Yildiz/commit/takipci
  gibi metrikler `metrics`e GIRMEZ (bos kalir).
- `evidence` README'den BIREBIR alintidir; validate_proposals kaynagi
  dogrular, tutmayan oneri atilir.
- GITHUB_TOKEN yalnizca okuma yetkilidir; loglara/ciktiya ASLA yazilmaz.
- Istekler SSRF korumalidir (sabit allowlist host + parca dogrulama) ve
  rate limit'e saygilidir (429/tukenmis kota -> yeniden denemeden durur).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("ingest_facts")

GITHUB_API = "https://api.github.com"
# Repo sahibi/ad parcalari: yol enjeksiyonunu engelle (SSRF'in ilk halkasi).
_REPO_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_LIST_PAGES = 5
_SUMMARY_MAX = 500


class RateLimited(Exception):
    """GitHub kotasi tukendi; yeniden denemeden durulmali."""


def _validate_repo_part(value: str, what: str) -> str:
    cleaned = (value or "").strip()
    if not _REPO_PART_RE.fullmatch(cleaned) or set(cleaned) <= {"."}:
        raise ValueError(f"Gecersiz {what}: {cleaned!r}")
    return cleaned


def github_headers() -> dict[str, str]:
    """Istek basliklari. Token ortamdadir; DONUS DEGERI DAHIL hicbir
    yerde loglanmaz/yazdirilmaz (ASLA)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-job-agent-fact-ingest",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _public_url(url: str) -> str:
    from shared.infra.urls import assert_public_http_url

    return assert_public_http_url(url)


def is_rate_limited(status: int, headers: Any) -> bool:
    if status == 429:
        return True
    if status == 403:
        try:
            remaining = headers.get("x-ratelimit-remaining")
        except Exception:
            return False
        return str(remaining) == "0"
    return False


async def fetch_repo_facts(client: Any, owner: str, repo: str) -> dict | None:
    """Tek repo icin ham fact'leri ceker (None = atla).

    Atlananlar: fork, arsivlenmis, baskasina ait, erisilemeyen,
    rate-limit'e takilan (RateLimited yukselir, cagri durur).
    """
    owner = _validate_repo_part(owner, "owner")
    repo = _validate_repo_part(repo, "repo")
    base = _public_url(f"{GITHUB_API}/repos/{owner}/{repo}")

    r = await client.get(base)
    if is_rate_limited(r.status_code, r.headers):
        raise RateLimited(f"{owner}/{repo}")
    if r.status_code != 200:
        logger.warning("repo atlandi (HTTP %s): %s/%s", r.status_code, owner, repo)
        return None
    meta = r.json()
    if meta.get("fork") or meta.get("archived"):
        logger.info("repo atlandi (fork/arsivli): %s/%s", owner, repo)
        return None
    actual_owner = ((meta.get("owner") or {}).get("login") or "").lower()
    if actual_owner != owner.lower():
        logger.info("repo atlandi (sahibi %s degil): %s/%s", owner, owner, repo)
        return None

    langs: dict = {}
    lang_url = meta.get("languages_url") or f"{base}/languages"
    try:
        lr = await client.get(_public_url(lang_url))
        if is_rate_limited(lr.status_code, lr.headers):
            raise RateLimited(f"{owner}/{repo}")
        if lr.status_code == 200:
            langs = lr.json() or {}
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001 - dil listesi opsiyonel, bos gecer
        logger.warning("diller alinamadi %s/%s: %s", owner, repo, exc)

    readme = ""
    try:
        rr = await client.get(_public_url(f"{base}/readme"))
        if is_rate_limited(rr.status_code, rr.headers):
            raise RateLimited(f"{owner}/{repo}")
        if rr.status_code == 200:
            payload = rr.json() or {}
            content = payload.get("content") or ""
            if payload.get("encoding") == "base64" or content:
                try:
                    readme = base64.b64decode(content).decode("utf-8", "replace")
                except Exception:
                    readme = ""
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001 - README yoksa ozet/evidens bos olur
        logger.warning("README alinamadi %s/%s: %s", owner, repo, exc)

    created = str(meta.get("created_at") or "")[:4]
    pushed = str(meta.get("pushed_at") or "")[:4]
    logger.info("repo fact ok: %s/%s (diller=%d, readme=%d char)", owner, repo, len(langs), len(readme))
    return {
        "name": meta.get("name") or repo,
        "full_name": f"{owner}/{repo}",
        "url": meta.get("html_url") or f"https://github.com/{owner}/{repo}",
        "languages": list(langs),
        "readme": readme,
        "created": created,
        "pushed": pushed,
    }


async def list_user_repos(client: Any, owner: str) -> list[str]:
    """Kullanicinin repolarini listeler (fork/arsivli dahil doner; eleme
    fetch_repo_facts'te yapilir). Rate limit'te durur."""
    owner = _validate_repo_part(owner, "owner")
    names: list[str] = []
    for page in range(1, _MAX_LIST_PAGES + 1):
        url = _public_url(f"{GITHUB_API}/users/{owner}/repos?per_page=100&type=owner&page={page}")
        r = await client.get(url)
        if is_rate_limited(r.status_code, r.headers):
            logger.warning("repo listesi rate limit'e takildi, mevcutlarla devam")
            break
        if r.status_code != 200:
            logger.warning("repo listesi alinamadi (HTTP %s)", r.status_code)
            break
        items = r.json() or []
        if not items:
            break
        for item in items:
            name = item.get("name")
            if name and _REPO_PART_RE.fullmatch(str(name)):
                names.append(str(name))
        if len(items) < 100:
            break
    return names


def extract_readme_summary(readme: str, maximum: int = _SUMMARY_MAX) -> str:
    """README'den ilk esasli paragrafi ozet olarak cikarir (baslik/kod atlanir)."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in (readme or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("```"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if re.match(r"^(\s*[-*]\s+|\s*\d+\.\s+|[A-Z_ ]+:?$)", line) and len(stripped) < 60:
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    for para in paragraphs:
        if len(para) >= 40:
            return para[:maximum].strip()
    return (paragraphs[0][:maximum].strip() if paragraphs else "")


def extract_readme_skills(readme: str, languages: list[str]) -> list[str]:
    """skills = diller + README'de ADI GECEN teknolojiler.

    Kapali vocab (shared/profile/tech_vocab) kelime sinirli aranir;
    README'de gecmeyen teknoloji ASLA skills'e girmez.
    """
    from shared.profile.tech_vocab import KNOWN_TECH_VOCAB

    seen: list[str] = []
    for lang in languages or []:
        if lang and lang not in seen:
            seen.append(lang)
    text = readme or ""
    for tech in KNOWN_TECH_VOCAB:
        if tech.lower() in {s.lower() for s in seen}:
            continue
        if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE) and tech not in seen:
            seen.append(tech)
    return seen


def extract_evidence(readme: str, skills: list[str]) -> str:
    """README'den BIREBIR alinti (once skill iceren satir, yoksa ilk cumle)."""
    lines = [line.strip() for line in (readme or "").splitlines() if line.strip()]
    for line in lines:
        if line.startswith("#") or line.startswith("```"):
            continue
        for skill in skills:
            if skill and re.search(rf"\b{re.escape(skill)}\b", line, re.IGNORECASE):
                return line
    text = re.sub(r"\s+", " ", readme or "").strip()
    match = re.search(r".+?[.!?](\s|$)", text)
    if match:
        return match.group(0).strip()
    return text[:200].strip()


def build_github_project_proposal(repo_facts: dict) -> dict:
    """Tek repo -> tek `project` onerisi. Metrikler metrics'e GIRMEZ (bos)."""
    readme = repo_facts.get("readme") or ""
    skills = extract_readme_skills(readme, repo_facts.get("languages") or [])
    created = repo_facts.get("created") or ""
    pushed = repo_facts.get("pushed") or ""
    period = created if created == pushed else f"{created}–{pushed}"
    return {
        "type": "project",
        "title": repo_facts.get("name") or "",
        "period": period.strip("–"),
        "skills": skills,
        "text": extract_readme_summary(readme),
        "evidence": extract_evidence(readme, skills),
        "source": "github",
        "repo": repo_facts.get("full_name") or "",
        "url": repo_facts.get("url") or "",
        "role": "owner",  # onay adiminda kullanici owner | ai_assisted secer
        "role_fit": ["engineer"],  # onayda duzenlenebilir (consultant | engineer)
        "metrics": {},  # yildiz/commit/takipci BURAYA GIRMEZ; bilerek bos
    }


def _contains_contact(text: str) -> bool:
    """Kisisel iletisim bilgisi tasiyorsa True (kanit havuzuna girmez)."""
    from shared.infra import pii

    if pii.EMAIL_RE.search(text) or pii.ADDRESS_RE.search(text):
        return True
    for match in pii.PHONE_RE.findall(text):
        if ":" in match:
            continue  # saat/IP:port degil iletisim
        if 9 <= sum(ch.isdigit() for ch in match) <= 15:
            return True
    return False


def validate_proposals(proposals: list[dict], sources: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """evidence kaynakta birebir gecmeli; gecmeyen oneri ATILIR.

    sources: {repo_full_name | cv:<dosya>: kaynak metin}. Donus: (kabul, reddedilen).
    Iletisim bilgisi iceren evidence da atilir (kanit havuzuna girmez).
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    for proposal in proposals:
        evidence = (proposal.get("evidence") or "").strip()
        key = proposal.get("repo") or proposal.get("source_doc") or ""
        source_text = sources.get(key, "") or ""
        if not evidence:
            reason = "evidence bos"
        elif _contains_contact(evidence):
            reason = "kanit havuzuna iletisim bilgisi girmez"
        elif evidence not in source_text:
            reason = "evidence kaynakta birebir gecmiyor"
        else:
            accepted.append(proposal)
            continue
        logger.warning("oneri atildi (%s): %s", reason, proposal.get("title"))
        rejected.append({**proposal, "reject_reason": reason})
    return accepted, rejected


async def ingest_github_projects(
    client: Any,
    owner: str,
    repos: Optional[list[str]] = None,
) -> list[dict]:
    """GitHub -> dogrulanmis project onerileri (rate limit'te zarifce durur)."""
    owner = _validate_repo_part(owner, "owner")
    if not repos:
        repos = await list_user_repos(client, owner)
    proposals: list[dict] = []
    sources: dict[str, str] = {}
    for repo in repos:
        try:
            facts = await fetch_repo_facts(client, owner, repo)
        except RateLimited:
            logger.warning("rate limit: kalan repolar atlandi")
            break
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - tek repo hatasi akisi durdurmaz
            logger.warning("repo atlandi (hata): %s/%s: %s", owner, repo, exc)
            continue
        if facts is None:
            continue
        sources[facts["full_name"]] = facts["readme"]
        proposals.append(build_github_project_proposal(facts))
    accepted, _ = validate_proposals(proposals, sources)
    logger.info("github ingestion: %d repo -> %d gecerli oneri", len(repos), len(accepted))
    return accepted


# ---------------- GOREV 2c: yerel kaynak klasoru ----------------
# Env: PROFILE_SOURCES_DIR (varsayilan profile/sources; .gitignore'da).
# .pdf PyPDF2 ile (mevcut CV loader deseni), .docx python-docx ile okunur
# (cv-generator'da ZATEN bagimlilik) — yeni agir bagimlilik YOK.
LOCAL_SOURCE_EXTS = {".pdf", ".docx", ".md", ".txt"}

_ENGINEER_HINTS = [
    "python", "kubernetes", "docker", "terraform", "jenkins", "gitlab",
    "backend", "frontend", "devops", "full-stack", "fullstack", "api",
    "microservices", "ci/cd", "linux", "ansible", "developer", "engineer",
]
_CONSULTANT_HINTS = [
    "alm", "consulting", "consultant", "danışman", "strategy", "strateji",
    "mentor", "governance", "yönetişim", "stakeholder", "maturity",
    "audit", "transformation", "dönüşüm", "advisor",
]


def sources_dir(directory: str | None = None) -> Path:
    return Path(directory or os.environ.get("PROFILE_SOURCES_DIR", "profile/sources"))


def _read_txt_md(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    import PyPDF2

    with path.open("rb") as f:
        reader = PyPDF2.PdfReader(f)
        return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    import docx

    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def redact_for_llm(text: str) -> str:
    """LLM'e gidecek metin: telefon/e-posta/adres/ad redakte edilir."""
    from shared.infra.pii import redact

    return redact(text or "")


def read_local_sources(directory: str | None = None) -> list[dict]:
    """Klasordeki her dosyayi ayri `source` etiketiyle okur.

    Donus: [{"tag": "cv:<dosyaadi>", "raw": ..., "safe": ...}].
    `safe` LLM'e gidebilir; evidence dogrulama HER ZAMAN `raw` ile yapilir.
    """
    base = sources_dir(directory)
    if not base.is_dir():
        logger.warning("kaynak klasoru yok: %s", base)
        return []
    readers = {".md": _read_txt_md, ".txt": _read_txt_md, ".pdf": _read_pdf, ".docx": _read_docx}
    out: list[dict] = []
    for path in sorted(base.iterdir()):
        if not path.is_file() or path.suffix.lower() not in LOCAL_SOURCE_EXTS:
            continue
        try:
            raw = readers[path.suffix.lower()](path)
        except Exception as exc:  # noqa: BLE001 - tek dosya hatasi akisi durdurmaz
            logger.warning("kaynak okunamadi %s: %s", path.name, exc)
            continue
        out.append({"tag": f"cv:{path.name}", "raw": raw or "", "safe": redact_for_llm(raw or "")})
        logger.info("kaynak okundu: %s (%d char)", path.name, len(raw or ""))
    return out


def extract_local_candidates(source: dict) -> list[dict]:
    """Dosya metninden deterministik aday oneriler (satir duzeyinde alinti).

    Hukum KULLANICININDIR (review_facts.py): bu fonksiyon yalnizca birebir
    satirlari aday gosterir, iletisim satirlarini havuza almaz.
    """
    candidates: list[dict] = []
    for line in (source.get("raw") or "").splitlines():
        stripped = line.strip()
        if len(stripped) < 40 or _contains_contact(stripped):
            continue
        candidates.append({
            "type": "excerpt",
            "title": stripped[:60],
            "text": stripped[:500],
            "evidence": stripped,
            "source": "cv",
            "source_doc": source.get("tag") or "",
            "role_fit": ["consultant", "engineer"],
            "metrics": {},
        })
    return candidates


def build_llm_context(source_texts: list[dict], maximum: int = 6000) -> str:
    """LLM istemine girecek redakte baglam (HAM metin ASLA girmez)."""
    parts = []
    for source in source_texts:
        parts.append(f"[{source.get('tag') or '?'}]\n{(source.get('safe') or '')[:maximum]}")
    context = "\n\n".join(parts)
    return context[: maximum * max(len(parts), 1)]


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def detect_date_conflicts(facts: list[dict]) -> list[dict]:
    """Ayni rol farkli tarihlerle gelirse `conflict` yazar, otomatik secmez.

    TARİH icin CV (`cv:` kaynakli) kazanir; tum varyantlar `conflict`
    altinda review_facts.py'ye gosterilir.
    """
    groups: dict[str, list[dict]] = {}
    for fact in facts:
        groups.setdefault(_norm_title(fact.get("title") or ""), []).append(fact)
    merged: list[dict] = []
    for group in groups.values():
        periods: list[tuple[str, str]] = []
        for fact in group:
            period = (fact.get("period") or "").strip()
            src = fact.get("source_doc") or fact.get("source") or ""
            if period and (period, src) not in periods:
                periods.append((period, src))
        base = dict(group[0])
        if len({p for p, _ in periods}) > 1:
            cv_periods = [p for p, s in periods if str(s).startswith("cv:")]
            base["period"] = cv_periods[0] if cv_periods else periods[0][0]
            base["conflict"] = [{"period": p, "source": s} for p, s in periods]
            logger.warning("tarih cakismasi '%s': %s", base.get("title"), base["conflict"])
        merged.append(base)
    return merged


def guess_role(job_title: str, job_text: str = "") -> str | None:
    """Ilan metninden rol tahmini (deterministik anahtar kelime kurali, LLM degil)."""
    haystack = f"{job_title or ''}\n{job_text or ''}".lower()
    eng = sum(1 for hint in _ENGINEER_HINTS if re.search(rf"\b{re.escape(hint)}\b", haystack))
    con = sum(1 for hint in _CONSULTANT_HINTS if re.search(rf"\b{re.escape(hint)}\b", haystack))
    if eng == con:
        return None
    return "engineer" if eng > con else "consultant"


def select_facts(facts: list[dict], job_title: str, job_text: str = "") -> list[dict]:
    """Rol tahmini role_fit'i one alir (kararli siralama, esitlikte dokunmaz)."""
    role = guess_role(job_title, job_text)
    if role is None:
        return list(facts)
    matched = [f for f in facts if role in (f.get("role_fit") or ["consultant", "engineer"])]
    rest = [f for f in facts if f not in matched]
    return matched + rest


async def _amain(out: str = "fact_proposals_github.jsonl") -> int:
    import httpx

    owner = os.environ.get("GITHUB_USERNAME", "").strip()
    if not owner:
        print("GITHUB_USERNAME bos: once kullanici adini verin")  # noqa: T201 - CLI
        return 2
    repos_raw = os.environ.get("GITHUB_REPOS", "").strip()
    repos = [r.strip() for r in repos_raw.split(",") if r.strip()] or None
    async with httpx.AsyncClient(timeout=20.0, headers=github_headers()) as client:
        accepted = await ingest_github_projects(client, owner, repos)
    with Path(out).open("w", encoding="utf-8") as f:
        for proposal in accepted:
            f.write(json.dumps(proposal, ensure_ascii=False) + "\n")
    print(f"{len(accepted)} gecerli oneri -> {out}")  # noqa: T201 - CLI
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    return asyncio.run(_amain(args[0] if args else "fact_proposals_github.jsonl"))


if __name__ == "__main__":
    sys.exit(main())

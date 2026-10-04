from pathlib import Path
from typing import Any, Dict, List, Optional, Set, cast
import re
import yaml
import logging

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None  # type: ignore[assignment]

from shared.config import settings

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s./()-]{7,}\d")
_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+\.(?:vercel\.app|com|de|net|io|dev)(?:/\S*)?", re.IGNORECASE)

# CV.txt / MASTER_CV.txt icinde deneyim bolumunu bulmak icin basliklar (DE + EN).
_EXPERIENCE_HEADINGS = (
    "berufliche erfahrungen",
    "berufserfahrung",
    "professional experience",
    "work experience",
    "employment history",
)
_EXPERIENCE_END_HEADINGS = (
    "ausgewählte projekte",
    "ausgewaehlte projekte",
    "selected projects",
    "portfolio",
    "ausbildung",
    "education",
    "zertifikate",
    "certifications",
    "sprachen",
    "languages",
)

_COMPANY_SPLIT_RE = re.compile(r"\s*[·|]\s*")
_ROLE_KEYWORDS_RE = re.compile(
    r"(architect|founder|consultant|manager|lead|engineer|specialist|director|administrator|"
    r"entwickler|berater|leiter|spezialist|architekt|manager|consultant)",
    re.IGNORECASE,
)


def _read_text_candidates(explicit: Optional[str]) -> tuple[str, Optional[Path]]:
    """Master CV metni icin pdf -> txt -> md sirasiyla ilk bulunan dosyayi oku."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    try:
        candidates.append(Path(settings.MASTER_CV_PATH))
    except Exception:
        pass
    candidates.extend(
        [
            Path("profile/master_cv.pdf"),
            Path("profile/MASTER_CV.txt"),
            Path("profile/master_cv.txt"),
            Path("profile/master_cv.md"),
            Path("profile/MASTER_CV.md"),
            Path("profile/sources/CV.txt"),
            Path("profile/sources/cv.txt"),
            Path("profile/sources/CV.md"),
            Path("profile/sources/cv.md"),
            Path("profile/sources/master_cv.txt"),
        ]
    )
    # sources altinda baska bir txt/md varsa onu da dene
    try:
        src_dir = Path("profile/sources")
        if src_dir.is_dir():
            for extra in sorted(src_dir.glob("*")):
                if extra.suffix.lower() in {".txt", ".md"} and extra not in candidates:
                    candidates.append(extra)
    except Exception:
        pass
    for cand in candidates:
        try:
            if cand.is_file():
                if cand.suffix.lower() == ".pdf":
                    continue  # pdf ayrica PyPDF2 ile okunur
                text = cand.read_text(encoding="utf-8", errors="ignore").strip()
                # "Put Master CV Here" gibi placeholder satirlarini temizle
                lines = [
                    ln
                    for ln in text.splitlines()
                    if ln.strip().lower() not in {"put master cv here", "cv here", "cv here."}
                ]
                cleaned = "\n".join(lines).strip()
                if len(cleaned) >= 50:
                    return cleaned, cand
        except Exception as e:
            logger.warning(f"Could not read master CV text ({cand}): {e}")
    return "", None


def _parse_experience_blocks(cv_text: str) -> List[Dict[str, Any]]:
    """CV.txt icindeki deneyim bolumunu kaba ama deterministik sekilde parse et.

    Beklenen format (kullanicinin CV.txt'si):
        <Unvan satiri>
        <Sirket · donem · lokasyon>
        • <madde>
    Donem yoksa da blok uretilir; grounding icin sirket + donem fact olur.
    """
    if not cv_text:
        return []
    low = cv_text.lower()
    start = -1
    for heading in _EXPERIENCE_HEADINGS:
        idx = low.find(heading)
        if idx != -1:
            start = idx + len(heading)
            break
    if start == -1:
        return []
    end = len(cv_text)
    for heading in _EXPERIENCE_END_HEADINGS:
        idx = low.find(heading, start)
        if idx != -1:
            end = min(end, idx)
    section = cv_text[start:end].strip()
    if not section:
        return []
    lines = [ln.strip() for ln in section.splitlines()]
    lines = [ln for ln in lines if ln]
    experiences: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _flush() -> None:
        if current and (current.get("title") or current.get("company")):
            experiences.append(current)

    def _has_company_hint(text: str) -> bool:
        return (
            "·" in text
            or "|" in text
            or "GmbH" in text
            or " AS " in f" {text} "
            or ".com" in text
            or bool(
                re.search(
                    r"\b(20\d{2}|19\d{2}|Heute|Present|Remote|Berlin|Istanbul|Ankara|Bursa|"
                    r"Ukraine|Vinnytsia|Strausberg|Türkei|Turkei)\b",
                    text,
                )
            )
        )

    def _parse_company_line(text: str, target: Dict[str, Any]) -> None:
        # Sadece · ve | ayraci kullanilir; "2020 – Heute" donemi bolunmez.
        parts = _COMPANY_SPLIT_RE.split(text.replace("|", "·"))
        parts = [p.strip() for p in parts if p.strip()]
        target["company"] = parts[0] if parts else text
        for part in parts[1:]:
            if re.search(r"(19|20)\d{2}|Heute|Present", part):
                target["period"] = part
                break
        rest = [p for p in parts[1:] if p != target.get("period")]
        if rest:
            target["location"] = " / ".join(rest)

    for idx, line in enumerate(lines):
        is_bullet = line.startswith("•") or line.startswith("- ") or line.startswith("* ")
        if is_bullet:
            bullet = line.lstrip("•-* ").strip()
            if current is None:
                current = {"title": "", "company": "", "period": "", "location": "", "bullets": []}
            bullets = current.setdefault("bullets", [])
            if bullet:
                bullets.append(bullet)
            continue
        if line.lower().startswith("stack:"):
            if current is None:
                current = {"title": "", "company": "", "period": "", "location": "", "bullets": []}
            bullets = current.setdefault("bullets", [])
            if bullets:
                bullets[-1] = f"{bullets[-1]} {line}".strip()
            else:
                bullets.append(line)
            continue
        if _has_company_hint(line) and current is not None and not current.get("company"):
            _parse_company_line(line, current)
            continue
        # Sirketten sonraki duz satir: alt satira tasman cumle devami ya da
        # yeni is unvani olabilir. Yeni unvani ele veren isaret: bu satirdan
        # SONRAKI satirin sirket satiri olmasi (unvan + sirket ikilisi).
        # Sonraki satir madde/stack ise bu satir onceki maddenin devamlidir.
        if current is not None and current.get("company"):
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            nxt_clean = nxt.lstrip("•-* ").strip()
            nxt_is_company = bool(nxt) and _has_company_hint(nxt_clean) and not nxt_clean.lower().startswith("stack:")
            if nxt_is_company and _ROLE_KEYWORDS_RE.search(line):
                # Bu satir yeni is unvani: mevcut blogu kapat, yenisini ac.
                _flush()
                current = {"title": line, "company": "", "period": "", "location": "", "bullets": []}
                continue
            # Yoksa onceki maddenin devam cumlesi (or. "Retraining und ...").
            bullets = current.setdefault("bullets", [])
            if bullets:
                bullets[-1] = f"{bullets[-1]} {line}".strip()
            else:
                bullets.append(line)
            continue
        # Yoksa yeni unvan blogu baslat (ardisik baslik satirlarini birlestir).
        if current is not None and not current.get("company") and not current.get("bullets"):
            current["title"] = f"{current['title']} / {line}".strip(" /")
            continue
        _flush()
        current = {"title": line, "company": "", "period": "", "location": "", "bullets": []}
    _flush()
    # Bos baslikli ama sirketli bloklari ele, en az bir maddesi olmali
    return [e for e in experiences if e.get("title") and e.get("company")]


def _enrich_facts_from_cv_text(facts: Dict[str, Any], cv_text: str) -> Dict[str, Any]:
    """profile.yaml'da eksik kalan iletisim + deneyim fact'lerini CV.txt'den doldur."""
    if not cv_text:
        return facts
    if not facts.get("email"):
        match = _EMAIL_RE.search(cv_text)
        if match:
            facts["email"] = match.group(0)
    if not facts.get("phone"):
        # e-postadaki sayilari degil, +49 ile baslayan gercek telefonu tercih et
        phones = _PHONE_RE.findall(cv_text)
        intl = [p.strip() for p in phones if p.strip().startswith("+")]
        local = [p.strip() for p in phones if re.search(r"\d{3,}", p)]
        facts["phone"] = (intl[0] if intl else (local[0] if local else ""))
    if not facts.get("website"):
        match = _URL_RE.search(cv_text)
        if match:
            url = match.group(0)
            facts["website"] = url if url.startswith("http") else f"https://{url}"
    if not facts.get("experience"):
        parsed = _parse_experience_blocks(cv_text)
        if parsed:
            facts["experience"] = parsed
    if not facts.get("projects"):
        # "Ausgewählte Projekte" tablosundaki proje satirlarini kaba yakala
        low = cv_text.lower()
        proj_idx = -1
        for key in ("ausgewählte projekte", "ausgewaehlte projekte", "selected projects"):
            proj_idx = low.find(key)
            if proj_idx != -1:
                break
        if proj_idx != -1:
            proj_section = cv_text[proj_idx : proj_idx + 3000]
            proj_lines = [ln.strip() for ln in proj_section.splitlines() if ln.strip()]
            projects: List[Dict[str, Any]] = []
            for ln in proj_lines[1:10]:
                if len(ln) > 15 and not ln.lower().startswith(("projekt", "portfolio", "ausbildung")):
                    projects.append({"title": ln[:120], "role": "owner"})
            if projects:
                facts.setdefault("projects", projects)
    # CV.txt'de gecen teknik yetkinlikleri skills'e ekle (grounding + tailoring icin)
    try:
        from shared.profile.tech_vocab import KNOWN_TECH_VOCAB
    except Exception:
        KNOWN_TECH_VOCAB = set()
    existing = {str(s).lower() for s in facts.get("skills", []) if isinstance(s, str)}
    cv_low = cv_text.lower()
    for tech in sorted(KNOWN_TECH_VOCAB):
        if tech.lower() in existing:
            continue
        if re.search(rf"\b{re.escape(tech.lower())}\b", cv_low):
            # canonical yazim: vocab'daki hali korunur
            facts.setdefault("skills", []).append(tech)
    return facts


class CanonicalProfile:
    """
    Immutable representation of the candidate's canonical profile.
    Explicitly distinguishes FACT, INFERENCE, and PREFERENCE.
    """
    def __init__(
        self,
        facts: Dict[str, Any],
        preferences: Dict[str, Any],
        inferences: Optional[Dict[str, Any]] = None,
        master_cv_text: Optional[str] = None,
    ):
        self.facts = facts
        self.preferences = preferences
        self.inferences = inferences or {}
        self.master_cv_text = master_cv_text or ""

        # Pre-computed normalized sets for ultra-fast matching
        self._skills_set: Set[str] = {
            s.lower().strip() for s in self.facts.get("skills", [])
        }
        self._preferred_roles_set: Set[str] = {
            r.lower().strip() for r in self.preferences.get("preferred_roles", [])
        }
        self._excluded_roles_set: Set[str] = {
            r.lower().strip() for r in self.preferences.get("excluded_roles", [])
        }
        self._locations_set: Set[str] = {
            loc.lower().strip() for loc in self.preferences.get("locations", [])
        }

    @property
    def name(self) -> str:
        return cast(str, self.facts.get("name", ""))

    @property
    def email(self) -> str:
        return cast(str, self.facts.get("email", ""))

    @property
    def phone(self) -> str:
        return cast(str, self.facts.get("phone", "+49 176 00000000"))

    @property
    def website(self) -> str:
        return cast(str, self.facts.get("website", ""))

    @property
    def experience_years(self) -> int:
        return int(self.facts.get("experience_years", 15))

    @property
    def languages(self) -> Dict[str, str]:
        return cast(Dict[str, str], self.facts.get("languages", {}))

    @property
    def education(self) -> List[Dict[str, Any]]:
        return cast(List[Dict[str, Any]], self.facts.get("education", []))

    @property
    def certifications(self) -> List[str]:
        return cast(List[str], self.facts.get("certifications", []))

    @property
    def skills(self) -> List[str]:
        return cast(List[str], self.facts.get("skills", []))

    @property
    def satisfies(self) -> Dict[str, bool]:
        """B1 kapilari icin acik onaylar (yoksa/hepsi False)."""
        raw = self.preferences.get("satisfies", {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): bool(v) for k, v in raw.items()}

    def has_verified_skill(self, skill: str) -> bool:
        """Returns True only if skill is a verified candidate fact."""
        return skill.lower().strip() in self._skills_set

    def is_role_excluded(self, title: str) -> bool:
        t_low = title.lower()
        return any(ex in t_low for ex in self._excluded_roles_set)

    def is_role_preferred(self, title: str) -> bool:
        t_low = title.lower()
        return any(pref in t_low for pref in self._preferred_roles_set)

    def is_location_preferred(self, location: Optional[str], remote_status: Optional[str]) -> bool:
        if self.preferences.get("remote", True) and remote_status and "remote" in remote_status.lower():
            return True
        if not location:
            return False
        loc_low = location.lower()
        return any(pref in loc_low for pref in self._locations_set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "preferences": self.preferences,
            "inferences": self.inferences,
            "has_master_cv": bool(self.master_cv_text),
        }


def load_canonical_profile(
    profile_path: Optional[str] = None,
    preferences_path: Optional[str] = None,
    master_cv_path: Optional[str] = None,
) -> CanonicalProfile:
    """
    Loads and validates the candidate canonical profile from disk.
    FACT is authoritative.
    """
    p_path = Path(profile_path or settings.PROFILE_PATH)
    pref_path = Path(preferences_path or settings.PREFERENCES_PATH)
    cv_path = Path(master_cv_path or settings.MASTER_CV_PATH)

    # Resolve local fallback paths if running outside docker container
    if not p_path.exists():
        p_path = Path("profile/profile.yaml")
    if not pref_path.exists():
        pref_path = Path("profile/preferences.yaml")
    if not cv_path.exists():
        cv_path = Path("profile/master_cv.pdf")

    facts: Dict[str, Any] = {}
    if p_path.exists():
        with open(p_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            facts = data.get("candidate", data)

    preferences: Dict[str, Any] = {}
    if pref_path.exists():
        with open(pref_path, "r", encoding="utf-8") as f:
            preferences = yaml.safe_load(f) or {}

    master_cv_text = ""
    master_cv_source: Optional[Path] = None
    if cv_path.exists() and cv_path.suffix.lower() == ".pdf" and PyPDF2 is not None:
        try:
            with open(cv_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pages = [page.extract_text() or "" for page in reader.pages]
                master_cv_text = "\n".join(pages).strip()
                if len(master_cv_text) >= 50:
                    master_cv_source = cv_path
        except Exception as e:
            logger.warning(f"Could not extract text from master CV ({cv_path}): {e}")
    # PDF yoksa/bossa: MASTER_CV.txt ve profile/sources/CV.txt'e dus (kullanicinin guclu CV'si).
    if len(master_cv_text) < 50:
        txt_text, txt_source = _read_text_candidates(
            str(cv_path) if cv_path.suffix.lower() != ".pdf" else None
        )
        if len(txt_text) >= 50:
            master_cv_text = txt_text
            master_cv_source = txt_source
    if master_cv_source is not None:
        logger.info(f"Master CV text loaded from {master_cv_source}")
    facts = _enrich_facts_from_cv_text(facts, master_cv_text)

    inferences: Dict[str, Any] = {
        "source": "canonical_profile_loader",
        "website_verified": True if facts.get("website") else False,
    }

    return CanonicalProfile(
        facts=facts,
        preferences=preferences,
        inferences=inferences,
        master_cv_text=master_cv_text,
    )

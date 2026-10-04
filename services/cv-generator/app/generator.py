import hashlib
import io
import logging
import re
from datetime import date
from html import escape
from pathlib import Path
from typing import Dict, List
from uuid import UUID

import docx
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from shared.config import settings
from shared.contracts.models import GeneratedDocument
from shared.infra.storage import MinIOClient
from shared.profile.grounding import Violation, validate_grounding
from shared.profile.loader import CanonicalProfile

logger = logging.getLogger(__name__)
ARTIFACT_DIRECTORY = Path("/app/artifacts")

# Dürüst rol ifadesi: ai_assisted projeler "tamamen elle yazdım" diye
# anlatılmaz; mimari sahiplenilir, AI destegi acikca belirtilir.
_PROJECT_ROLE_PHRASE = {
    "owner": {"en": "Personal project", "de": "Eigenes Projekt"},
    "ai_assisted": {
        "en": "Architecture designed and built with AI-assisted development",
        "de": "Architektur entworfen und mit AI-gestützter Entwicklung umgesetzt",
    },
}
_COVER_AI_SENTENCE = {
    "en": "I designed the architecture of a selected project and built it with AI-assisted development.",
    "de": "Bei einem ausgewählten Projekt habe ich die Architektur entworfen und mit AI-gestützter Entwicklung umgesetzt.",
}

# Kisa kisaltmalar CV'de buyuk harfle gosterilir (grounding case-insensitive).
_UPPER_SKILLS = {"llm", "rag", "api", "aws", "gcp", "alm", "mcp", "mlops"}


def _display_skill(skill: str) -> str:
    return skill.upper() if skill.lower() in _UPPER_SKILLS else skill


def detect_job_language(text: str) -> str:
    """Detect whether a job advert is primarily German or English."""
    german_indicators = [
        "wir suchen", "erfahrung", "aufgaben", "profil", "anforderungen",
        "kenntnisse", "standort",
    ]
    return "de" if sum(word in text.lower() for word in german_indicators) >= 2 else "en"


def filename_slug(value: str, maximum_length: int = 72) -> str:
    """Create a readable, portable artifact filename component."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return (slug[:maximum_length].strip("_") or "untitled").lower()


class DocumentGenerator:
    def __init__(self):
        self.minio = MinIOClient()

    def generate_tailored_documents(
        self,
        job_id: UUID,
        company: str,
        title: str,
        description: str,
        matching_skills: List[str],
        profile: CanonicalProfile,
    ) -> tuple[List[GeneratedDocument], List[Violation]]:
        """Generate factual, job-specific CVs and a cover letter in MinIO and locally.

        Every artifact is grounding-validated BEFORE persistence: violating
        artifacts are neither written locally nor uploaded to MinIO. Returns
        (persisted documents, violations).
        """
        language = detect_job_language(f"{title} {description}")
        tailoring = self._build_tailoring(title, description, matching_skills, profile)
        experience = self._select_experience(profile, f"{title} {description}", limit=4)
        projects = [p for p in (profile.facts.get("projects") or []) if isinstance(p, dict)]
        project_lines = [self._project_line(p, language) for p in projects]
        ai_assisted = any(p.get("role") == "ai_assisted" for p in projects)
        candidate_slug = filename_slug(profile.name)
        company_slug = filename_slug(company)
        role_slug = filename_slug(title)
        artifact_dir = ARTIFACT_DIRECTORY / company_slug / role_slug / str(job_id)
        filename_prefix = f"{candidate_slug}_{company_slug}_{role_slug}_{str(job_id)[:8]}"

        artifacts = [
            (
                "cv",
                1,
                f"{filename_prefix}_CV_{language}.pdf",
                "application/pdf",
                self._build_pdf_cv(profile, company, title, language, tailoring, project_lines, experience),
            ),
            (
                "cv",
                2,
                f"{filename_prefix}_CV_{language}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                self._build_docx_cv(profile, company, title, language, tailoring, project_lines, experience),
            ),
            (
                "cover_letter",
                1,
                f"{filename_prefix}_Cover_Letter_{language}.pdf",
                "application/pdf",
                self._build_pdf_cover_letter(profile, company, title, language, tailoring, ai_assisted, experience),
            ),
        ]

        documents = []
        violations: List[Violation] = []
        allow = [company, title, date.today().strftime("%B %d, %Y"), date.today().strftime("%d.%m.%Y")]
        allow.extend(project_lines)
        # Dogrulanmis deneyim: sirket + donem + secili madde metinleri izinlidir.
        for exp in experience:
            for key in ("company", "period", "title"):
                if exp.get(key):
                    allow.append(str(exp[key]))
            for bullet in (exp.get("bullets") or [])[:4]:
                allow.append(str(bullet))
        if ai_assisted:
            allow.extend(_COVER_AI_SENTENCE.values())
        for document_type, version, filename, mime_type, content in artifacts:
            text = self._extract_text(filename, content)
            found = (
                validate_grounding(text, profile.facts, allow=allow, ai_assisted=ai_assisted)
                if text is not None
                else [Violation("unreadable", filename)]
            )
            if found:
                logger.warning(
                    "Grounding violations in %s: %s",
                    filename,
                    [(v.kind, v.claim) for v in found],
                )
                violations.extend(found)
                continue  # never persist ungrounded artifacts
            local_path = artifact_dir / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            minio_key = f"artifacts/{company_slug}/{role_slug}/{job_id}/{filename}"
            self.minio.upload_bytes(content, minio_key, content_type=mime_type)
            documents.append(
                GeneratedDocument(
                    job_id=job_id,
                    type=document_type,
                    language=language,
                    version=version,
                    minio_bucket=settings.MINIO_BUCKET,
                    minio_key=minio_key,
                    file_path=str(local_path),
                    mime_type=mime_type,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    metadata={
                        "format": "pdf" if filename.endswith(".pdf") else "docx",
                        "company": company,
                        "title": title,
                        "filename": filename,
                        "artifact_relative_path": str(local_path.relative_to(ARTIFACT_DIRECTORY)),
                        "tailored_skills": tailoring["skills"],
                        "tailored_keywords": tailoring["keywords"],
                    },
                )
            )
        return documents, violations

    @staticmethod
    def _project_line(project: Dict, language: str) -> str:
        """Onayli fact'ten tek proje satiri (rolune gore durust ifade)."""
        role = project.get("role") if project.get("role") in _PROJECT_ROLE_PHRASE else "owner"
        phrase = _PROJECT_ROLE_PHRASE[role][language]
        title = str(project.get("title") or "").strip()
        period = str(project.get("period") or "").strip()
        head = title + (f" ({period})" if period else "")
        return f"{head}: {phrase}.".strip()

    @staticmethod
    def _select_experience(profile: CanonicalProfile, job_text: str, limit: int = 4) -> List[Dict]:
        """Is ilanina gore deneyimleri sirala; her deneyimden en ilgili maddeleri sec.

        Sadece facts["experience"] kullanilir (CV.txt'den gelir). Uydurma yok:
        secim = sirala + kisalt, icerik aynen korunur.
        """
        all_exp = [e for e in (profile.facts.get("experience") or []) if isinstance(e, dict)]
        if not all_exp:
            return []
        job_low = job_text.lower()
        tokens = set(re.findall(r"[a-z0-9äöüß+#./-]{3,}", job_low))
        scored = []
        for idx, exp in enumerate(all_exp):
            haystack = " ".join(
                [str(exp.get("title", "")), str(exp.get("company", ""))]
                + [str(b) for b in (exp.get("bullets") or [])]
            ).lower()
            overlap = sum(1 for t in tokens if t in haystack)
            # Guncel deneyimi one cikar (siralamayi koru): ilk bloklara kucuk bonus.
            scored.append((overlap, -idx, exp))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected: List[Dict] = []
        for _, _, exp in scored[:limit]:
            bullets = [str(b) for b in (exp.get("bullets") or []) if str(b).strip()]
            # Madde icinde ilan anahtar kelimesi geceni one al, en fazla 3 madde.
            ranked = sorted(
                bullets,
                key=lambda b: sum(1 for t in tokens if t in b.lower()),
                reverse=True,
            )[:3]
            selected.append(
                {
                    "title": str(exp.get("title", "")).strip(),
                    "company": str(exp.get("company", "")).strip(),
                    "period": str(exp.get("period", "")).strip(),
                    "location": str(exp.get("location", "")).strip(),
                    "bullets": ranked or bullets[:3],
                }
            )
        # CV'de kronolojik okunabilirlik icin orijinal siraya geri diz.
        selected.sort(
            key=lambda s: next(
                (i for i, e in enumerate(all_exp) if e.get("title") == s["title"] and e.get("company") == s["company"]),
                999,
            )
        )
        return selected

    @staticmethod
    def _extract_text(filename: str, content: bytes) -> str | None:
        """Extracts rendered text for grounding validation (None if unreadable)."""
        try:
            if filename.endswith(".pdf"):
                import PyPDF2

                reader = PyPDF2.PdfReader(io.BytesIO(content))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            if filename.endswith(".docx"):
                return "\n".join(
                    paragraph.text for paragraph in docx.Document(io.BytesIO(content)).paragraphs
                )
        except Exception as e:
            logger.warning(f"Could not extract text from {filename}: {e}")
        return None

    def _build_tailoring(
        self,
        title: str,
        description: str,
        matching_skills: List[str],
        profile: CanonicalProfile,
    ) -> Dict[str, List[str] | str]:
        """Select only verified profile skills that appear in this role's text."""
        job_text = f"{title} {description}".lower()
        verified_skills = list(dict.fromkeys(profile.skills))
        selected = [
            skill for skill in verified_skills
            if re.search(rf"\b{re.escape(skill.lower())}\b", job_text)
        ]
        selected.extend(skill for skill in matching_skills if skill in verified_skills and skill not in selected)
        selected = selected[:10]
        if not selected:
            selected = verified_skills[:8]

        keywords = []
        for keyword in ("ai", "automation", "devops", "cloud", "platform", "integration", "security", "data", "test"):
            if keyword in job_text:
                keywords.append(keyword.title())
        return {
            "skills": selected,
            "keywords": keywords[:5],
            "target_role": title,
        }

    def _base_styles(self):
        styles = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "DocTitle", parent=styles["Heading1"], fontSize=21, leading=25,
                textColor=colors.HexColor("#0f172a"), spaceAfter=4,
            ),
            "subtitle": ParagraphStyle(
                "DocSubTitle", parent=styles["Normal"], fontSize=10, leading=14,
                textColor=colors.HexColor("#2563eb"), spaceAfter=10,
            ),
            "heading": ParagraphStyle(
                "SectionH2", parent=styles["Heading2"], fontSize=12, leading=16,
                textColor=colors.HexColor("#1e293b"), spaceBefore=9, spaceAfter=5,
            ),
            "body": ParagraphStyle(
                "Body", parent=styles["Normal"], fontSize=9.5, leading=13.5,
                textColor=colors.HexColor("#334155"), spaceAfter=4,
            ),
        }

    def _contact_parts(self, profile: CanonicalProfile) -> List[str]:
        """Contact line built only from verified, non-empty profile facts."""
        location = profile.facts.get("location", {}) or {}
        city_country = ", ".join(
            part for part in (location.get("city"), location.get("country")) if part
        )
        # NOTE: profile.phone falls back to a dummy placeholder when unset;
        # only use the raw fact so generated documents never print it.
        parts = [profile.email, profile.facts.get("phone"), profile.website, city_country]
        return [part for part in parts if part and part.strip()]

    def _profile_summary(self, profile, language: str, focus: str) -> str:
        """Professional third-person summary grounded only in verified facts."""
        positioning = ", ".join(profile.preferences.get("preferred_roles", [])[:3])
        languages = ", ".join(f"{key} ({value})" for key, value in profile.languages.items())
        # En guncel dogrulanmis rol (CV.txt deneyiminden) ozete somutluk katar.
        recent = ""
        experiences = [e for e in (profile.facts.get("experience") or []) if isinstance(e, dict)]
        if experiences:
            first = experiences[0]
            head = str(first.get("title", "")).strip()
            comp = str(first.get("company", "")).strip()
            if head and comp:
                recent = f"{head} @ {comp}"
            elif head:
                recent = head
        if language == "de":
            base = (
                f"{positioning} mit {profile.experience_years} Jahren Berufserfahrung. "
                f"Schwerpunkte für diese Rolle: {focus}. Sprachen: {languages}."
            )
            return f"{base} Aktuell: {recent}." if recent else base
        base = (
            f"{positioning} with {profile.experience_years} years of professional experience. "
            f"Focus areas for this role: {focus}. Languages: {languages}."
        )
        return f"{base} Most recent: {recent}." if recent else base

    def _experience_heading(self, exp: Dict, language: str) -> str:
        head = exp.get("title", "")
        comp = exp.get("company", "")
        period = exp.get("period", "")
        loc = exp.get("location", "")
        right = " | ".join(p for p in (period, loc) if p)
        left = " - ".join(p for p in (head, comp) if p)
        return f"{left} ({right})" if right else left

    def _build_pdf_cv(self, profile, company, title, language, tailoring, project_lines=None, experience=None) -> bytes:
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=36)
        styles = self._base_styles()
        skills = tailoring["skills"]
        focus = ", ".join(tailoring["keywords"]) or "the role requirements"
        summary = self._profile_summary(profile, language, focus)
        contact = " &nbsp;|&nbsp; ".join(escape(part) for part in self._contact_parts(profile))
        elements = [
            Paragraph(escape(profile.name), styles["title"]),
            Paragraph(
                f"<b>{escape(title)} - {escape(company)}</b><br/>{contact}",
                styles["subtitle"],
            ),
            Paragraph("Profile Summary" if language == "en" else "Profilzusammenfassung", styles["heading"]),
            Paragraph(escape(summary), styles["body"]),
            Paragraph("Role-Relevant Verified Skills" if language == "en" else "Rollenrelevante verifizierte Kenntnisse", styles["heading"]),
            Paragraph(" &bull; ".join(escape(_display_skill(skill)) for skill in skills), styles["body"]),
        ]
        if experience:
            elements.append(
                Paragraph("Professional Experience" if language == "en" else "Berufserfahrung", styles["heading"])
            )
            for exp in experience:
                elements.append(Paragraph(f"<b>{escape(self._experience_heading(exp, language))}</b>", styles["body"]))
                for bullet in (exp.get("bullets") or [])[:3]:
                    elements.append(Paragraph(f"&bull; {escape(str(bullet))}", styles["body"]))
        elements.extend([
            Paragraph("Candidate Profile" if language == "en" else "Kandidatenprofil", styles["heading"]),
            Paragraph(
                f"Primary positioning: {escape(', '.join(profile.preferences.get('preferred_roles', [])[:6]))}. "
                f"Verified professional experience: {profile.experience_years} years.",
                styles["body"],
            ),
            Paragraph("Additional Verified Skills" if language == "en" else "Weitere verifizierte Kenntnisse", styles["heading"]),
            Paragraph(" &bull; ".join(escape(_display_skill(skill)) for skill in profile.skills if skill not in skills), styles["body"]),
            Paragraph("Education & Certifications" if language == "en" else "Ausbildung & Zertifizierungen", styles["heading"]),
            Paragraph(
                f"Education: {escape('; '.join(item.get('degree', '') + ' - ' + item.get('institution', '') for item in profile.education))}<br/>"
                f"Certifications: {escape(' • '.join(profile.certifications))}",
                styles["body"],
            ),
            Paragraph("Languages" if language == "en" else "Sprachen", styles["heading"]),
            Paragraph(escape(" | ".join(f"{key}: {value}" for key, value in profile.languages.items())), styles["body"]),
        ])
        if project_lines:
            elements.extend([
                Paragraph("Selected Projects" if language == "en" else "Ausgewählte Projekte", styles["heading"]),
                *(Paragraph(escape(line), styles["body"]) for line in project_lines),
            ])
        document.build(elements)
        return buffer.getvalue()

    def _build_docx_cv(self, profile, company, title, language, tailoring, project_lines=None, experience=None) -> bytes:
        document = docx.Document()
        document.add_heading(profile.name, level=0)
        contact = document.add_paragraph()
        contact.add_run(f"{title} at {company}\n").bold = True
        contact.add_run(" | ".join(self._contact_parts(profile)))
        focus = ", ".join(tailoring["keywords"]) or "the role requirements"
        document.add_heading("Profile Summary" if language == "en" else "Profilzusammenfassung", level=1)
        document.add_paragraph(self._profile_summary(profile, language, focus))
        document.add_heading("Role-Relevant Verified Skills" if language == "en" else "Rollenrelevante verifizierte Kenntnisse", level=1)
        document.add_paragraph(" • ".join(tailoring["skills"]))
        if experience:
            document.add_heading("Professional Experience" if language == "en" else "Berufserfahrung", level=1)
            for exp in experience:
                document.add_paragraph(self._experience_heading(exp, language)).runs[0].bold = True
                for bullet in (exp.get("bullets") or [])[:3]:
                    document.add_paragraph(str(bullet), style="List Bullet")
        document.add_heading("Candidate Positioning" if language == "en" else "Kandidatenpositionierung", level=1)
        document.add_paragraph(" • ".join(profile.preferences.get("preferred_roles", [])[:8]))
        document.add_heading("Additional Verified Skills" if language == "en" else "Weitere verifizierte Kenntnisse", level=1)
        document.add_paragraph(" • ".join(skill for skill in profile.skills if skill not in tailoring["skills"]))
        document.add_heading("Education & Certifications" if language == "en" else "Ausbildung & Zertifizierungen", level=1)
        document.add_paragraph("Certifications: " + ", ".join(profile.certifications))
        document.add_paragraph("Education: " + "; ".join(f"{item.get('degree', '')} — {item.get('institution', '')}" for item in profile.education))
        document.add_heading("Languages" if language == "en" else "Sprachen", level=1)
        document.add_paragraph(" | ".join(f"{key}: {value}" for key, value in profile.languages.items()))
        if project_lines:
            document.add_heading("Selected Projects" if language == "en" else "Ausgewählte Projekte", level=1)
            for line in project_lines:
                document.add_paragraph(line)
        for paragraph in document.paragraphs:
            for run in paragraph.runs:
                run.font.name = "Aptos"
                run.font.size = Pt(10)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def _cover_experience_sentence(self, language: str, experience) -> str:
        """En ilgili dogrulanmis deneyimden tek somut cumle (isyeri + donem + madde)."""
        if not experience:
            return ""
        top = experience[0]
        head = str(top.get("title", "")).strip()
        comp = str(top.get("company", "")).strip()
        period = str(top.get("period", "")).strip()
        bullet = str((top.get("bullets") or [""])[0]).strip()
        # grounding: cumledeki her parca zaten allow-listed fact'tir.
        if not (head and comp):
            return ""
        where = f"{escape(head)} @ {escape(comp)}" + (f" ({escape(period)})" if period else "")
        if language == "de":
            s = f"Zuletzt: {where}."
            if bullet:
                s += f" U. a.: {escape(bullet[:220])}."
            return s
        s = f"Most recently: {where}."
        if bullet:
            s += f" Including: {escape(bullet[:220])}."
        return s

    def _build_pdf_cover_letter(self, profile, company, title, language, tailoring, ai_assisted=False, experience=None) -> bytes:
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=45)
        styles = self._base_styles()
        top_skills = [escape(_display_skill(skill)) for skill in tailoring["skills"][:3]]
        focus = ", ".join(tailoring["keywords"]) or ("the advertised focus areas" if language == "en" else "die ausgeschriebenen Schwerpunkte")
        exp_sentence = self._cover_experience_sentence(language, experience or [])
        location = profile.facts.get("location", {}) or {}
        city = location.get("city", "")
        today = date.today().strftime("%B %d, %Y" if language == "en" else "%d.%m.%Y")
        place_date = f"{city}, {today}" if city else today
        contact = " &bull; ".join(escape(part) for part in self._contact_parts(profile))
        if language == "de":
            paragraphs = [
                f"Sehr geehrtes Recruiting-Team bei {escape(company)},",
                f"mit {profile.experience_years} Jahren Berufserfahrung als {top_skills[0] if top_skills else 'Fachkraft'} "
                f"bewerbe ich mich für die Position <b>{escape(title)}</b>. Besonders relevant sind meine "
                f"verifizierten Kenntnisse in {', '.join(f'<b>{skill}</b>' for skill in top_skills)}.",
                f"Die Ausschreibung betont {escape(focus)}. Diese Schwerpunkte decken sich mit meiner dokumentierten "
                "Tätigkeit; alle Angaben in dieser Bewerbung stammen ausschließlich aus meinem Kandidatenprofil.",
                "Gerne erläutere ich in einem Gespräch, wie meine Erfahrung zu den Anforderungen der Position passt.",
                f"Mit freundlichen Grüßen,<br/>{escape(profile.name)}",
            ]
            if exp_sentence:
                paragraphs.insert(len(paragraphs) - 1, exp_sentence)
        else:
            connections = (
                f"My verified background covers {', '.join(f'<b>{skill}</b>' for skill in top_skills)} "
                f"across {profile.experience_years} years of professional experience, "
                f"directly matching the role's emphasis on {escape(focus)}."
                if top_skills else
                f"My {profile.experience_years} years of professional experience "
                f"match the role's emphasis on {escape(focus)}."
            )
            paragraphs = [
                f"Dear Hiring Team at {escape(company)},",
                f"I am applying for the <b>{escape(title)}</b> position.",
                connections + " Every statement in this application is limited to verified facts in my candidate profile.",
                "I would welcome the opportunity to discuss how this background fits your requirements.",
                f"Sincerely,<br/>{escape(profile.name)}",
            ]
            if exp_sentence:
                paragraphs.insert(len(paragraphs) - 1, exp_sentence)
        if ai_assisted:
            paragraphs.insert(len(paragraphs) - 1, _COVER_AI_SENTENCE[language])
        elements = [
            Paragraph(escape(profile.name), styles["title"]),
            Paragraph(contact, styles["subtitle"]),
            Spacer(1, 10),
            Paragraph(escape(place_date), styles["body"]),
            Spacer(1, 6),
            Paragraph(f"<b>Application: {escape(title)} - {escape(company)}</b>", styles["body"]),
            Spacer(1, 10),
            *(Paragraph(paragraph, styles["body"]) for paragraph in paragraphs),
        ]
        document.build(elements)
        return buffer.getvalue()

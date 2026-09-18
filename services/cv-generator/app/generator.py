import hashlib
import io
import logging
import re
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
from shared.profile.loader import CanonicalProfile

logger = logging.getLogger(__name__)
ARTIFACT_DIRECTORY = Path("/app/artifacts")


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
    ) -> List[GeneratedDocument]:
        """Generate factual, job-specific CVs and a cover letter in MinIO and locally."""
        language = detect_job_language(f"{title} {description}")
        tailoring = self._build_tailoring(title, description, matching_skills, profile)
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
                self._build_pdf_cv(profile, company, title, language, tailoring),
            ),
            (
                "cv",
                2,
                f"{filename_prefix}_CV_{language}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                self._build_docx_cv(profile, company, title, language, tailoring),
            ),
            (
                "cover_letter",
                1,
                f"{filename_prefix}_Cover_Letter_{language}.pdf",
                "application/pdf",
                self._build_pdf_cover_letter(profile, company, title, language, tailoring),
            ),
        ]

        documents = []
        for document_type, version, filename, mime_type, content in artifacts:
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
        return documents

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

    def _build_pdf_cv(self, profile, company, title, language, tailoring) -> bytes:
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=36)
        styles = self._base_styles()
        skills = tailoring["skills"]
        focus = ", ".join(tailoring["keywords"]) or "the role requirements"
        summary = (
            f"Targeted for {escape(title)} at {escape(company)}. This CV prioritizes the candidate's "
            f"verified experience of {profile.experience_years} years and verified skills relevant to {escape(focus)}."
        )
        if language == "de":
            summary = (
                f"Zielgerichtete Bewerbung für {escape(title)} bei {escape(company)}. Dieser Lebenslauf priorisiert "
                f"die verifizierte Erfahrung von {profile.experience_years} Jahren und relevante, verifizierte Kenntnisse."
            )
        elements = [
            Paragraph(escape(profile.name), styles["title"]),
            Paragraph(
                f"<b>Target role:</b> {escape(title)} &nbsp; | &nbsp; "
                f"{escape(profile.email)} &nbsp; | &nbsp; {escape(profile.website)}",
                styles["subtitle"],
            ),
            Paragraph("Profile Summary" if language == "en" else "Profilzusammenfassung", styles["heading"]),
            Paragraph(summary, styles["body"]),
            Paragraph("Role-Relevant Verified Skills" if language == "en" else "Rollenrelevante verifizierte Kenntnisse", styles["heading"]),
            Paragraph(" &bull; ".join(escape(skill) for skill in skills), styles["body"]),
            Paragraph("Candidate Profile" if language == "en" else "Kandidatenprofil", styles["heading"]),
            Paragraph(
                f"Primary positioning: {escape(', '.join(profile.preferences.get('preferred_roles', [])[:6]))}. "
                f"Verified professional experience: {profile.experience_years} years.",
                styles["body"],
            ),
            Paragraph("Additional Verified Skills" if language == "en" else "Weitere verifizierte Kenntnisse", styles["heading"]),
            Paragraph(" &bull; ".join(escape(skill) for skill in profile.skills if skill not in skills), styles["body"]),
            Paragraph("Education & Certifications" if language == "en" else "Ausbildung & Zertifizierungen", styles["heading"]),
            Paragraph(
                f"Education: {escape('; '.join(item.get('degree', '') + ' — ' + item.get('institution', '') for item in profile.education))}<br/>"
                f"Certifications: {escape(' • '.join(profile.certifications))}",
                styles["body"],
            ),
            Paragraph("Languages" if language == "en" else "Sprachen", styles["heading"]),
            Paragraph(escape(" | ".join(f"{key}: {value}" for key, value in profile.languages.items())), styles["body"]),
        ]
        document.build(elements)
        return buffer.getvalue()

    def _build_docx_cv(self, profile, company, title, language, tailoring) -> bytes:
        document = docx.Document()
        document.add_heading(profile.name, level=0)
        contact = document.add_paragraph()
        contact.add_run(f"Target role: {title} at {company}\n").bold = True
        contact.add_run(f"{profile.email} | {profile.website}")
        document.add_heading("Profile Summary" if language == "en" else "Profilzusammenfassung", level=1)
        document.add_paragraph(
            f"This version is tailored for {title} at {company}. It prioritizes verified profile facts "
            f"and {profile.experience_years} years of professional experience."
        )
        document.add_heading("Role-Relevant Verified Skills" if language == "en" else "Rollenrelevante verifizierte Kenntnisse", level=1)
        document.add_paragraph(" • ".join(tailoring["skills"]))
        document.add_heading("Candidate Positioning" if language == "en" else "Kandidatenpositionierung", level=1)
        document.add_paragraph(" • ".join(profile.preferences.get("preferred_roles", [])[:8]))
        document.add_heading("Additional Verified Skills" if language == "en" else "Weitere verifizierte Kenntnisse", level=1)
        document.add_paragraph(" • ".join(skill for skill in profile.skills if skill not in tailoring["skills"]))
        document.add_heading("Education & Certifications" if language == "en" else "Ausbildung & Zertifizierungen", level=1)
        document.add_paragraph("Certifications: " + ", ".join(profile.certifications))
        document.add_paragraph("Education: " + "; ".join(f"{item.get('degree', '')} — {item.get('institution', '')}" for item in profile.education))
        document.add_heading("Languages" if language == "en" else "Sprachen", level=1)
        document.add_paragraph(" | ".join(f"{key}: {value}" for key, value in profile.languages.items()))
        for paragraph in document.paragraphs:
            for run in paragraph.runs:
                run.font.name = "Aptos"
                run.font.size = Pt(10)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def _build_pdf_cover_letter(self, profile, company, title, language, tailoring) -> bytes:
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=45)
        styles = self._base_styles()
        selected_skills = ", ".join(escape(skill) for skill in tailoring["skills"][:6])
        if language == "de":
            paragraphs = [
                f"Sehr geehrtes Recruiting-Team bei {escape(company)},",
                f"ich bewerbe mich für die Position <b>{escape(title)}</b>. Mein Profil enthält {profile.experience_years} Jahre Berufserfahrung sowie verifizierte Kenntnisse, die für diese Rolle priorisiert wurden.",
                f"Für diese Bewerbung hervorgehoben: <b>{selected_skills}</b>. Diese Angaben stammen ausschließlich aus meinem Kandidatenprofil.",
                "Ich freue mich über die Gelegenheit, die Anforderungen der Position und meinen möglichen Beitrag in einem Gespräch zu erläutern.",
                f"Mit freundlichen Grüßen,<br/>{escape(profile.name)}",
            ]
        else:
            paragraphs = [
                f"Dear Hiring Team at {escape(company)},",
                f"I am applying for the <b>{escape(title)}</b> position. My profile contains {profile.experience_years} years of professional experience and verified skills selected specifically for this role.",
                f"For this application, I have highlighted: <b>{selected_skills}</b>. These statements are limited to facts in my candidate profile.",
                "I would welcome the opportunity to discuss the role's requirements and how my verified background may be relevant.",
                f"Sincerely,<br/>{escape(profile.name)}",
            ]
        elements = [
            Paragraph(escape(profile.name), styles["title"]),
            Paragraph(f"{escape(profile.email)} &bull; {escape(profile.website)}", styles["subtitle"]),
            Spacer(1, 16),
            Paragraph(f"<b>Application: {escape(title)} — {escape(company)}</b>", styles["body"]),
            Spacer(1, 10),
            *(Paragraph(paragraph, styles["body"]) for paragraph in paragraphs),
        ]
        document.build(elements)
        return buffer.getvalue()

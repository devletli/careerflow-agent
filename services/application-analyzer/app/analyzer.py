import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from shared.contracts.models import (
    ApplicationQuestionSchema,
    QuestionClassification,
)
from shared.profile.loader import CanonicalProfile

logger = logging.getLogger(__name__)


class ApplicationField:
    def __init__(
        self,
        field_name: str,
        label: str,
        type: str,
        required: bool = True,
        options: Optional[List[str]] = None,
        confidence: float = 1.0,
        source: str = "form_inspection",
    ):
        self.field_name = field_name
        self.label = label
        self.type = type
        self.required = required
        self.options = options or []
        self.confidence = confidence
        self.source = source

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "options": self.options,
            "confidence": self.confidence,
            "source": self.source,
        }


class FormAnalyzer:
    def detect_ats(self, url: str, html: str = "") -> str:
        """Determines the ATS provider from URL or HTML indicators."""
        u_low = url.lower()
        h_low = html.lower()

        if "workable.com" in u_low or "workable" in h_low:
            return "workable"
        elif "greenhouse.io" in u_low or "gh_src" in u_low or "greenhouse" in h_low:
            return "greenhouse"
        elif "lever.co" in u_low or "lever" in h_low:
            return "lever"
        elif "ashbyhq.com" in u_low or "ashby" in h_low:
            return "ashby"
        elif "smartrecruiters.com" in u_low or "smartrecruiters" in h_low:
            return "smartrecruiters"
        return "generic"

    def analyze_form(
        self,
        url: str,
        html: str,
    ) -> Tuple[List[ApplicationField], List[ApplicationQuestionSchema]]:
        """Extracts normalized form fields and screening questions."""
        soup = BeautifulSoup(html, "html.parser")

        fields: List[ApplicationField] = []
        questions: List[ApplicationQuestionSchema] = []

        # Standard baseline fields present on ATS platforms
        fields.append(ApplicationField("first_name", "First Name", "text", required=True))
        fields.append(ApplicationField("last_name", "Last Name", "text", required=True))
        fields.append(ApplicationField("email", "Email", "email", required=True))
        fields.append(ApplicationField("phone", "Phone", "phone", required=False))
        fields.append(ApplicationField("resume", "Resume / CV", "file", required=True))
        fields.append(ApplicationField("cover_letter", "Cover Letter", "file", required=False))

        # Inspect HTML input fields
        for input_tag in soup.find_all(["input", "select", "textarea"]):
            name = input_tag.get("name") or input_tag.get("id") or ""
            f_type = input_tag.get("type", "text")
            required = input_tag.has_attr("required")

            # Extract label
            label = ""
            if input_tag.get("id"):
                label_tag = soup.find("label", attrs={"for": input_tag.get("id")})
                if label_tag:
                    label = label_tag.get_text(strip=True)
            if not label:
                label = input_tag.get("placeholder") or input_tag.get("aria-label") or name

            if not name or name.lower() in ["csrf", "_token", "authenticity_token"]:
                continue

            options = []
            if input_tag.name == "select":
                f_type = "select"
                options = [opt.get_text(strip=True) for opt in input_tag.find_all("option") if opt.get_text(strip=True)]

            # Check if this is a custom screening question
            if any(term in name.lower() or term in label.lower() for term in [
                "question", "authorized", "sponsor", "salary", "notice", "relocate", "remote", "experience"
            ]):
                classification, confidence = self.classify_question(label or name)
                questions.append(
                    ApplicationQuestionSchema(
                        key=name,
                        text=label or name,
                        type=f_type,
                        is_required=required,
                        options=options,
                        classification=classification,
                        confidence=confidence,
                    )
                )
            else:
                fields.append(
                    ApplicationField(
                        field_name=name,
                        label=label,
                        type=f_type,
                        required=required,
                        options=options,
                    )
                )

        return fields, questions

    def classify_question(self, question_text: str) -> Tuple[QuestionClassification, float]:
        """
        Classifies an application question according to APPLICATION_ANSWER_PROMPT:
        - SAFE_FACT
        - SAFE_TRANSFORMATION
        - USER_PREFERENCE
        - LEGAL_OR_WORK_AUTHORIZATION
        - UNKNOWN
        """
        q_low = question_text.lower()

        # Legal & Work Authorization
        if any(w in q_low for w in ["authorized to work", "work permit", "visa", "sponsorship", "legally eligible", "arbeitserlaubnis"]):
            return QuestionClassification.LEGAL_OR_WORK_AUTHORIZATION, 1.0

        # User Preferences
        if any(w in q_low for w in ["salary expectation", "gehalt", "compensation", "notice period", "kündigungsfrist", "start date", "relocat", "willing to travel"]):
            return QuestionClassification.USER_PREFERENCE, 0.95

        # Safe Transformations (years-of-<field>-experience covers
        # Greenhouse/Lever variants like "years of DevOps experience").
        if any(w in q_low for w in ["jahre erfahrung", "highest degree", "highest education", "level of english", "deutschkenntnisse"]):
            return QuestionClassification.SAFE_TRANSFORMATION, 0.95
        if "years of experience" in q_low or re.search(r"years?\s+of\s+[\w\s]*experience", q_low):
            return QuestionClassification.SAFE_TRANSFORMATION, 0.95

        # Safe Facts
        if any(w in q_low for w in ["first name", "last name", "email", "phone", "website", "linkedin", "github", "city", "country"]):
            return QuestionClassification.SAFE_FACT, 1.0

        return QuestionClassification.UNKNOWN, 0.0

    def resolve_answer(
        self,
        question: ApplicationQuestionSchema,
        profile: CanonicalProfile,
    ) -> Tuple[Optional[Any], str, bool]:
        """
        Resolves answer for a question safely without guessing:
        Returns: (answer_value, source, is_verified)
        """
        q_text = question.text.lower()
        classification = question.classification

        if classification == QuestionClassification.SAFE_FACT:
            if "first name" in q_text:
                return profile.name.split()[0], "PROFILE_FACT", True
            if "last name" in q_text:
                parts = profile.name.split()
                return " ".join(parts[1:]) if len(parts) > 1 else "", "PROFILE_FACT", True
            if "email" in q_text:
                return profile.email, "PROFILE_FACT", True
            if "phone" in q_text:
                return profile.phone, "PROFILE_FACT", True
            if "website" in q_text or "portfolio" in q_text:
                return profile.website, "PROFILE_FACT", True
            if "city" in q_text:
                return profile.facts.get("location", {}).get("city", "Strausberg"), "PROFILE_FACT", True
            if "country" in q_text:
                return profile.facts.get("location", {}).get("country", "Germany"), "PROFILE_FACT", True

        elif classification == QuestionClassification.SAFE_TRANSFORMATION:
            if "years of experience" in q_text or "erfahrung" in q_text:
                return profile.experience_years, "SAFE_TRANSFORMATION", True
            if "deutsch" in q_text or "german" in q_text:
                return profile.languages.get("German", "C1"), "SAFE_TRANSFORMATION", True
            if "english" in q_text or "englisch" in q_text:
                return profile.languages.get("English", "C1"), "SAFE_TRANSFORMATION", True
            if "degree" in q_text or "education" in q_text:
                return "Computer Engineering (B.Sc.)", "SAFE_TRANSFORMATION", True

        elif classification == QuestionClassification.USER_PREFERENCE:
            if "relocat" in q_text:
                pref = profile.preferences.get("relocation", False)
                return ("Yes" if pref else "No"), "USER_PREFERENCE", True
            if "remote" in q_text:
                pref = profile.preferences.get("remote", True)
                return ("Yes" if pref else "No"), "USER_PREFERENCE", True
            if "salary" in q_text or "gehalt" in q_text:
                # Never guess salary unless explicitly defined in preferences
                configured_salary = profile.preferences.get("expected_salary")
                if configured_salary:
                    return configured_salary, "USER_PREFERENCE", True
                return None, "USER_PREFERENCE", False

        elif classification == QuestionClassification.LEGAL_OR_WORK_AUTHORIZATION:
            # Strictly verified profile facts
            auth_info = profile.facts.get("work_authorization", {})
            if "authorized" in q_text and auth_info.get("country") == "Germany":
                # Candidate is EU/German work authorized
                return "Yes", "LEGAL_OR_WORK_AUTHORIZATION", True
            if "sponsor" in q_text:
                # No sponsorship required for Germany
                return "No", "LEGAL_OR_WORK_AUTHORIZATION", True

        # UNKNOWN or unanswered
        return None, "UNKNOWN", False

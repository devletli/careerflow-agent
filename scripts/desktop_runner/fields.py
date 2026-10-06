"""Verified-answer field matching (pure helpers, stdlib only).

Shared by the legacy one-shot fill and the assisted loop: only verified
profile answers are ever written; everything else stays empty for the human.
"""
from __future__ import annotations

import re


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def standard_answers(profile: dict) -> dict:
    name_parts = profile.get("name", "").split()
    location = profile.get("location", {})
    full_name = profile.get("name", "")
    return {
        "first_name": name_parts[0] if name_parts else "",
        "firstname": name_parts[0] if name_parts else "",
        "last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
        "lastname": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "website": profile.get("website", ""),
        "portfolio": profile.get("website", ""),
        "city": location.get("city", ""),
        "country": location.get("country", ""),
        # Ayrışmamış ad alanları ("Legal Name") için adın tamamı.
        # Bilerek "name" değil "full_name": kısa anahtar username/
        # company_name gibi alanları da yakalardı.
        "full_name": full_name,
    }


def answer_for_field(field_key: str, answers: dict) -> object | None:
    if not field_key:
        return None
    for answer_key, answer_value in answers.items():
        normalized_key = normalized(answer_key)
        if normalized_key and (
            normalized_key in field_key or field_key in normalized_key
        ):
            return answer_value
    # "Legal Name" gibi tek parça ad alanları: adın tamamı.
    if "legal" in field_key or field_key in ("name", "fullname", "full_name"):
        return answers.get("full_name")
    return None

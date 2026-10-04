"""Sert kapilar: riskli ilan skoru yuksek olsa bile QUALIFIED'a girmez (B1).

Kapilar yalnizca QUALIFIED -> REVIEW dusurur (asla otomatik reddetmez).
Tetiklenme, profilin acik onayina (`profile.yaml -> satisfies`) baglidir;
onaylanmamis iddia REVIEW'a duser ve gerekcesi kayda yazilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Gate:
    name: str
    pattern: re.Pattern[str]
    profile_key: str  # profile.yaml -> "satisfies" altindaki anahtar


GATES: tuple[Gate, ...] = (
    Gate("german_c1", re.compile(
        r"(verhandlungssicher|fließend|fliessend)\w*\s+deutsch|deutsch\s*(c1|c2|muttersprach\w*)", re.I), "german_c1"),
    Gate("senior_title", re.compile(r"\b(senior|lead|principal|head of|staff)\b", re.I), "senior"),
    Gate("security_clearance", re.compile(
        r"sicherheits(überprüfung|check)|security clearance|ü2|ü3", re.I), "clearance"),
)


def evaluate_gates(job_text: str, title: str, satisfies: dict[str, bool]) -> list[str]:
    haystack = f"{title}\n{job_text}"
    return [g.name for g in GATES if g.pattern.search(haystack) and not satisfies.get(g.profile_key, False)]


def apply_gates(band: str, hits: list[str]) -> str:
    return "REVIEW" if (band == "QUALIFIED" and hits) else band

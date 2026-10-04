"""B1 kapilari unit testleri (offline, deterministik)."""
import pytest

from shared.matching.gates import apply_gates, evaluate_gates


@pytest.mark.parametrize("text,title,expected", [
    ("Wir erwarten verhandlungssicheres Deutsch", "Python Developer", ["german_c1"]),
    ("Fließend Deutsch erforderlich", "Backend Engineer", ["german_c1"]),
    ("Python, FastAPI", "Senior Backend Engineer", ["senior_title"]),
    ("Python, FastAPI", "Backend Engineer", []),
])
def test_gates(text, title, expected):
    assert evaluate_gates(text, title, {}) == expected


def test_gate_never_rejects_only_downgrades():
    assert apply_gates("QUALIFIED", ["senior_title"]) == "REVIEW"
    assert apply_gates("REVIEW", ["senior_title"]) == "REVIEW"
    assert apply_gates("NOT_QUALIFIED", ["senior_title"]) == "NOT_QUALIFIED"


def test_satisfied_gate_is_ignored():
    assert evaluate_gates("Fließend Deutsch", "Dev", {"german_c1": True}) == []


def test_senior_in_body_does_not_trigger():
    assert evaluate_gates("Du arbeitest mit Senior Engineers zusammen", "Backend Developer", {}) == []


def test_senior_in_title_triggers():
    assert evaluate_gates("Python", "Senior Backend Developer", {}) == ["senior_title"]


def test_clearance_word_boundary():
    assert evaluate_gates("Heute Menü2 in der Kantine", "Dev", {}) == []
    assert evaluate_gates("Sicherheitsüberprüfung erforderlich", "Dev", {}) == ["security_clearance"]

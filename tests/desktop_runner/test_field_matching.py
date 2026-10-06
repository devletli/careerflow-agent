"""Field matching: label text, empty-key guard, full-name fallback (pure, no browser)."""

import importlib.util
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"


def _load():
    sys.modules.pop("desktop_runner.fields", None)
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "desktop_runner.fields", PACKAGE_DIR / "fields.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["desktop_runner.fields"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(PACKAGE_DIR.parent))
        except ValueError:
            pass


def test_empty_field_key_never_matches():
    fields = _load()
    answers = {"first_name": "Ada", "email": "ada@example.com"}
    assert fields.answer_for_field("", answers) is None


def test_legal_name_falls_back_to_full_name():
    fields = _load()
    answers = fields.standard_answers({"name": "Ada Lovelace", "email": "", "location": {}})
    assert fields.answer_for_field("systemfield_name_legal_name", answers) == "Ada Lovelace"


def test_full_name_does_not_hijack_username_or_company():
    fields = _load()
    answers = fields.standard_answers({"name": "Ada Lovelace", "email": "", "location": {}})
    assert fields.answer_for_field("username", answers) is None
    assert fields.answer_for_field("company_name", answers) is None


def test_specific_name_parts_win_over_fallback():
    fields = _load()
    answers = fields.standard_answers({"name": "Ada Lovelace", "email": "", "location": {}})
    assert fields.answer_for_field("first_name", answers) == "Ada"
    assert fields.answer_for_field("last_name", answers) == "Lovelace"

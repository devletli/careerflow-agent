"""T7 dashboard i18n tests (offline, static).

User-facing dashboard text lives in services/frontend/i18n/{en,tr}.json;
the default locale comes from the DASHBOARD_LOCALE setting. Both files
must share the same keys, placeholders, and action ids.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
I18N = ROOT / "services" / "frontend" / "i18n"
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"
LIB = ROOT / "services" / "frontend" / "app" / "lib.js"


def _load(name):
    return json.loads((I18N / name).read_text(encoding="utf-8"))


def test_locales_share_keys_and_action_ids():
    en, tr = _load("en.json"), _load("tr.json")
    assert set(en) == set(tr), f"locale key mismatch: {set(en) ^ set(tr)}"
    assert [a["id"] for a in en["actions"]] == [a["id"] for a in tr["actions"]]
    assert len(en["tabs"]) == len(tr["tabs"]) == 6
    assert len(en["actions"]) == len(tr["actions"]) == 5


def test_placeholders_match_across_locales():
    en, tr = _load("en.json"), _load("tr.json")
    for key in ("confirmStart", "confirmSubmit"):
        assert set(re.findall(r"\{\w+\}", en[key])) == set(re.findall(r"\{\w+\}", tr[key]))


def test_page_uses_strings_module_not_hardcoded_tabs():
    src = PAGE.read_text(encoding="utf-8")
    assert "STRINGS" in src
    assert "const TABS = STRINGS.tabs" in src
    assert "const ACTIONS = STRINGS.actions" in src
    assert '"Overview", "Jobs"' not in src
    for literal in ("Open in Browser", "Fill with Playwright", "Submit with Playwright",
                    "Playwright ile Gönder", "Tarayıcıda Aç",
                    "Pipeline Controls", "Recent Jobs", "Runtime Settings",
                    "Discovered / matched jobs", "Application history",
                    "Generated CVs and cover letters", "Continue manually",
                    "No jobs discovered yet.", "No applications yet.",
                    "No documents generated yet.", "Switch to light mode"):
        assert literal not in src, f"hardcoded dashboard text: {literal}"


def test_lib_selects_locale_from_env():
    src = LIB.read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_LOCALE" in src
    assert "STRINGS" in src


def test_compose_wires_dashboard_locale():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_LOCALE" in compose and "DASHBOARD_LOCALE" in compose
    assert "DASHBOARD_LOCALE=" in env_example

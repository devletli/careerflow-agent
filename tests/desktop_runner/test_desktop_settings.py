"""DesktopSettings: standalone config (never imports shared.config/pydantic)."""

import importlib.util
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"


def _load_config():
    for module_name in ("desktop_runner", "desktop_runner.config"):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "desktop_runner.config", PACKAGE_DIR / "config.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["desktop_runner.config"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(PACKAGE_DIR.parent))
        except ValueError:
            pass


def test_defaults_match_spec(monkeypatch):
    config = _load_config()
    for key in (
        "DESKTOP_HANDOFF_TIMEOUT_SECONDS",
        "DESKTOP_AUTO_NEXT",
        "DESKTOP_TYPE_DELAY_MS",
        "DESKTOP_BROWSER_CHANNEL",
        "DESKTOP_PROFILE_DIR",
        "LOCALAPPDATA",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = config.DesktopSettings.from_env()
    assert settings.handoff_timeout_seconds == 900.0
    assert settings.auto_next is True
    assert settings.type_delay_ms == 15
    assert settings.browser_channel == "chrome"


def test_validators_reject_non_positive(monkeypatch):
    config = _load_config()
    for key in (
        "DESKTOP_HANDOFF_TIMEOUT_SECONDS",
        "DESKTOP_AUTO_NEXT",
        "DESKTOP_TYPE_DELAY_MS",
        "DESKTOP_BROWSER_CHANNEL",
        "DESKTOP_PROFILE_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    import pytest

    with pytest.raises(ValueError):
        config.DesktopSettings(handoff_timeout_seconds=0)
    with pytest.raises(ValueError):
        config.DesktopSettings(type_delay_ms=-1)
    with pytest.raises(ValueError):
        config.DesktopSettings(browser_channel="firefox")


def test_env_overrides_and_bool_parsing(monkeypatch):
    config = _load_config()
    monkeypatch.setenv("DESKTOP_HANDOFF_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("DESKTOP_AUTO_NEXT", "false")
    monkeypatch.setenv("DESKTOP_TYPE_DELAY_MS", "30")
    monkeypatch.setenv("DESKTOP_BROWSER_CHANNEL", "chromium")
    settings = config.DesktopSettings.from_env()
    assert settings.handoff_timeout_seconds == 60.0
    assert settings.auto_next is False
    assert settings.type_delay_ms == 30
    assert settings.browser_channel == "chromium"


def test_profile_dir_outside_repo(monkeypatch, tmp_path):
    config = _load_config()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DESKTOP_PROFILE_DIR", raising=False)
    settings = config.DesktopSettings.from_env()
    assert str(settings.profile_dir).startswith(str(tmp_path))
    assert "careerflow" in settings.profile_dir.parts


def test_does_not_import_server_settings():
    source = (PACKAGE_DIR / "config.py").read_text(encoding="utf-8")
    assert "from shared" not in source
    assert "import shared" not in source
    assert "from pydantic" not in source
    assert "import pydantic" not in source

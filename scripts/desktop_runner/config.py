"""Standalone desktop-runner settings (stdlib only).

Intentionally NOT part of shared.config.Settings: the desktop runner
executes on the user's Windows host with only playwright+pyyaml installed,
while shared.config requires four server secrets at import time.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BROWSER_CHANNELS = ("chrome", "chromium")


def default_profile_dir() -> Path:
    """Persistent browser profile. Always outside the repo (sessions survive)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "careerflow" / "browser-profile"
    return Path.home() / ".careerflow" / "browser-profile"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DesktopSettings:
    handoff_timeout_seconds: float = 900.0
    auto_next: bool = True
    type_delay_ms: int = 15
    browser_channel: str = "chrome"
    profile_dir: Path = field(default_factory=default_profile_dir)

    def __post_init__(self) -> None:
        if self.handoff_timeout_seconds <= 0:
            raise ValueError("DESKTOP_HANDOFF_TIMEOUT_SECONDS must be > 0")
        if self.type_delay_ms <= 0:
            raise ValueError("DESKTOP_TYPE_DELAY_MS must be > 0")
        if self.browser_channel not in BROWSER_CHANNELS:
            raise ValueError(f"DESKTOP_BROWSER_CHANNEL must be one of {BROWSER_CHANNELS}")

    @classmethod
    def from_env(cls) -> DesktopSettings:
        profile_raw = os.environ.get("DESKTOP_PROFILE_DIR")
        return cls(
            handoff_timeout_seconds=_env_float(
                "DESKTOP_HANDOFF_TIMEOUT_SECONDS", 900.0
            ),
            auto_next=_env_bool("DESKTOP_AUTO_NEXT", True),
            type_delay_ms=_env_int("DESKTOP_TYPE_DELAY_MS", 15),
            browser_channel=os.environ.get("DESKTOP_BROWSER_CHANNEL", "chrome")
            .strip()
            .lower()
            or "chrome",
            profile_dir=Path(profile_raw).expanduser()
            if profile_raw and profile_raw.strip()
            else default_profile_dir(),
        )

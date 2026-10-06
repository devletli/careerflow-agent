"""Launch a visible, local Playwright application-preparation session on Windows."""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from playwright.async_api import Page, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_runner.config import DesktopSettings  # noqa: E402
from desktop_runner.assisted import run_assisted  # noqa: E402
from desktop_runner.documents import (  # noqa: E402
    cleanup_upload_files,
    prepare_upload_files,
)
from desktop_runner.fields import (  # noqa: E402
    answer_for_field,
    normalized,
    standard_answers,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE_URL = "http://localhost:8000"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktop-runner")


def application_id_from_uri(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "ai-job-agent" or parsed.netloc != "prepare":
        raise ValueError("Expected an ai-job-agent://prepare?application_id=<UUID> URL.")
    application_id = urllib.parse.parse_qs(parsed.query).get("application_id", [""])[0]
    if not application_id:
        raise ValueError("The local application URL is missing application_id.")
    return application_id


def _api_key_from_env() -> str:
    """API anahtarini proje .env dosyasindan okur (dashboard disindan erisim)."""
    env_path = PROJECT_ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def request_context(application_id: str) -> dict:
    url = f"{API_BASE_URL}/api/v1/applications/{application_id}/desktop-context"
    request = urllib.request.Request(url, headers={"X-API-Key": _api_key_from_env()})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except Exception as exc:
        raise RuntimeError(
            "Could not retrieve the application from the local AI Job Agent API. "
            "Make sure Docker Compose is running."
        ) from exc


def load_profile() -> dict:
    with (PROJECT_ROOT / "profile" / "profile.yaml").open(encoding="utf-8") as profile_file:
        return (yaml.safe_load(profile_file) or {}).get("candidate", {})


async def fill_form(page: Page, context: dict, profile: dict) -> None:
    answers = standard_answers(profile)
    answers.update(context["verified_answers"])

    await page.goto(context["application_url"], wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(1_000)

    fields = page.locator("input:not([type='hidden']), textarea")
    for index in range(await fields.count()):
        field = fields.nth(index)
        if not await field.is_visible() or not await field.is_enabled():
            continue
        input_type = (await field.get_attribute("type") or "text").lower()
        if input_type in {"file", "checkbox", "radio", "submit", "button", "password", "hidden"}:
            continue
        # HOTFIX: kimlik bilgisi/OTP alanlarina asla yazma (tur + autocomplete cift filtresi).
        autocomplete = (await field.get_attribute("autocomplete") or "").lower().strip()
        if autocomplete in {"one-time-code", "current-password", "new-password"}:
            continue
        field_key = normalized(
            " ".join(
                filter(
                    None,
                    [
                        await field.get_attribute("name"),
                        await field.get_attribute("id"),
                        await field.get_attribute("autocomplete"),
                        await field.get_attribute("placeholder"),
                        await field.get_attribute("aria-label"),
                    ],
                )
            )
        )
        value = answer_for_field(field_key, answers)
        if value is not None and str(value).strip():
            await field.fill(str(value))

    await upload_documents(page, context["document_paths"])
    await page.screenshot(
        path=str(PROJECT_ROOT / "browser-traces" / f"{context['application_id']}_desktop_prepared.png"),
        full_page=True,
    )


async def upload_documents(page: Page, document_paths: dict) -> None:
    for index in range(await page.locator("input[type='file']").count()):
        field = page.locator("input[type='file']").nth(index)
        field_key = normalized(
            " ".join(
                filter(
                    None,
                    [
                        await field.get_attribute("name"),
                        await field.get_attribute("id"),
                        await field.get_attribute("accept"),
                    ],
                )
            )
        )
        document_type = (
            "cover_letter" if "cover" in field_key or "letter" in field_key else "resume"
        )
        relative_path = document_paths.get(document_type)
        if relative_path:
            document_path = PROJECT_ROOT / "artifacts" / relative_path
            if document_path.is_file():
                await field.set_input_files(str(document_path))


async def run(application_uri: str, *, fresh_profile: bool = False) -> None:
    application_id = application_id_from_uri(application_uri)
    context = request_context(application_id)
    profile = load_profile()
    settings = DesktopSettings.from_env()
    if fresh_profile:
        user_data_dir = Path(tempfile.mkdtemp(prefix="careerflow-desktop-"))
    else:
        user_data_dir = settings.profile_dir
        user_data_dir.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "browser-traces").mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict = {
        "headless": False,
        "viewport": {"width": 1440, "height": 1000},
    }
    if settings.browser_channel != "chromium":
        launch_kwargs["channel"] = settings.browser_channel
    prepared = prepare_upload_files(API_BASE_URL, _api_key_from_env(), application_id)
    async with async_playwright() as playwright:
        browser_context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            **launch_kwargs,
        )
        page, _summary = await run_assisted(
            browser_context,
            context["application_url"],
            profile,
            context["verified_answers"],
            settings,
            prepared,
        )
        await page.screenshot(
            path=str(PROJECT_ROOT / "browser-traces" / f"{context['application_id']}_desktop_prepared.png"),
            full_page=True,
        )
        logger.info(
            "%s — %s hazır. CAPTCHA/giriş ve kalan alanları tamamlayıp "
            "başvuruyu kendiniz gönderin. İşiniz bittiğinde tarayıcı "
            "penceresini kapatın.",
            context["company"],
            context["title"],
        )
        try:
            await browser_context.wait_for_event("close", timeout=0)
        finally:
            # Chromium dosyayi submit aninda okur: temp belgeler ancak
            # tarayici kapandiktan sonra silinir.
            cleanup_upload_files(prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("application_uri")
    parser.add_argument(
        "--fresh-profile",
        action="store_true",
        help="Gecici bir tarayici profili ac (oturum saklanmaz).",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.application_uri, fresh_profile=args.fresh_profile))
    except (RuntimeError, ValueError) as exc:
        logger.error("AI Job Agent desktop runner error: %s", exc)
        raise SystemExit(1) from exc

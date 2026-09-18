"""Launch a visible, local Playwright application-preparation session on Windows."""

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from playwright.async_api import Page, async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE_URL = "http://localhost:8000"
USER_DATA_DIRECTORY = PROJECT_ROOT / "browser-state" / "desktop-profile"


def application_id_from_uri(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "ai-job-agent" or parsed.netloc != "prepare":
        raise ValueError("Expected an ai-job-agent://prepare?application_id=<UUID> URL.")
    application_id = urllib.parse.parse_qs(parsed.query).get("application_id", [""])[0]
    if not application_id:
        raise ValueError("The local application URL is missing application_id.")
    return application_id


def request_context(application_id: str) -> dict:
    url = f"{API_BASE_URL}/api/v1/applications/{application_id}/desktop-context"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response)
    except Exception as exc:
        raise RuntimeError(
            "Could not retrieve the application from the local AI Job Agent API. "
            "Make sure Docker Compose is running."
        ) from exc


def load_profile() -> dict:
    with (PROJECT_ROOT / "profile" / "profile.yaml").open(encoding="utf-8") as profile_file:
        return (yaml.safe_load(profile_file) or {}).get("candidate", {})


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def standard_answers(profile: dict) -> dict:
    name_parts = profile.get("name", "").split()
    location = profile.get("location", {})
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
    }


def answer_for_field(field_key: str, answers: dict) -> object | None:
    for answer_key, answer_value in answers.items():
        normalized_key = normalized(answer_key)
        if normalized_key and (
            normalized_key in field_key or field_key in normalized_key
        ):
            return answer_value
    return None


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
        if input_type in {"file", "checkbox", "radio", "submit", "button"}:
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


async def run(application_uri: str) -> None:
    application_id = application_id_from_uri(application_uri)
    context = request_context(application_id)
    profile = load_profile()
    USER_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "browser-traces").mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser_context = await playwright.chromium.launch_persistent_context(
            str(USER_DATA_DIRECTORY),
            headless=False,
            viewport={"width": 1440, "height": 1000},
        )
        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
        await fill_form(page, context, profile)
        print(
            f"{context['company']} — {context['title']} hazır. "
            "CAPTCHA/giriş ve kalan alanları tamamlayıp başvuruyu kendiniz gönderin."
        )
        print("İşiniz bittiğinde Chromium penceresini kapatın.")
        await page.wait_for_event("close")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("application_uri")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.application_uri))
    except (RuntimeError, ValueError) as exc:
        print(f"AI Job Agent desktop runner error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

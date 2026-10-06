"""Generic ATS form adapter: accessible locator-first field filling.

Fills only plan entries carrying a verified value; everything else lands in
skipped_unverified and is never guessed. Protection controls are never
touched. No submit capability exists on adapters by design.
"""
import logging
import re
from pathlib import Path

from playwright.async_api import Page

from browser.site_adapters.base import FieldPlan, FieldSpec, FillResult

logger = logging.getLogger(__name__)

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "[data-sitekey]",
]

CAPTCHA_TEXT = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "security check",
    "prove you're human",
    "robot",
    "cloudflare",
    "access denied",
]

LOGIN_TEXT = [
    "sign in to continue",
    "please log in",
    "create an account to apply",
]

MFA_TEXT = [
    "mfa",
    "2fa",
    "two-factor",
    "two factor",
    "multi-factor",
    "multi factor",
    "authenticator",
    "verification code",
    "verify your identity",
]

# pre_fill: yalnizca bunlar tiklanir; ACCEPT_ALL_RX eslesen hicbir sey tiklanmaz.
REJECT_RX = re.compile(
    r"reject|decline|only necessary|necessary only|essential only|"
    r"strictly necessary|nur notwendige|alle ablehnen|ablehnen|"
    r"yaln.zca gerekli|sadece gerekli|reddet|zorunlu|sadece zorunlu",
    re.I,
)

ACCEPT_ALL_RX = re.compile(
    r"accept all|alle akzeptieren|t.m.n. kabul et", re.I
)


class GenericAdapter:
    name = "generic"

    def matches(self, url: str) -> bool:
        return True

    async def detect_blockers(self, page: Page) -> str | None:
        for selector in CAPTCHA_SELECTORS:
            if await page.locator(selector).count():
                return "CAPTCHA"
        if await page.locator("input[type=password]").count():
            return "LOGIN"
        text = (await page.content()).lower()
        if any(indicator in text for indicator in CAPTCHA_TEXT):
            return "CAPTCHA"
        if any(indicator in text for indicator in MFA_TEXT):
            return "MFA"
        if any(indicator in text for indicator in LOGIN_TEXT):
            return "LOGIN"
        return None

    async def discover_application(self, page: Page) -> str | None:
        """Generic kural: site-ici kesif yok; Engine cagrisi aynen gecer."""
        return None

    def submit_locator(self, page: Page) -> str | None:
        """Siteye ozel secici yok; Engine varsayilan SUBMIT_SELECTORS kullanilir."""
        return None

    async def form_root(self, page: Page) -> Page:
        """Varsayilan: ana sayfa (gomulu form yok)."""
        return page

    def field_specs(self) -> dict[str, FieldSpec]:
        """Varsayilan: ATS'ye ozel cozum yok."""
        return {}

    async def pre_fill(self, page: Page) -> None:
        """Yalnizca reject/necessary-only cerez dugmesini tiklar.

        Accept-all eslesen dugmeler atlanir; hicbiri bulunamazsa dokunulmaz.
        """
        try:
            buttons = await page.get_by_role("button").all()
        except Exception:
            return
        for btn in buttons:
            try:
                name = (await btn.inner_text()).strip()
            except Exception:
                continue
            if not name or ACCEPT_ALL_RX.search(name):
                continue
            if not REJECT_RX.search(name):
                continue
            try:
                if await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    return
            except Exception:
                continue

    def _match_key(self, plan: list[FieldPlan], key: str) -> FieldPlan | None:
        for field in plan:
            if field.key.lower() in key or key in field.key.lower():
                return field
        return None

    async def fill(self, page: Page, plan: list[FieldPlan]) -> FillResult:
        result = FillResult()
        for field in plan:
            if field.value is None or not str(field.value).strip():
                result.skipped_unverified.append(field.key)
        answerable = {f.key: f for f in plan if f.value is not None and str(f.value).strip()}

        for inp in await page.query_selector_all(
            "input[type='text'], input[type='email'], input[type='tel'], input:not([type])"
        ):
            try:
                name = await inp.get_attribute("name") or ""
                inp_id = await inp.get_attribute("id") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                key = (name or inp_id or placeholder).lower().replace("-", "_").replace(" ", "_")
                if not key:
                    continue
                field = self._match_key(plan, key)
                if field is None or field.key not in answerable:
                    continue
                if await inp.is_visible() and await inp.is_enabled():
                    await inp.click()
                    await inp.fill(str(answerable[field.key].value))
                    result.filled.append(field.key)
                    logger.debug(f"Filled input '{key}'")
            except Exception as field_err:
                logger.debug(f"Skipping field fill error: {field_err}")

        for ta in await page.query_selector_all("textarea"):
            try:
                name = await ta.get_attribute("name") or ""
                ta_id = await ta.get_attribute("id") or ""
                key = (name or ta_id).lower().replace("-", "_")
                field = self._match_key(plan, key)
                if field is None or field.key not in answerable:
                    continue
                if await ta.is_visible():
                    await ta.fill(str(answerable[field.key].value))
                    result.filled.append(field.key)
            except Exception:
                pass

        for sel in await page.query_selector_all("select"):
            try:
                name = await sel.get_attribute("name") or ""
                sel_id = await sel.get_attribute("id") or ""
                key = (name or sel_id).lower().replace("-", "_")
                field = self._match_key(plan, key)
                if field is None or field.key not in answerable:
                    continue
                value = str(answerable[field.key].value)
                try:
                    await sel.select_option(label=value)
                except Exception:
                    await sel.select_option(value=value)
                result.filled.append(field.key)
            except Exception:
                pass

        for upload in await page.query_selector_all("input[type='file']"):
            try:
                name = await upload.get_attribute("name") or ""
                up_id = await upload.get_attribute("id") or ""
                key = (name or up_id).lower().replace("-", "_")
                field = self._match_key(plan, key)
                if field is None or field.key not in answerable:
                    continue
                path = Path(str(answerable[field.key].value))
                if path.is_file():
                    await upload.set_input_files(str(path))
                    result.filled.append(field.key)
                else:
                    result.skipped_unverified.append(field.key)
            except Exception:
                pass

        return result

    async def verify_submission(self, page: Page) -> bool:
        """Conservative generic confirmation: never claim success lightly.

        Site-specific adapters (Workable/Greenhouse/Lever) should override
        this with their own confirmation rules. The generic adapter only
        accepts an explicit application-received style message.
        """
        try:
            body = (await page.content()).lower()
        except Exception:
            return False
        explicit_markers = (
            "application received",
            "thank you for applying",
            "submission confirmed",
            "your application has been submitted",
            "application submitted",
        )
        return any(marker in body for marker in explicit_markers)

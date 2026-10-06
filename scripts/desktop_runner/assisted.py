"""Assisted loop: fill -> hand off on blocker -> wait -> continue.

Adapter-free by design: it reuses the existing verified_answers matching
(fields.py) and wraps the fill/wait cycle around it. No status reporting in
v1, no submit clicking, no credential writing. On posting pages with zero
filled fields, a narrow form-opener ("Apply for this job") is clicked once
to reveal the form; submit-family labels are never clicked.
"""
from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import BrowserContext, Locator, Page

from desktop_runner.blockers import detect_blocker
from desktop_runner.config import DesktopSettings
from desktop_runner.documents import attach_files
from desktop_runner.fields import answer_for_field, normalized, standard_answers
from desktop_runner.fill import (
    FILLED,
    mark_unverified,
    set_checkable,
    set_select,
)
from desktop_runner.handoff import (
    active_page,
    ensure_panel_script,
    show_panel,
    wait_for_user,
)
from desktop_runner.navigation import (
    NEXT_RX,
    click_form_opener,
    click_next,
    dismiss_cookie_banner,
    is_submit_label,
    wait_for_content,
)
from desktop_runner.resolver import (
    CREDENTIAL_KEYS,
    absence_reason,
    diagnose,
    fill_and_verify,
    fill_combobox,
    is_sensitive,
    resolve,
)
from desktop_runner.target import resolve_target

REASONS = {
    "CAPTCHA": "CAPTCHA bekleniyor.",
    "LOGIN": "Giriş bekleniyor.",
    "MFA": "Doğrulama kodu bekleniyor.",
}

MAX_STEPS = 12

logger = logging.getLogger("desktop-runner")

SKIP_TYPES = {
    "file",
    "checkbox",
    "radio",
    "submit",
    "button",
    "password",
    "hidden",
    "image",
    "reset",
}

CREDENTIAL_AUTOCOMPLETE = {"one-time-code", "current-password", "new-password"}
TRUTHY = {"yes", "true", "1", "checked", "on", "ja"}


@dataclass
class StepResult:
    filled: list[str] = field(default_factory=list)
    unverified_required: list[str] = field(default_factory=list)
    unverified_locators: list[Locator] = field(default_factory=list)
    field_records: list[dict] = field(default_factory=list)


@dataclass
class AssistSummary:
    filled: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    fields: list[dict] = field(default_factory=list)
    handoffs: int = 0
    timed_out: str | None = None
    ats: str = "generic"
    target_kind: str = "form"  # form | stay | moved | email_only | no_form
    target_reason: str | None = None  # EMAIL_ONLY | NO_ONLINE_FORM | None
    target_email: str | None = None  # panele gosterilir, rapora yazilmaz


def _adapter_hooks(app_url: str):
    """Registry uzerinden adapter (ATS `if` yok); yoksa bos kancalar."""
    try:
        from browser.site_adapters.registry import resolve as resolve_adapter

        adapter = resolve_adapter(app_url or "")
        return adapter.field_specs(), adapter
    except Exception:
        return {}, None


def _record(result: StepResult, key: str, outcome: str,
            reason: str | None = None) -> None:
    entry: dict = {"key": str(key), "outcome": outcome}
    if reason:
        entry["reason"] = reason
    result.field_records.append(entry)


async def _fresh_page(ctx: BrowserContext) -> Page:
    """Varsa boş sekmeyi kullanır, yoksa açar (gereksiz boş sekme birikmez)."""
    try:
        for candidate in ctx.pages:
            try:
                if candidate.url in ("about:blank", "chrome://newtab/"):
                    return candidate
            except Exception:
                continue
    except Exception:
        pass
    return await ctx.new_page()


async def _field_key(field: Locator) -> str:
    parts = []
    for attr in ("name", "id", "autocomplete", "placeholder", "aria-label"):
        try:
            parts.append(await field.get_attribute(attr))
        except Exception:
            parts.append(None)
    # Ashby gibi sitelerde alan adı yalnızca <label>'da yazar.
    try:
        parts.append(
            await field.evaluate(
                "(el) => (el.labels ? Array.from(el.labels).map(l => l.innerText).join(' ') : '')"
            )
        )
    except Exception:
        parts.append(None)
    return normalized(" ".join(filter(None, parts)))


async def _is_required(field: Locator) -> bool:
    try:
        return bool(
            await field.evaluate(
                "(el) => el.required === true || el.getAttribute('aria-required') === 'true'"
            )
        )
    except Exception:
        return False


async def _current_value(field: Locator) -> str:
    try:
        return (await field.input_value()).strip()
    except Exception:
        return ""


def _matches_checkable(field_value_attr: str | None, verified: object) -> bool:
    text = str(verified).strip().lower()
    if not text:
        return False
    if text in TRUTHY:
        return True
    attr = (field_value_attr or "").lower()
    return bool(attr) and (text == attr or text in attr or attr in text)


async def _fill_verified_keys(page: Page, root, specs: dict, answers: dict,
                              delay_ms: int, result: StepResult) -> None:
    """Anahtar-gudumlu doldurma: coz -> (hassasiyet filtresi) -> yaz-dogrula.

    Cozulemeyen dogrulanmis deger tahminle yazilmaz (ambiguous kaydi duser,
    not_found sessiz gecilir). Hassas alan sarilanir, insanin kalir.
    """
    for answer_key, answer_value in (answers or {}).items():
        if answer_value is None or not str(answer_value).strip():
            continue
        value = str(answer_value)
        for candidate_key in (str(answer_key), normalized(str(answer_key))):
            norm = normalized(str(answer_key))
            if norm in CREDENTIAL_KEYS or "password" in norm:
                break
            spec = specs.get(candidate_key)
            kind = (spec.kind if spec is not None else "text")
            if kind in ("select", "checkbox", "file"):
                continue
            try:
                loc = await resolve(root, candidate_key, spec)
            except Exception:
                continue
            if loc is None:
                try:
                    if await absence_reason(root, candidate_key, spec) == "ambiguous":
                        _record(result, candidate_key, "ambiguous",
                                "multiple_candidates")
                except Exception:
                    pass
                continue
            try:
                if await is_sensitive(loc):
                    await mark_unverified(page, [loc])
                    _record(result, candidate_key, "skipped_sensitive",
                            "sensitive_never_fill")
                    result.unverified_required.append(candidate_key)
                    result.unverified_locators.append(loc)
                    break
            except Exception:
                break
            try:
                if kind == "combobox":
                    outcome = await fill_combobox(loc, value)
                else:
                    outcome = await fill_and_verify(loc, value, delay_ms)
            except RuntimeError:
                _record(result, candidate_key, "skipped_credential",
                        "credential_protected")
                break
            except Exception:
                continue
            if outcome == "filled":
                _record(result, candidate_key, "filled")
                result.filled.append(candidate_key)
            elif outcome == "failed_verify":
                try:
                    reason = await diagnose(loc, value)
                except Exception:
                    reason = "value_mismatch"
                _record(result, candidate_key, "failed_verify", reason)
                result.unverified_required.append(candidate_key)
            elif outcome == "skipped_unverified":
                _record(result, candidate_key, "skipped_unverified",
                        "requires_human")
            else:
                _record(result, candidate_key, outcome,
                        "prefilled_kept" if outcome == "skipped_prefilled"
                        else "credential_protected")
            break


async def inspect_and_fill(page: Page, answers: dict, delay_ms: int,
                           app_url: str = "") -> StepResult:
    """Fill one visible step from verified answers; record human work."""
    result = StepResult()
    specs, adapter = _adapter_hooks(app_url)
    try:
        root = await adapter.form_root(page) if adapter is not None else page
    except Exception:
        root = page
    await _fill_verified_keys(page, root, specs, answers, delay_ms, result)

    fields = page.locator("input:not([type='hidden']), textarea")
    for index in range(await fields.count()):
        loc = fields.nth(index)
        try:
            if not await loc.is_visible() or not await loc.is_enabled():
                continue
        except Exception:
            continue
        try:
            tag = (await loc.evaluate("(el) => el.tagName")).lower()
        except Exception:
            continue
        if tag == "textarea":
            input_type = "textarea"
        else:
            try:
                input_type = ((await loc.get_attribute("type")) or "text").lower()
            except Exception:
                input_type = "text"
        if input_type in SKIP_TYPES:
            continue
        try:
            autocomplete = ((await loc.get_attribute("autocomplete")) or "").lower().strip()
        except Exception:
            autocomplete = ""
        key = await _field_key(loc)
        required = await _is_required(loc)
        if autocomplete in CREDENTIAL_AUTOCOMPLETE:
            if required and not await _current_value(loc):
                result.unverified_required.append(key or "credential")
                result.unverified_locators.append(loc)
            continue
        value = answer_for_field(key, answers)
        if value is not None and str(value).strip():
            # Phase A owned verified fills; cozulemeyen insanin isi.
            try:
                sensitive = await is_sensitive(loc)
            except Exception:
                sensitive = False
            if sensitive:
                await mark_unverified(page, [loc])
                _record(result, key, "skipped_sensitive",
                        "sensitive_never_fill")
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)
                continue
            try:
                empty = not await _current_value(loc)
            except Exception:
                empty = True
            if required and empty:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)
            continue
        if not await _current_value(loc):
            if required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    for index in range(await page.locator("select").count()):
        loc = page.locator("select").nth(index)
        try:
            if not await loc.is_visible() or not await loc.is_enabled():
                continue
        except Exception:
            continue
        key = await _field_key(loc)
        required = await _is_required(loc)
        value = answer_for_field(key, answers)
        if value is not None and str(value).strip():
            try:
                sensitive = await is_sensitive(loc)
            except Exception:
                sensitive = False
            if sensitive:
                await mark_unverified(page, [loc])
                _record(result, key, "skipped_sensitive",
                        "sensitive_never_fill")
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)
                continue
            if await set_select(loc, str(value)) == FILLED:
                result.filled.append(key)
        else:
            try:
                selected = await loc.evaluate(
                    "(el) => { const s = Array.from(el.selectedOptions).map(o => o.value);"
                    " return el.multiple ? s : (s[0] ?? ''); }"
                )
            except Exception:
                selected = ""
            has_selection = (
                any(str(v).strip() for v in selected)
                if isinstance(selected, list)
                else bool(str(selected).strip())
            )
            if not has_selection and required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    for box_type in ("checkbox", "radio"):
        boxes = page.locator(f"input[type='{box_type}']")
        for index in range(await boxes.count()):
            loc = boxes.nth(index)
            try:
                if not await loc.is_visible() or not await loc.is_enabled():
                    continue
                checked = await loc.is_checked()
            except Exception:
                continue
            if checked:
                continue
            key = await _field_key(loc)
            required = await _is_required(loc)
            value = answer_for_field(key, answers)
            matched = False
            if value is not None and str(value).strip():
                try:
                    attr = await loc.get_attribute("value")
                except Exception:
                    attr = None
                matched = _matches_checkable(attr, value)
            if matched:
                try:
                    sensitive = await is_sensitive(loc)
                except Exception:
                    sensitive = False
                if sensitive:
                    await mark_unverified(page, [loc])
                    _record(result, key, "skipped_sensitive",
                            "sensitive_never_fill")
                    result.unverified_required.append(key)
                    result.unverified_locators.append(loc)
                elif await set_checkable(loc, True) == FILLED:
                    result.filled.append(key)
            elif required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    return result


async def looks_like_application_form(page: Page, app_url: str) -> bool:
    """True when the page plausibly hosts the application form."""
    try:
        current = urllib.parse.urlparse(page.url)
        want = urllib.parse.urlparse(app_url)
        if (
            current.hostname
            and want.hostname
            and current.hostname.lower() != want.hostname.lower()
        ):
            return False
    except Exception:
        pass
    try:
        if await page.locator("input[type=password]:visible").count():
            return False  # login wall, not the form
        if await page.locator("input[type='file']:visible").count():
            return True
        for btn in await page.get_by_role("button").all():
            try:
                name = (await btn.inner_text()).strip()
            except Exception:
                continue
            if name and is_submit_label(name):
                try:
                    if await btn.is_visible():
                        return True
                except Exception:
                    continue
        if await page.locator("input[required]:visible").count():
            return True
    except Exception:
        return False
    return False


async def is_final_step(page: Page) -> bool:
    """True when no clickable Next-type button remains."""
    try:
        for btn in await page.get_by_role("button").all():
            try:
                name = (await btn.inner_text()).strip()
            except Exception:
                continue
            if not name or is_submit_label(name):
                continue
            try:
                if (
                    NEXT_RX.match(name)
                    and await btn.is_visible()
                    and await btn.is_enabled()
                ):
                    return False
            except Exception:
                continue
    except Exception:
        return True
    return True


def summary_text(filled: int, unverified: int) -> str:
    if unverified:
        return f"{filled} alan dolduruldu; sarı alanları sen doldur, sonra gönder."
    return f"{filled} alan dolduruldu; formu gözden geçirip gönder."


async def run_assisted(
    ctx: BrowserContext,
    app_url: str,
    profile: dict,
    verified_answers: dict,
    settings: DesktopSettings,
    prepared: dict[str, Path],
) -> tuple[Page, AssistSummary]:
    """Fill, hand off on blockers, wait, and continue across steps."""
    answers = standard_answers(profile)
    answers.update(verified_answers or {})

    await ensure_panel_script(ctx)
    page = await _fresh_page(ctx)
    await page.goto(app_url, wait_until="domcontentloaded", timeout=45_000)
    # Boş sayfa normaldir (yeni sekme); içerik belirmeden tarama yapılmaz.
    await wait_for_content(page)

    summary = AssistSummary()
    target = await resolve_target(
        page,
        app_url,
        form_like=await looks_like_application_form(page, app_url),
        blocked=await detect_blocker(page) is not None,
        recheck_form=lambda p: looks_like_application_form(p, app_url),
    )
    summary.ats = target.get("ats", "generic")
    summary.target_kind = target.get("kind", "form")
    if target["kind"] == "email_only":
        summary.target_reason = "EMAIL_ONLY"
        summary.target_email = target.get("email")
        await show_panel(
            page,
            f"Bu ilan e-posta ile basvuru istiyor: {summary.target_email}. "
            "Mail atmadim; adresi dashboard'daki ilanda da gorebilirsin.",
        )
        return page, summary
    if target["kind"] == "no_form":
        summary.target_reason = "NO_ONLINE_FORM"
        await show_panel(
            page,
            "Bu sayfada cevrimici basvuru formu bulamadim (NO_ONLINE_FORM).",
        )
        return page, summary
    opener_tried = False
    for _ in range(MAX_STEPS):
        blocker = await detect_blocker(page)
        if blocker:
            summary.handoffs += 1
            ok = await wait_for_user(
                ctx,
                page,
                REASONS[blocker],
                detect_blocker,
                timeout_s=settings.handoff_timeout_seconds,
            )
            if not ok:
                summary.timed_out = blocker
                break
            page = active_page(ctx, page)
            if not await looks_like_application_form(page, app_url):
                await page.goto(app_url, wait_until="domcontentloaded", timeout=45_000)
            continue
        await dismiss_cookie_banner(page)
        step = await inspect_and_fill(page, answers, settings.type_delay_ms,
                                      app_url)
        await attach_files(page, prepared)
        await mark_unverified(page, step.unverified_locators)
        summary.filled.extend(step.filled)
        summary.unverified.extend(step.unverified_required)
        summary.fields.extend(step.field_records)
        logger.info(
            "Adım sonucu: %d dolduruldu, %d doğrulanmamış gerekli alan.",
            len(step.filled),
            len(step.unverified_required),
        )
        if step.unverified_required or await is_final_step(page):
            # Posting page?: nothing filled and nothing required, so the form
            # may hide behind an "Apply for this job" opener. Try it once;
            # submit-family labels are never clicked (see navigation.py).
            if not summary.filled and not summary.unverified and not opener_tried:
                logger.info("Form açıcı aranıyor (hiç alan doldurulamadı)...")
                if await click_form_opener(page):
                    opener_tried = True
                    logger.info("Form açıcı tıklandı, form taranıyor.")
                    await wait_for_content(page)
                    continue
                logger.info("Form açıcı bulunamadı, bitiriliyor.")
            break
        if not settings.auto_next or not await click_next(page):
            break
    await show_panel(page, summary_text(len(summary.filled), len(summary.unverified)))
    return page, summary

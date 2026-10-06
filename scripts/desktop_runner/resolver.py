"""Saglam alan cozumu + doldurma-sonrasi dogrulama (stdlib + playwright).

Kurallar:
- Tam OLARAK bir gorunur aday varsa dondur; belirsizse None (tahmin yok).
- Deger geri okunamazsa veya aria-invalid=true ise kirmizi + failed_verify;
  yeniden deneme dongusu YOK.
- Maas/izin/uyruk/saglik/ozel kategori alanlarina ASLA yazilmaz (sari).
- Password/OTP'ye yazilmaz; kullanicinin degeri ezilmez (mevcut fill.py).
"""
from __future__ import annotations

import re

from desktop_runner.fill import RED, YELLOW, fill_field, highlight

GREEN = "#22c55e"

SYNONYMS = {
    "first_name": ["first name", "given name", "vorname"],
    "firstname": ["first name", "given name", "vorname"],
    "last_name": ["last name", "surname", "family name", "nachname"],
    "lastname": ["last name", "surname", "family name", "nachname"],
    "full_name": ["full name", "legal name", "complete name"],
    "email": ["email", "e-mail", "e-mail-adresse", "e-posta"],
    "phone": ["phone", "telefon", "mobil", "handy", "phone number"],
    "website": ["website", "webseite", "homepage"],
    "portfolio": ["portfolio", "website"],
    "linkedin": ["linkedin"],
    "location": ["location", "standort", "current location"],
    "city": ["city", "stadt", "town"],
    "country": ["country", "land"],
    "organization": ["company", "organization", "organisation",
                     "current company", "arbeitgeber"],
    "resume": ["resume", "cv", "lebenslauf"],
    "cover_letter": ["cover letter", "anschreiben", "motivationsschreiben",
                     "additional information"],
}

# ASLA otomatik doldurulmaz: maas, calisma izni, uyruk, saglik/ozel kategori.
SENSITIVE_RX = re.compile(
    r"salary|gehalt|verg.tung|compensation|wage|lohn|pay\b|maas|maaş|"
    r"authoriz|arbeitserlaubnis|besch.ftigungserlaubnis|visa|sponsorship|"
    r"citizen|nationality|staatsangeh.rigkeit|uyruk|vatandas|"
    r"health|gesundheit|disab|behinderung|gender|geschlecht|race|ethni|"
    r"religion|pregnan|schwanger|age\b|alter\b|geburt|sexual|orientation|"
    r"military|veteran|eeo|diversity",
    re.I,
)

# Cevap anahtari kimlik bilgisi ise cozume hic girilmez.
CREDENTIAL_KEYS = {"password", "passwort", "sifre", "şifre", "one-time-code",
                   "onetimecode", "otp", "current-password", "new-password",
                   "mfa", "totp"}

VISIBLE_TIMEOUT_MS = 5000


def _label_pattern(label: str):
    return re.compile(rf"\b{re.escape(label)}\b", re.I)


async def _single_visible(loc, timeout_ms: int = VISIBLE_TIMEOUT_MS):
    """count==1 ve gorunurse locator, yoksa None (sinirli bekleme)."""
    try:
        if await loc.count() != 1:
            return None
    except Exception:
        return None
    first = loc.first
    try:
        await first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        try:
            if not await first.is_visible():
                return None
        except Exception:
            return None
    try:
        if await first.is_visible():
            return first
    except Exception:
        return None
    return None


async def resolve(root, key: str, spec=None):
    """Tam OLARAK bir gorunur aday varsa onu dondurur; belirsizse None."""
    if not key or key.strip().lower().replace("_", "-") in CREDENTIAL_KEYS:
        return None
    labels = list(getattr(spec, "labels", None) or ())
    if spec is not None:
        for sel in (getattr(spec, "selectors", None) or ()):
            try:
                found = await _single_visible(root.locator(sel))
            except Exception:
                continue
            if found is not None:
                return found
    seen: set[str] = set()
    for label in (*labels, *SYNONYMS.get(key, [])):
        norm = label.strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        try:
            loc = root.get_by_label(_label_pattern(label))
            if await loc.count() != 1:
                continue
        except Exception:
            continue
        found = await _single_visible(loc)
        if found is not None:
            return found
    return None


async def absence_reason(root, key: str, spec=None) -> str:
    """resolve() None dondugunde: 'ambiguous' | 'not_found'."""
    labels = [*(getattr(spec, "labels", None) or ()), *SYNONYMS.get(key, [])]
    for label in labels:
        try:
            loc = root.get_by_label(_label_pattern(label))
            if await loc.count() > 1:
                return "ambiguous"
        except Exception:
            continue
    return "not_found"


async def field_text(loc) -> str:
    """Erisilebilir ad metni: label + ad/id/placeholder/aria-label."""
    parts: list[str] = []
    for attr in ("name", "id", "placeholder", "aria-label"):
        try:
            value = await loc.get_attribute(attr)
        except Exception:
            value = None
        if value:
            parts.append(value)
    try:
        labels = await loc.evaluate(
            "(el) => (el.labels ? Array.from(el.labels).map(l => l.innerText).join(' ') : '')"
        )
    except Exception:
        labels = ""
    if labels:
        parts.append(labels)
    return " ".join(parts)


async def is_sensitive(loc) -> bool:
    try:
        return SENSITIVE_RX.search(await field_text(loc)) is not None
    except Exception:
        return False


async def diagnose(loc, value: str) -> str:
    """failed_verify alt sebebi: 'aria_invalid' | 'value_mismatch'."""
    try:
        if (await loc.get_attribute("aria-invalid")) == "true":
            return "aria_invalid"
    except Exception:
        pass
    return "value_mismatch"


async def fill_and_verify(loc, value: str, delay_ms: int) -> str:
    """Yaz, geri oku, dogrula. Donus: fill outcome veya 'failed_verify'."""
    outcome = await fill_field(loc, value, delay_ms)
    if outcome != "filled":
        return outcome
    try:
        ok = (await loc.input_value()) == value
    except Exception:
        ok = False
    try:
        invalid = (await loc.get_attribute("aria-invalid")) == "true"
    except Exception:
        invalid = False
    if ok and not invalid:
        return "filled"
    try:
        await highlight(loc, RED)
    except Exception:
        pass
    return "failed_verify"


async def fill_combobox(loc, value: str) -> str:
    """Tikla -> yaz -> gorunur listeden TAM eslesmeyi sec.

    Eslesme yoksa dokunulmaz (sari). Donus: filled | skipped_unverified.
    """
    try:
        await loc.scroll_into_view_if_needed()
        await loc.click()
        await loc.press_sequentially(value, delay=15)
    except Exception:
        return "skipped_unverified"
    try:
        options = loc.page.get_by_role("option")
        await options.first.wait_for(state="visible", timeout=5000)
    except Exception:
        options = None
    if options is not None:
        try:
            total = await options.count()
        except Exception:
            total = 0
        want = value.strip().lower()
        for index in range(min(total, 50)):
            option = options.nth(index)
            try:
                if not await option.is_visible():
                    continue
                text = ((await option.inner_text()) or "").strip()
            except Exception:
                continue
            if text.lower() == want:
                try:
                    await option.click()
                except Exception:
                    break
                try:
                    await highlight(loc, GREEN)
                except Exception:
                    pass
                return "filled"
    try:
        await loc.page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await loc.fill("")
    except Exception:
        pass
    try:
        await highlight(loc, YELLOW)
    except Exception:
        pass
    return "skipped_unverified"

"""Lever application-site adapter (T6).

Kaynak (2026-10-06, jobs.lever.co/palantir/.../apply):
- form#application-form[method=POST]
- ad: TEK alan input[data-qa="name-input"][name="name"] (ad/soyad ayri degil)
- input[data-qa="email-input"][name="email"][type=email]
- input[data-qa="phone-input"][name="phone"]
- konum: input#location-input.location-input[data-qa="location-input"]
- sirket: input[data-qa="org-input"][name="org"]
- linkler: input[name="urls[LinkedIn]"] / urls[GitHub] / urls[Portfolio]
- ozel sorular: textarea.card-field-input[name="cards[<uuid>][field<N>]"],
  checkbox input[name="cards[<uuid>][field<N>]"] (uuid ilan basina degisir)
- on yazi: textarea#additional-information[name="comments"]
- CV: GIZLI input#resume-upload-input.application-file-input
  [data-qa="input-resume"][name="resume"][type=file] (tabindex=-1)
- submit: button#btn-submit[type=button][data-qa="btn-submit"]
  (JS ile gonderir; adapter TIKLAMAZ)
- cerez: button.cc-btn.cc-deny (reddet) / .cc-allow (kabul)

PREPARE-only: no submit() exists on adapters by design; submission stays
in BrowserAutomationEngine behind confirmed=True + FULL_AUTO.
"""
from browser.site_adapters.base import FieldSpec
from browser.site_adapters.generic import GenericAdapter as _Generic
from browser.site_adapters.resolve import ats_from_url


class LeverAdapter(_Generic):
    name = "lever"

    def matches(self, url: str) -> bool:
        return ats_from_url(url) == "lever"

    async def form_root(self, page):
        try:
            if await page.locator("form#application-form").count():
                return page.locator("form#application-form")
        except Exception:
            pass
        return page

    def field_specs(self) -> dict[str, FieldSpec]:
        return {
            "full_name": FieldSpec(
                selectors=('input[data-qa="name-input"]', 'input[name="name"]'),
                labels=("Full name", "Name",),
            ),
            "email": FieldSpec(
                selectors=('input[data-qa="email-input"]', 'input[name="email"]'),
                labels=("Email",),
            ),
            "phone": FieldSpec(
                selectors=('input[data-qa="phone-input"]', 'input[name="phone"]'),
                labels=("Phone",),
            ),
            "location": FieldSpec(
                selectors=('input[data-qa="location-input"]', "#location-input"),
                labels=("Location", "Current location",),
            ),
            "organization": FieldSpec(
                selectors=('input[data-qa="org-input"]', 'input[name="org"]'),
                labels=("Company", "Organization", "Current company",),
            ),
            "linkedin": FieldSpec(
                selectors=('input[name="urls[LinkedIn]"]',),
                labels=("LinkedIn",),
            ),
            "resume": FieldSpec(
                selectors=("#resume-upload-input", 'input[data-qa="input-resume"]'),
                labels=("Resume", "CV",),
                kind="file",
            ),
            "cover_letter": FieldSpec(
                selectors=("#additional-information", 'textarea[name="comments"]'),
                labels=("Cover letter", "Additional information",),
            ),
        }

    async def pre_fill(self, page) -> None:
        """Lever cerez bandi: yalnizca .cc-deny (reddet) tiklanir."""
        try:
            deny = page.locator("button.cc-btn.cc-deny").first
            if await deny.count() and await deny.is_visible():
                await deny.click()
                return
        except Exception:
            pass
        await super().pre_fill(page)

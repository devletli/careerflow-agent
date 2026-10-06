"""Greenhouse application-site adapter (T6).

Kaynak (2026-10-06, job-boards.greenhouse.io/example/jobs/44735):
- form#application-form.application--form
- input#first_name / #last_name / #email(type=text) / #phone(type=tel),
  hepsi aria-label'li; required = aria-required="true"
- konum: react-select combobox (input.select__input, etiketi Country/Location)
- resume/cover: gizli input#resume / input#cover_letter[type=file]
  (.visually-hidden) + Attach/Dropbox/paste dugmeleri
- ozel sorular: id'si ilan basina degisen input#question_<id>
  (etiketi aria-label/label'da, orn. "LinkedIn Profile")
- submit: .application--submit button[type=submit] (adapter TIKLAMAZ)

PREPARE-only: no submit() exists on adapters by design; submission stays
in BrowserAutomationEngine behind confirmed=True + FULL_AUTO.
"""
from browser.site_adapters.base import FieldSpec
from browser.site_adapters.generic import GenericAdapter as _Generic
from browser.site_adapters.resolve import ats_from_url


class GreenhouseAdapter(_Generic):
    name = "greenhouse"

    def matches(self, url: str) -> bool:
        return ats_from_url(url) == "greenhouse"

    async def form_root(self, page):
        try:
            if await page.locator("form#application-form").count():
                return page.locator("form#application-form")
        except Exception:
            pass
        return page

    def field_specs(self) -> dict[str, FieldSpec]:
        return {
            "first_name": FieldSpec(
                selectors=("#first_name", 'input[aria-label="First Name"]'),
                labels=("First Name",),
            ),
            "last_name": FieldSpec(
                selectors=("#last_name", 'input[aria-label="Last Name"]'),
                labels=("Last Name",),
            ),
            "email": FieldSpec(
                selectors=("#email", 'input[aria-label="Email"]'),
                labels=("Email", "E-mail",),
            ),
            "phone": FieldSpec(
                selectors=("#phone", 'input[aria-label="Phone"]'),
                labels=("Phone", "Telefon",),
            ),
            "location": FieldSpec(
                selectors=("input.select__input[role='combobox']",),
                labels=("Country", "Location",),
                kind="combobox",
            ),
            "resume": FieldSpec(
                selectors=("input#resume[type='file']",),
                labels=("Resume", "CV",),
                kind="file",
            ),
            "cover_letter": FieldSpec(
                selectors=("input#cover_letter[type='file']",),
                labels=("Cover Letter",),
                kind="file",
            ),
            # Soru id'leri ilan basina degisir; yalnizca etiketle cozulur.
            "linkedin": FieldSpec(
                labels=("LinkedIn Profile", "LinkedIn",),
            ),
        }

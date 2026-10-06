"""Ashby application-site adapter.

Kaynak (2026-10-06, jobs.ashbyhq.com/ashby/.../application; headless
Chromium ile render edilmis yapi):
- <form> YOK (React SPA, div tabanli); form_root varsayilani = page
- ad: input#_systemfield_name[name="_systemfield_name"][type=text],
  etiketi <label> baglantisinda ("Name")
- e-posta: input#_systemfield_email[type=email] (etiket "Email")
- CV: input#_systemfield_resume[type=file] (etiket "Resume")
- ozel metin: id/name'i ilan basina degisen UUID input/textarea
  (etiket yalnizca <label>'da: "LinkedIn URL", "GitHub URL", ...)
- konum: input.ashby-application-form-input-autocomplete
  (placeholder "Start typing...", combobox davranisi)
- Bilerek spec DIŞI: yas/cinsiyet/etnik koken/engellilik gibi
  EEO-demografik sorular (ozel kategori; ASLA otomatik doldurulmaz).

PREPARE-only: no submit() exists on adapters by design; submission stays
in BrowserAutomationEngine behind confirmed=True + FULL_AUTO.
"""
from browser.site_adapters.base import FieldSpec
from browser.site_adapters.generic import GenericAdapter as _Generic
from browser.site_adapters.resolve import ats_from_url


class AshbyAdapter(_Generic):
    name = "ashby"

    def matches(self, url: str) -> bool:
        return ats_from_url(url) == "ashby"

    def field_specs(self) -> dict[str, FieldSpec]:
        return {
            "full_name": FieldSpec(
                selectors=("input#__systemfield_name",
                           'input[name="_systemfield_name"]'),
                labels=("Name", "Legal name", "Full name",),
            ),
            "email": FieldSpec(
                selectors=("input#__systemfield_email",
                           'input[name="_systemfield_email"]'),
                labels=("Email",),
            ),
            # Kararli secici yok (UUID); etiketle cozulur.
            "phone": FieldSpec(
                labels=("Phone", "Phone number", "Telefon",),
            ),
            "linkedin": FieldSpec(
                labels=("LinkedIn URL", "LinkedIn",),
            ),
            "location": FieldSpec(
                selectors=("input.ashby-application-form-input-autocomplete",),
                labels=("Location", "Current location",),
                kind="combobox",
            ),
            "resume": FieldSpec(
                selectors=("input#__systemfield_resume[type='file']",),
                labels=("Resume", "CV",),
                kind="file",
            ),
        }

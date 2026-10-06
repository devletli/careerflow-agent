"""Workable application-site adapter.

Gercek sayfa kaydi henuz yok (ats_stats verisi + Faz 5 kaydedici
bekleniyor): yalnizca etiket esanlamlilari, UYDURULMUS secici yok.
Kayit alinca greenhouse.py/lever.py deseninde doldurulacak.
"""
from browser.site_adapters.base import FieldSpec
from browser.site_adapters.generic import GenericAdapter as _Generic
from browser.site_adapters.resolve import ats_from_url


class WorkableAdapter(_Generic):
    name = "workable"

    def matches(self, url: str) -> bool:
        return ats_from_url(url) == "workable"

    def field_specs(self) -> dict[str, FieldSpec]:
        return {
            "first_name": FieldSpec(labels=("First Name",)),
            "last_name": FieldSpec(labels=("Last Name",)),
            "email": FieldSpec(labels=("Email",)),
            "phone": FieldSpec(labels=("Phone",)),
            "resume": FieldSpec(labels=("Resume", "CV",), kind="file"),
            "cover_letter": FieldSpec(labels=("Cover Letter",), kind="file"),
        }

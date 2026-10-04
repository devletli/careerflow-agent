"""Gorev 6: frontend kaynak tarama yardimcisi.

page.js bilesenlere bolundu; kaynak-metin testleri artik app/ altindaki
tum .js dosyalarini birlestirerek tarar (kontrol gucu korunur).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "services" / "frontend" / "app"


def read_frontend_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(APP.rglob("*.js"))
    )

"""F2: STATUS_UX eksiksizlik sozlesmesi (statik, offline).

Ajan haritayi koddan cikarir; bu test eksigi yakalar. NOT: kaynak-metin
taramasi kirilgandir (yorumdaki ornek durum adlari yanlis pozitif
uretebilir); asil guc, harita anahtarlarini satir basi duzenli
ifadesiyle cikarmaktadir.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
UX = ROOT / "services" / "frontend" / "app" / "lib" / "statusUx.js"


def backend_statuses() -> set[str]:
    """Backend'in gercekten yazdigi durumlar: _mark() + PipelineStatus + execute."""
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in pathlib.Path(ROOT / "services").rglob("*.py")
        if "tests" not in p.parts
    )
    found = set(re.findall(r"_mark\([^)]*?[\"']([A-Z_]{4,})[\"']", src))
    found |= set(re.findall(r"PipelineStatus\.([A-Z_]{4,})", src))
    found |= set(re.findall(r"application\.status = [\"']([A-Z_]{4,})[\"']", src))
    found |= set(re.findall(r"status=\"([A-Z_]{4,})\"", src))
    # Yalnizca basvuru yasam dongusuyle ilgili olanlar (is/SMTP gürültüsü yok).
    app_level = {
        "CREATED", "DISCOVERED", "RUNNING", "FILLING", "FILLED", "SUBMITTING",
        "REQUIRES_HUMAN", "READY_TO_SUBMIT", "READY_TO_APPLY", "FAILED",
        "BLOCKED", "SUBMITTED",
    }
    return found & app_level


def ux_keys() -> set[str]:
    text = UX.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{2}([A-Z_]{4,}):", text, re.MULTILINE))


def test_every_backend_status_has_ux_entry():
    missing = [s for s in sorted(backend_statuses()) if s not in ux_keys()]
    assert not missing, f"statusUx.js'te eksik durumlar: {missing}"


def test_every_ux_entry_has_label_and_next():
    text = UX.read_text(encoding="utf-8")
    for key in sorted(ux_keys()):
        block = re.search(rf"{key}:\s*\{{\s*([^}}]+)\}}", text)
        assert block, f"{key} blogu cozulemedi"
        assert 'key: "status.' in block.group(1), f"{key} i18n anahtari yok"
        assert "next:" in block.group(1) and "tone:" in block.group(1), f"{key} next/tone yok"


def test_every_ux_label_translated_tr_en():
    text = UX.read_text(encoding="utf-8")
    dotted = set(re.findall(r'key:\s*"([^"]+)"', text))
    en = json.loads((ROOT / "services" / "frontend" / "i18n" / "en.json").read_text(encoding="utf-8"))
    tr = json.loads((ROOT / "services" / "frontend" / "i18n" / "tr.json").read_text(encoding="utf-8"))

    def _lookup(d, dotted_key):
        node = d
        for part in dotted_key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node

    missing = [k for k in sorted(dotted) if not _lookup(en, k) or not _lookup(tr, k)]
    assert not missing, f"cevrilmemis durum etiketleri: {missing}"


def test_unknown_status_falls_back_without_crash():
    text = UX.read_text(encoding="utf-8")
    assert "UNKNOWN_UX" in text, "bilinmeyen durum yedegi yok"
    assert "statusUxFor" in text, "statusUxFor yardimcisi yok"

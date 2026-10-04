"""GOREV 2c: yerel kaynak klasoru testleri (offline).

Kapsar: klasorun gitignore'da olmasi, dosya turu okuma (.md/.txt/.docx/.pdf),
evidence'nin SADECE kendi dosyasinda aranmasi, tarih cakismasinda `conflict`
+ CV'nin kazanmasi, iletisim bilgisinin LLM baglamina sizmamasi (sahte istemci),
role_fit secimi ve select_facts onceligi.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingest = _load("ingest_facts_local_under_test", "scripts/ingest_facts.py")
review = _load("review_facts_local_under_test", "scripts/review_facts.py")

CV_TEXT = """Aday Deneme
Senior DevOps Engineer with 8 years of experience in Kubernetes and Terraform.
Ilesitim: aday@example.com, +49 170 1111111
Adres: Musterstrasse 12, 10115 Berlin
Calisti: BankPozitif 2019 - 2023 yillari arasinda uygulama yoneticisi olarak.
"""


def _write_sources(tmp_path, files=None):
    base = tmp_path / "sources"
    base.mkdir()
    for name, content in (files or {"cv.md": CV_TEXT}).items():
        (base / name).write_text(content, encoding="utf-8")
    return base


def test_kaynak_klasoru_gitignoreda():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "profile/sources" in gitignore
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", "profile/sources/x.md"],
            cwd=ROOT,
            capture_output=True,
        )
    except FileNotFoundError:
        pytest.skip("git yok")
    assert proc.returncode == 0, "profile/sources gitignore'da olmali"


def test_md_txt_okuma_ve_redaksiyon(tmp_path):
    base = _write_sources(tmp_path)
    (base / "not.txt").write_text("Python ve Docker ile 6 yillik deneyim sahibi uzman mühendis.", encoding="utf-8")
    sources = ingest.read_local_sources(str(base))
    tags = {s["tag"] for s in sources}
    assert tags == {"cv:cv.md", "cv:not.txt"}
    cv = next(s for s in sources if s["tag"] == "cv:cv.md")
    assert "aday@example.com" in cv["raw"]  # ham metin korunur (evidence icin)
    for leak in ("aday@example.com", "+49 170 1111111", "Musterstrasse 12"):
        assert leak not in cv["safe"]  # LLM'e gidecek metin temiz


def test_docx_okuma(tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    base = tmp_path / "sources"
    base.mkdir()
    doc = Document()
    doc.add_paragraph("Senior ALM Consultant with Jenkins and Jira expertise in banking.")
    doc.save(str(base / "cv.docx"))
    sources = ingest.read_local_sources(str(base))
    assert len(sources) == 1 and sources[0]["tag"] == "cv:cv.docx"
    assert "Jenkins" in sources[0]["raw"]


def test_pdf_okuma(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    base = tmp_path / "sources"
    base.mkdir()
    path = str(base / "cv.pdf")
    page = canvas.Canvas(path)
    page.drawString(72, 720, "Platform Engineer with Prometheus and Grafana experience.")
    page.save()
    sources = ingest.read_local_sources(str(base))
    assert len(sources) == 1 and sources[0]["tag"] == "cv:cv.pdf"
    assert "Prometheus" in sources[0]["raw"]


def test_evidence_baska_dosyada_gecerse_atilir():
    ok = {"title": "t", "evidence": "Kubernetes and Terraform", "source_doc": "cv:cv.md"}
    accepted, _ = ingest.validate_proposals([ok], {"cv:cv.md": "Kubernetes and Terraform"})
    assert len(accepted) == 1
    cross = {"title": "t", "evidence": "Kubernetes and Terraform", "source_doc": "cv:diger.md"}
    accepted, rejected = ingest.validate_proposals([cross], {"cv:cv.md": "Kubernetes and Terraform"})
    assert accepted == [] and len(rejected) == 1


def test_iletisim_evidence_havuza_girmez():
    proposal = {
        "title": "t",
        "evidence": "Iletisim: aday@example.com, +49 170 1111111",
        "source_doc": "cv:cv.md",
    }
    sources = {"cv:cv.md": "Iletisim: aday@example.com, +49 170 1111111"}
    accepted, rejected = ingest.validate_proposals([proposal], sources)
    assert accepted == [] and rejected[0]["reject_reason"] == "kanit havuzuna iletisim bilgisi girmez"


def test_tarih_cakismasi_conflict_uretir_cv_kazanir():
    facts = [
        {"title": "Founder Huzur AS", "period": "2021 - Present", "source": "website", "source_doc": "site"},
        {"title": "Founder  Huzur  AS", "period": "2020 - Present", "source": "cv", "source_doc": "cv:cv.pdf"},
    ]
    merged = ingest.detect_date_conflicts(facts)
    assert len(merged) == 1
    assert merged[0]["period"] == "2020 - Present"  # CV kazanir
    assert {c["period"] for c in merged[0]["conflict"]} == {"2021 - Present", "2020 - Present"}
    # Cakisma yoksa conflict anahtari uretilmez.
    plain = ingest.detect_date_conflicts([{"title": "X", "period": "2020", "source_doc": "cv:a"}])
    assert "conflict" not in plain[0]


def test_llm_istemine_telefon_eposta_gitmez():
    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt):
            self.prompts.append(prompt)
            return "ok"

    sources = [{"tag": "cv:cv.md", "raw": CV_TEXT, "safe": ingest.redact_for_llm(CV_TEXT)}]
    llm = FakeLLM()
    llm.complete(ingest.build_llm_context(sources))
    assert llm.prompts and len(llm.prompts) == 1
    for leak in ("aday@example.com", "+49 170 1111111", "Musterstrasse 12"):
        assert leak not in llm.prompts[0]
    assert "Kubernetes" in llm.prompts[0]  # icerik korunur, sadece PII gider


def test_role_fit_sorusu():
    answers = iter(["consultant"])
    assert review.prompt_role_fit({"title": "t"}, input_fn=lambda _: next(answers)) == ["consultant"]
    answers = iter([""])
    assert review.prompt_role_fit(
        {"title": "t", "role_fit": ["engineer"]}, input_fn=lambda _: next(answers)
    ) == ["engineer"]


def test_select_facts_rol_onceligi():
    facts = [
        {"title": "ALM danismanlik", "role_fit": ["consultant"]},
        {"title": "Python gelistirme", "role_fit": ["engineer"]},
    ]
    eng = ingest.select_facts(facts, "Senior Python Engineer", "Kubernetes Docker Terraform")
    assert eng[0]["title"] == "Python gelistirme"
    con = ingest.select_facts(facts, "ALM Consultant", "strateji yönetişim mentor")
    assert con[0]["title"] == "ALM danismanlik"
    # Beraberlikte sira bozulmaz.
    same = ingest.select_facts(facts, "Genel ilan", "ofis calismasi")
    assert [f["title"] for f in same] == ["ALM danismanlik", "Python gelistirme"]

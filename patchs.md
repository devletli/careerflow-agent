ROL
careerflow-agent reposunda çalışan kıdemli backend/test/DevOps mühendisisin.
"yama temizlik 2–8" tamamlandı. Şimdi (A) temizlik doğrulamasında çıkan açıkları kapat ve
(B) kalan güvenlik/kalite iyileştirmelerini yap. Yeni özellik ekleme.

═══ DEĞİŞMEZ KURALLAR ═══
- security.md ve README "Design Principles" bağlayıcı. PREPARE_APPLICATION varsayılanı, onay token'ı akışı,
  submit koruması (FULL_AUTO + AUTO_SUBMIT), CAPTCHA/MFA hard-stop DEĞİŞMEZ.
- Skor deterministik kalır; LLM skoru ve QUALIFIED/REVIEW kararını değiştiremez.
- OPENAI_API_KEY / ANTHROPIC_API_KEY'i SİLME (shared/llm/client.py kullanıyor).
- Hiçbir testi zayıflatma, skip'leme veya assert'i gevşetme. Gevşetme gerekiyorsa DUR ve gerekçeyle sor.
- Mevcut Alembic migration'larını (001–007) düzenleme; gerekirse 008 ekle.
- Her görev ayrı commit (`yama temizlik 9<x>: ...`); commit öncesi `python -m pytest -q` ve `ruff check .` yeşil.
- Önce 15 satırı geçmeyen plan sun. Şema veya submit yoluna dokunan adımda DUR ve onay iste.
- Ortam: Windows PowerShell + Docker; komutları PowerShell uyumlu ver.

══════════════════════════════════════════
BÖLÜM A — TEMİZLİK DOĞRULAMASINDAN KALANLAR
══════════════════════════════════════════

A1. Kopya fixture ve test kontrolü (temizlik 1 hiç yapılmamış görünüyor)
Şüpheli ikililer: tests/fixtures/forms/{captcha,with_captcha}.html, {login_wall,with_login}.html,
tests/fixtures/application_form.html ~ tests/fixtures/forms/simple.html.
```powershell
Get-FileHash tests/fixtures/forms/captcha.html, tests/fixtures/forms/with_captcha.html
Get-FileHash tests/fixtures/forms/login_wall.html, tests/fixtures/forms/with_login.html
Get-FileHash tests/fixtures/application_form.html, tests/fixtures/forms/simple.html
git grep -n -E "with_captcha|with_login|simple\.html|application_form\.html|captcha\.html|login_wall\.html" -- tests
python -m pytest --collect-only -q | Select-Object -Last 3
```
Kural: içerik BİREBİR aynı ve yalnızca biri referanslanıyorsa kullanılmayanı `git rm`. Farklıysa silme,
farkı rapora yaz. Silme öncesi/sonrası toplanan test sayısı AYNI kalmalı (fixture silmek test sayısını
değiştirmez; düşerse bir test dosyayı kaybetmiştir, geri al).
test_application_center.py ile test_application_actions.py: önceki turda ikisi 317 satırdı, şimdi
center −23 satır. Kalan ortak test fonksiyonu adlarını karşılaştır; aynı isimli ve aynı gövdeli testleri tek yerde bırak:
```powershell
git grep -n "^def test_\|^async def test_" -- tests/integration/test_application_center.py tests/integration/test_application_actions.py
```

A2. docs/archive içerikleri bozulmuş (yama.md 289→104, GuiYama.md 51→379 satır)
`git mv` içeriği değiştirmez; burada içerik yeniden yazılmış. Orijinalleri geri getir:
```powershell
git show c44cda6:yama.md     | Set-Content -Encoding utf8 docs/archive/yama.md
git show c44cda6:GuiYama.md  | Set-Content -Encoding utf8 docs/archive/GuiYama.md
```
Eğer 379 satırlık GuiYama içeriği bilinçli bir özet/rapor ise onu `docs/archive/CLEANUP_SUMMARY.md` adıyla
AYRI dosyaya taşı; arşiv dosyaları orijinal içerikle kalsın. README'deki "GuiYama temizlik özeti" satırını
yeni yola yönlendir. Doğrulama: `git diff --stat c44cda6 HEAD -- docs/archive` içinde yama.md ve 9_10.md için
"0 değişiklik rename" görünmeli.

A3. e2e locator değişikliği test gücünü düşürmüş mü?
```powershell
git --no-pager show 4f70bcd -- tests/browser/test_dashboard_e2e.py
git --no-pager diff c44cda6 HEAD -- tests/unit/test_frontend_contract.py tests/unit/_frontend_src.py
```
Beklenen: 3 viewport'ta (1280/1024/390) 6 sekmenin her biri HÂLÂ `toBeVisible()` ile doğrulanıyor,
locator sıkı (exact):
```ts
for (const name of ["Overview", "Jobs", "Applications", "Documents", "Events", "Settings"]) {
  await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
}
```
`.first()`, kısmi metin eşleşmesi, `force: true` veya görünürlük kontrolünün kaldırıldığını görürsen geri al ve
asıl nedene (gerçek bir UI hatası) çözüm üret. Frontend sözleşme testlerinin (_frontend_src.py birleşik
kaynağı tarayan testler) arama kapsamını DARALTMADIĞINI doğrula: eski assert sayısı = yeni assert sayısı.

A4. OpenAPI yüzeyi değişmedi güvencesi (kalıcı snapshot testi)
```python
# tests/unit/test_openapi_surface.py
import json, os, pathlib
from services.api.app.main import app     # gerçek import yolunu koda göre kullan

SNAP = pathlib.Path("tests/snapshots/openapi_surface.json")

def current_surface() -> list[list[str]]:
    return sorted([p, m.upper()] for p, v in app.openapi()["paths"].items() for m in v)

def test_openapi_surface_unchanged():
    cur = current_surface()
    if os.environ.get("UPDATE_SNAPSHOT") == "1":
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    assert SNAP.exists(), "snapshot yok: UPDATE_SNAPSHOT=1 ile bir kez üret"
    assert cur == json.loads(SNAP.read_text(encoding="utf-8")), "API route yüzeyi değişti"
```
Snapshot'ı ÖNCE eski commit'ten üret (router bölmesinden önceki hal) ve karşılaştır:
```powershell
git worktree add ../careerflow-old c44cda6
Push-Location ../careerflow-old
$env:UPDATE_SNAPSHOT="1"; python -m pytest tests/unit/test_openapi_surface.py -q   # önce testi buraya kopyala
Copy-Item tests/snapshots/openapi_surface.json ../snapshot_old.json
Pop-Location; git worktree remove ../careerflow-old
Copy-Item ../snapshot_old.json tests/snapshots/openapi_surface.json
Remove-Item Env:UPDATE_SNAPSHOT
python -m pytest tests/unit/test_openapi_surface.py -q
```
Test geçmiyorsa kaybolan/eklenen route'u listele ve rapora yaz (bilinçli eklenenler hariç düzelt).

A5. CI güncelle (ci.yml temizlik sırasında hiç değişmemiş)
`${VAR:?}` boş değişkende compose'u kırar. Sahte sırlarla .env üret, yeni testleri ve frontend'i de çalıştır:
```yaml
# .github/workflows/ci.yml
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ./shared pytest pytest-asyncio aiosqlite ruff mypy
      - run: ruff check .
      - run: python -m pytest -m "not live" -q
      - name: compose config
        shell: bash
        run: |
          cp .env.example .env
          for k in POSTGRES_PASSWORD MINIO_ACCESS_KEY MINIO_SECRET_KEY API_KEY; do
            sed -i "s|^$k=.*|$k=ci-$(openssl rand -hex 8)|" .env
          done
          docker compose config -q
  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: services/frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: services/frontend/package-lock.json }
      - run: npm ci
      - run: npx eslint .
      - run: npm run build
```
Önce mevcut ci.yml'yi oku; zaten böyle yapan adım varsa tekrarlama. Playwright e2e testlerini CI'a
yalnızca stack kolay kalkıyorsa ekle; aksi halde `-m "not live and not e2e"` ile hariç tut ve README'ye yaz.

A6. README temizliği
- "Migration skew" maddesi (Remaining Risks) ortak image ile çözüldüyse KALDIR.
- Router yapısı ve `scripts/backfill_document_application_link.py` kullanımı için kısa bölüm ekle.
- `git grep -n "yama.md\|9_10.md\|GuiYama.md"`: tüm referanslar docs/archive/ yolunu göstersin.

A7. (Düşük öncelik) routers/applications.py 660 satır
Davranış değişmeden üçe böl: applications_core.py (liste/detay), applications_actions.py (execute/confirm),
applications_documents.py (belge bağlama). Router seviyesinde api-key bağımlılığı HER birinde olsun;
A4 snapshot ve test_all_routes_auth testi yeşil kalsın.

══════════════════════════════════════════
BÖLÜM B — KALAN İYİLEŞTİRMELER
══════════════════════════════════════════

B1. Sert kapılar: skor yüksek olsa bile riskli ilan QUALIFIED'a girmesin
Konum: services/job-matching/app/matcher.py (ve worker'ın bandı belirlediği yer). Kapılar yalnızca
QUALIFIED → REVIEW'a düşürür (asla otomatik reddetmez), gerekçeler eşleşme kaydına yazılır.
```python
# shared/matching/gates.py   (yeni dosya)
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class Gate:
    name: str
    pattern: re.Pattern[str]
    profile_key: str          # profile.yaml -> "satisfies" altındaki anahtar

GATES: tuple[Gate, ...] = (
    Gate("german_c1", re.compile(
        r"(verhandlungssicher|fließend|fliessend)\w*\s+deutsch|deutsch\s*(c1|c2|muttersprach\w*)", re.I), "german_c1"),
    Gate("senior_title", re.compile(r"\b(senior|lead|principal|head of|staff)\b", re.I), "senior"),
    Gate("security_clearance", re.compile(
        r"sicherheits(überprüfung|check)|security clearance|ü2|ü3", re.I), "clearance"),
)

def evaluate_gates(job_text: str, title: str, satisfies: dict[str, bool]) -> list[str]:
    haystack = f"{title}\n{job_text}"
    return [g.name for g in GATES if g.pattern.search(haystack) and not satisfies.get(g.profile_key, False)]

def apply_gates(band: str, hits: list[str]) -> str:
    return "REVIEW" if (band == "QUALIFIED" and hits) else band
```
Profile şeması: profile.example.yaml'a `satisfies: {german_c1: false, senior: false, clearance: false}`
ekle ve loader'da (shared/profile/loader.py) varsayılan `False` ile oku. Eşleşme açıklamasına/JSON'a
`gate_hits` yaz (şema değişikliği gerekiyorsa DUR ve onay iste; mevcut JSON alanına yazmak yeterliyse migration yok).
Testler (tests/unit/test_match_gates.py):
```python
import pytest
from shared.matching.gates import evaluate_gates, apply_gates

@pytest.mark.parametrize("text,title,expected", [
    ("Wir erwarten verhandlungssicheres Deutsch", "Python Developer", ["german_c1"]),
    ("Fließend Deutsch erforderlich", "Backend Engineer", ["german_c1"]),
    ("Python, FastAPI", "Senior Backend Engineer", ["senior_title"]),
    ("Python, FastAPI", "Backend Engineer", []),
])
def test_gates(text, title, expected):
    assert evaluate_gates(text, title, {}) == expected

def test_gate_never_rejects_only_downgrades():
    assert apply_gates("QUALIFIED", ["senior_title"]) == "REVIEW"
    assert apply_gates("REVIEW", ["senior_title"]) == "REVIEW"
    assert apply_gates("NOT_QUALIFIED", ["senior_title"]) == "NOT_QUALIFIED"

def test_satisfied_gate_is_ignored():
    assert evaluate_gates("Fließend Deutsch", "Dev", {"german_c1": True}) == []
```
Golden-set etkisi: tests/golden/jobs.jsonl satırlarından kapıya takılanlar varsa beklenen sınıfları
GİZLEMEDEN güncelle ve README "Match-score calibration" tablosunu yeniden üret; farkı raporla.

B2. Onay token'ı atomik tüketilsin (çift kullanımı engelle)
Konum: services/api/app/confirmations.py (+ tests/unit/test_confirmations.py, test_submit_confirmation.py).
Önce token'ın NEREDE saklandığını oku (Redis mi, DB mi, bellek mi). Bellek içi/process-local ise ve API
birden fazla worker/replica ile çalışabiliyorsa Redis'e taşı. Redis seçeneği:
```python
# services/api/app/confirmations.py
async def consume(redis, token: str, action: str, application_id: str) -> bool:
    raw = await redis.getdel(f"confirm:{token}")        # okuma + silme TEK atomik komut
    if raw is None:
        return False
    stored = raw.decode() if isinstance(raw, bytes) else raw
    return stored == f"{action}:{application_id}"
```
DB seçeneği (tek UPDATE ... RETURNING, yarış yok):
```python
stmt = (
    update(Confirmation)
    .where(Confirmation.token_hash == h, Confirmation.consumed_at.is_(None),
           Confirmation.expires_at > func.now(),
           Confirmation.action == action, Confirmation.application_id == app_id)
    .values(consumed_at=func.now())
    .returning(Confirmation.id)
)
ok = (await session.execute(stmt)).first() is not None
```
Token düz metin saklanmasın (sha256 hash). Yarış testi:
```python
import asyncio, pytest

@pytest.mark.asyncio
async def test_token_single_use_under_concurrency(store, app_id):
    token = await store.mint("submit", app_id)
    results = await asyncio.gather(*[store.consume(token, "submit", app_id) for _ in range(20)])
    assert results.count(True) == 1
```
Ek testler: yanlış action, yanlış application_id, süresi dolmuş (5 dk), token'ın loglarda geçmediği.

B3. Boş zorunlu sırlar HER ortamda startup hatası
Konum: shared/config.py (Settings doğrulayıcısı). Compose zaten `${VAR:?}` ile zorunlu kılıyor, ama
compose dışında çalışan süreçler (testler, scripts) için Settings da reddetsin. Zayıf-değer listesi yalnızca prod'da.
```python
WEAK = {"change_me", "changeme", "password", "minioadmin", "admin", "secret", "test"}
REQUIRED_SECRETS = ("POSTGRES_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "API_KEY")

@model_validator(mode="after")
def _secrets(self):
    for name in REQUIRED_SECRETS:
        v = getattr(self, name, None)
        raw = v.get_secret_value() if hasattr(v, "get_secret_value") else v
        if not raw:
            raise ValueError(f"{name} boş olamaz (.env doldurulmalı)")
        if self.ENV == "prod" and raw.lower() in WEAK:
            raise ValueError(f"{name} zayıf/varsayılan değer")
    return self
```
Test ortamı için tests/conftest.py'de sahte sırları env'e koy (autouse fixture, monkeypatch); mevcut
testlerin kırılmaması için bunu önce uygula, sonra doğrulayıcıyı aç. Yeni test: her sır için boş değerde
`ValidationError`, prod'da `minioadmin` reddi, dev'de güçlü değer kabulü. Settings'in secret alanlarını
(`API_KEY` vb.) `SecretStr` yaptığını ve repr/log'da maskelendiğini doğrula.

B4. JSON log varsayılan + correlation_id
Konum: shared/infra/jsonlog.py, shared/config.py (LOG_FORMAT), shared/contracts/events.py,
her worker'ın mesaj tüketim noktası (shared/infra/redis_bus.py).
- `LOG_FORMAT` varsayılanı `json`; `text` yalnızca geliştirme için (`LOG_FORMAT=text`).
- correlation_id contextvar ile tüm log satırlarına otomatik eklensin:
```python
# shared/infra/jsonlog.py
import contextvars, json, logging
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")

class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(r), "level": r.levelname, "svc": r.name,
                   "msg": r.getMessage(), "correlation_id": correlation_id.get()}
        payload.update(getattr(r, "ctx", {}))
        return json.dumps(payload, ensure_ascii=False)
```
```python
# redis_bus.py — mesaj işlenmeden hemen önce
token = correlation_id.set(event.correlation_id or event.idempotency_key or "-")
try:
    await handler(event)
finally:
    correlation_id.reset(token)
```
API tarafında middleware: `X-Correlation-ID` başlığını al/üret, contextvar'a yaz, yanıta ekle.
PII redaksiyon filtresi (shared/infra/pii.py) JSON handler'ına bağlı kalsın. Testler (test_jsonlog.py'yi
GENİŞLET, zayıflatma): varsayılan format json, her satırda correlation_id, redaksiyon hâlâ çalışıyor,
bir olay işlenirken üretilen iki farklı log satırı aynı correlation_id'yi taşıyor.

B5. Gerçek veriyle kalibrasyon (held-out) altyapısı
AJAN İLAN ETİKETLEYEMEZ ve etiket UYDURMAZ; yalnızca altyapıyı kurar. Etiketleri kullanıcı verecek.
- tests/golden/real_labeled.example.jsonl: şema örneği (3 satır, açıkça "ÖRNEK" etiketli, gerçek profil yok).
- Gerçek dosya `tests/golden/real_labeled.jsonl` .gitignore'a eklensin (kişisel etiketler repoya girmesin).
- scripts/calibrate.py: dosyayı okur, eşik taraması yapar, sınıf başına precision/recall basar ve
  veriyi %70 kalibrasyon / %30 held-out ayırır (sabit seed):
```python
# scripts/calibrate.py
import json, random, sys
from pathlib import Path
from shared.matching import score_job          # gerçek matcher giriş noktasını koda göre kullan

def load(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

def band(score, t):  # QUALIFIED >= t, REVIEW [t-10, t)
    return "QUALIFIED" if score >= t else "REVIEW" if score >= t - 10 else "NOT_QUALIFIED"

def main(path="tests/golden/real_labeled.jsonl"):
    rows = load(path)
    random.Random(42).shuffle(rows)
    cut = int(len(rows) * 0.7)
    cal, held = rows[:cut], rows[cut:]
    scored = [(r, score_job(r["job"])) for r in rows]
    for t in range(70, 96, 5):
        for name, subset in (("cal", cal), ("held", held)):
            pred = [(r["label"], band(score_job(r["job"]), t)) for r in subset]
            q = [(l, p) for l, p in pred if p == "QUALIFIED"]
            prec = sum(l == "QUALIFIED" for l, _ in q) / len(q) if q else float("nan")
            print(f"T={t} {name}: qualified_precision={prec:.2f} n_qualified={len(q)}")
main(*sys.argv[1:])
```
- `make calibrate` hedefi ekle. Test (tests/golden/test_real_calibration.py): dosya VARSA held-out
  QUALIFIED precision >= 0.9 aranır; dosya YOKSA test açık bir `pytest.skip("real_labeled.jsonl yok: kullanıcı etiketlemeli")`
  mesajıyla atlanır (sessiz geçmez).
- README "Match-score calibration" bölümüne uyarı ekle: mevcut tablo sentetik sette, gerçek ilanlarla
  doğrulanmadı; eşik değiştirilmeden önce `make calibrate` çalıştırılmalı.
- MIN_MATCH_SCORE uyarı eşiğini (>=95) olduğu gibi bırak ama gerekçesini config yorumuna yaz.

══════════════════════════════════════════
ÇALIŞMA DÜZENİ VE KABUL
══════════════════════════════════════════
Sıra: A1 → A2 → A3 → A4 → A5 → A6 → B3 → B2 → B4 → B1 → B5 → (A7 isteğe bağlı).
Her görevden sonra: `python -m pytest -q`, `ruff check .`, `docker compose config -q`.
B1/B2/B4 sonrası stack'i kaldır: `docker compose up --build -d`, `docker compose ps` (tüm servisler healthy),
`python scripts/smoke.py <API_KEY>`.

Kabul kriterleri:
- Fixture/test kopyası kalmadı, toplanan test sayısı gerekçeli; docs/archive/yama.md ve 9_10.md orijinal içerikte.
- e2e: 3 viewport × 6 sekme `exact` locator ile görünür; frontend sözleşme testlerinin assert sayısı düşmedi.
- tests/unit/test_openapi_surface.py yeşil ve snapshot eski commit'ten üretildi.
- CI: sahte sırlarla compose config, backend+frontend job'ları yeşil.
- Kapılar yalnızca QUALIFIED→REVIEW yapıyor; golden/README tablosu yeniden üretildi.
- Onay token'ı eşzamanlı 20 denemede tam 1 kez geçerli.
- Boş zorunlu sır her ortamda startup hatası; testler sahte env ile yeşil.
- Varsayılan log formatı json, her satırda correlation_id.
- scripts/calibrate.py ve `make calibrate` çalışıyor; gerçek etiket dosyası gitignore'da.

FINAL RAPOR: değişen/silinen dosyalar (neden güvenli), test sayısı öncesi/sonrası, openapi snapshot sonucu,
golden-set farkı, kalan riskler. Kullanıcıdan beklenen tek şey: tests/golden/real_labeled.jsonl için
20–30 gerçek ilanı elle etiketlemek (QUALIFIED/REVIEW/NOT_QUALIFIED).
ROL
Bu repoda (careerflow-agent) çalışan kıdemli backend/DevOps/frontend mühendisisin.
Amaç: (1) neyin ÇALIŞMADIĞINI kanıtla, (2) eksikleri tamamla, (3) kodu/dokümanı tutarlı ve
güvenli hale getir. Önce çalıştır ve ölç, sonra düzelt.

═══ DEĞİŞMEZ KURALLAR ═══
- security.md ve README "Design Principles" bağlayıcı.
- Skor deterministik; LLM skoru değiştiremez, aday hakkında bilgi uyduramaz.
- AUTOMATION_MODE=PREPARE_APPLICATION varsayılanı, "Gönder" onayı, AUTO_SUBMIT+FULL_AUTO şartı,
  CAPTCHA/MFA/login-wall hard-stop DEĞİŞMEZ. Bu yollara dokunmadan önce karakterizasyon testi yaz.
- Mevcut Alembic migration'larını düzenleme, yenisini ekle. MinIO private kalır.
- Gerçek iş sitelerine submit yapan test yazma. Tek kullanıcılı yerel araç: gereksiz karmaşıklık ekleme.
- Silmeden önce kullanılmadığını kanıtla (dinamik çağrı, event handler, Phase 9 planı).

═══ FAZ 0 — ÇALIŞTIR VE ÖLÇ (kod değiştirmeden) ═══
1. `docker compose config -q`, sonra `docker compose up --build -d`, `docker compose ps`,
   her servis için `docker compose logs --tail=100 <svc>`.
2. `pytest -q` çalıştır (Windows'a bağımlı olmadan). Başarısız/atlanan testleri listele.
3. Uçtan uca duman testi: tek sahte ilan ile discovery→matching→documents→analyzer→ready
   zincirini tetikle, her aşamanın pipeline_events kaydını kontrol et.
4. Çıktı: "Çalışıyor / Çalışmıyor / Doğrulanamadı" tablosu (servis ve aşama bazında, kanıtla).
   Bu tablo olmadan Faz 1'e geçme.

```python
# scripts/smoke.py  — çalıştırılabilir duman testi (gerçek siteye gitmez)
import sys, time, httpx

BASE, KEY = "http://127.0.0.1:8000", sys.argv[1] if len(sys.argv) > 1 else ""
H = {"X-API-Key": KEY} if KEY else {}

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    return ok

with httpx.Client(base_url=BASE, headers=H, timeout=10) as c:
    ok = check("health", c.get("/health").status_code == 200)
    st = c.get("/api/v1/status")
    ok &= check("status", st.status_code == 200, st.text[:200])
    for path in ("jobs", "applications", "events"):
        r = c.get(f"/api/v1/{path}")
        ok &= check(path, r.status_code == 200)
sys.exit(0 if ok else 1)
```

═══ FAZ 1 — YAPILANDIRMA VE TUTARLILIK (P0) ═══
A) `.env.example` düzelt: "#test commit" satırını sil, bileşen şifrelerini tek yerde tut,
   varsayılan şifreleri boş bırak (zorunlu), kullanılmayan anahtarları kaldır VEYA sağlayıcı
   soyutlaması gerçekten varsa belgele.

```dotenv
POSTGRES_DB=jobagent
POSTGRES_USER=jobagent
POSTGRES_PASSWORD=            # zorunlu, boş bırakma
# DATABASE_URL compose içinde yukarıdaki değişkenlerden türetilir
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=             # zorunlu
MINIO_SECRET_KEY=             # zorunlu
MINIO_BUCKET=job-agent-private
API_KEY=                      # zorunlu (dashboard→API)
LLM_PROVIDER=gemini
LLM_MODEL=                    # açılışta doğrulanır (aşağıya bak)
GEMINI_API_KEY=
MIN_MATCH_SCORE=70            # GEÇİCİ; golden-set ile kalibre edilecek
AUTOMATION_MODE=PREPARE_APPLICATION
AUTO_SUBMIT=false
```

```yaml
# docker-compose.yml
x-db-url: &db_url postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD:?set}@postgres:5432/${POSTGRES_DB}
services:
  api:
    environment:
      DATABASE_URL: *db_url
    ports: ["127.0.0.1:8000:8000"]
  minio:
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:?set}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:?set}
    ports: ["127.0.0.1:9001:9001"]
  postgres:
    ports: []
  redis:
    ports: []
```

B) Tek ayar sınıfı + açılış doğrulaması. MIN_MATCH_SCORE gerçekçi değilse uyar:

```python
# shared/settings.py
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
log = logging.getLogger("settings")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    redis_url: str
    api_key: SecretStr
    llm_provider: str = "gemini"
    llm_model: str = ""
    gemini_api_key: SecretStr | None = None
    min_match_score: int = 70
    automation_mode: str = "PREPARE_APPLICATION"
    auto_submit: bool = False

    @model_validator(mode="after")
    def sane(self):
        if not 0 <= self.min_match_score <= 100:
            raise ValueError("MIN_MATCH_SCORE 0-100 olmalı")
        if self.min_match_score >= 90:
            log.warning("MIN_MATCH_SCORE=%s çok yüksek; QUALIFIED sayısı ~0 olabilir", self.min_match_score)
        if self.auto_submit and self.automation_mode != "FULL_AUTO":
            raise ValueError("AUTO_SUBMIT yalnızca AUTOMATION_MODE=FULL_AUTO ile geçerli")
        return self
```

C) LLM model adını açılışta doğrula (`gemini-3.6-flash` geçerli mi KANITLA; bu adı varsayma).
   Geçersizse net hata logla ve deterministik moda geç, sessizce yutma:

```python
from google import genai

def resolve_model(client: genai.Client, wanted: str) -> str | None:
    available = {m.name.removeprefix("models/") for m in client.models.list()}
    if wanted in available:
        return wanted
    log.error("LLM_MODEL=%r geçersiz. Kullanılabilir flash modeller: %s",
              wanted, sorted(n for n in available if "flash" in n))
    return None   # None => LLM açıklaması kapalı, skor deterministik devam eder
```
   (SDK API şeklini sürüme göre doğrula.) Dashboard Settings/Overview'da "LLM: aktif/devre dışı (neden)"
   göstergesi ekle.

D) Kullanılmayan env/config (OPENAI/ANTHROPIC anahtarları, vb.) kod taramasıyla doğrula; kullanılmıyorsa sil.
E) Bağlayıcı bayraklar: README 5 discovery connector (Workable/Greenhouse/Lever/Ashby/SmartRecruiters)
   diyor ama env'de yalnızca WORKABLE_*. Her connector için `<NAME>_ENABLED` bayrağı ekle,
   varsayılanlar README ile aynı olsun, orchestrator hangi connector'ün aktif olduğunu açılışta loglasın.
F) `.gitignore`: `*.pdf` kuralına istisna ekle: `!tests/fixtures/**/*.pdf`. Örnek dosyalar:
   `profile/profile.example.yaml`, `profile/preferences.example.yaml` (yoksa oluştur, README'den bağla).

═══ FAZ 2 — DASHBOARD (P0) ═══
A) Navigasyon: sekmeler TEK diziden üretilsin, aktif sekme URL'den hesaplansın, dar ekranda
   kaydırılabilir olsun. Rota listesi ile README aynı olsun (Overview, Jobs, Applications,
   Documents, Events, Settings).

```tsx
export const NAV = [
  { href: "/", key: "nav.overview" }, { href: "/jobs", key: "nav.jobs" },
  { href: "/applications", key: "nav.applications" }, { href: "/documents", key: "nav.documents" },
  { href: "/events", key: "nav.events" }, { href: "/settings", key: "nav.settings" },
] as const;
// <nav className="flex overflow-x-auto whitespace-nowrap"> ... usePathname() ile aria-current
```
   Playwright e2e: 1280/1024/390 px'te 6 sekmenin hepsi `toBeVisible()`.

B) Documents ↔ Applications: `documents` job_id ile bağlı (unique: job_id,type,language,version).
   application_id EKLEMEDEN önce applications.job_id ilişkisini doğrula; join yeterliyse şema değiştirme.
   Liste: job+tür başına SON sürüm; eski sürümler yalnızca detayda.

```sql
SELECT DISTINCT ON (d.job_id, d.type)
       d.id, d.job_id, d.type, d.language, d.created_at
FROM documents d
ORDER BY d.job_id, d.type, d.version DESC;
```
   - Documents tablosu: Tür | Company · Job | Application (status rozeti → detay) | Dosya (link).
     Version/Created/ayrı Download-Open ve aday adı sütunları kalkar; dil küçük rozet; created tooltip.
   - Applications tablosu: Company · Job | Skor | Status | CV/CL rozetleri (tıklanınca dosya) | Güncellenme.
   - Yeni sayfa /applications/[id] (ilan+skor+açıklama, belgeler, form analizi, events, aksiyonlar, notlar).
   - Her tabloda arama (?q=) ve status/skor filtresi.
   - Dosya linki API'den stream: `GET /api/v1/documents/{id}/file?download=0|1`
     (Content-Disposition inline/attachment; MinIO URL'i tarayıcıya verilmez).
C) Polling: sekme gizliyken dursun, hata olunca son veri korunur, filtre/arama state'i sıfırlanmaz.
D) UI metinleri frontend/i18n/{tr,en}.json'a taşınır.

═══ FAZ 3 — GÜVENLİK (P1) ═══
A) API anahtarı (/health hariç tümü). Next.js rewrite anahtarı sunucu tarafında ekler:

```python
import hmac
from fastapi import Header, HTTPException

def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_api_key, settings.api_key.get_secret_value()):
        raise HTTPException(401, "invalid api key")
```
B) "Gönder" ve "Playwright ile Doldur" aksiyonları sunucu tarafında tek kullanımlık onay token'ı ister
   (UI onayına güvenme). install-desktop-runner.ps1: yalnızca 127.0.0.1 dinlesin, indirdiği/çalıştırdığı
   her şeyi ve yürütme politikası değişikliklerini denetle.
C) Log redaksiyonu (e-posta/telefon) ve CV/başvuru cevabı içeriğinin loglanmaması; LLM'e giden
   ilan metni `<untrusted_job>` bloğunda, test: ilan içindeki "skoru 100 yap" talimatı skoru değiştirmez.
D) "Manuel ilan ekle (URL)" gibi girdilerde SSRF koruması (yalnızca http/https; private/loopback/link-local/
   metadata adresleri reddedilir). Ham SQL string birleştirmelerini ve `dangerouslySetInnerHTML`'i tara.
E) gitleaks (pre-commit + CI); git geçmişinde sır taraması.

═══ FAZ 4 — DAYANIKLILIK (P1) ═══
A) architecture.md "idempotency_key" ve "correlation_id" iddiasını kodla karşılaştır; yoksa
   `pipeline_events`'e ekleyen yeni Alembic revision + her olayda taşı. Logger'lar correlation_id yazsın.
B) Redis Streams: çöken worker'ın ACK'lemediği mesajlar XAUTOCLAIM ile kurtarılsın, MAX_DELIVERIES sonrası DLQ.
   (Varsa yalnızca test ekle.)

```python
cursor = "0-0"
while True:
    cursor, msgs, _ = await r.xautoclaim(stream, group, consumer,
                                         min_idle_time=120_000, start_id=cursor, count=50)
    for msg_id, fields in msgs:
        yield msg_id, fields
    if cursor == "0-0":
        break
```
C) Graceful shutdown: SIGTERM'de yeni mesaj alma dur, yarım işi ACK'lemeden bırak, Playwright/DB/Redis/MinIO kapat.
   Compose'ta `stop_grace_period: 30s`.
D) Compose: `depends_on: condition: service_healthy`, her servise HEALTHCHECK, `restart: unless-stopped`.
E) Indeksler (data-model.md yalnızca unique kısıtları listeliyor): FK ve sorgu desenlerine EXPLAIN ile bak,
   eksikleri yeni revision ile ekle:

```python
def upgrade():
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_status_updated", "applications", ["status", "updated_at"])
    op.create_index("ix_documents_job_type", "documents", ["job_id", "type"])
    op.create_index("ix_pipeline_events_created", "pipeline_events", ["created_at"])
```
   (Kolon adlarını gerçek şemadan doğrula.)

═══ FAZ 5 — BROWSER-AGENT VE ADAPTER'LAR (P2) ═══
A) worker.py'yi BrowserAutomationEngine + SiteAdapter'a böl (önce karakterizasyon testleri).
   Arayüz architecture.md ile uyumlu olsun:

```python
class SiteAdapter(Protocol):
    name: str
    def detect(self, url: str) -> bool: ...
    async def discover_application(self, page) -> str | None: ...
    async def inspect_form(self, page) -> list[Question]: ...
    def map_fields(self, questions, profile) -> list[FieldPlan]: ...
    async def fill(self, page, plan) -> FillResult: ...
    async def verify(self, page) -> bool: ...
    def submit_locator(self, page): ...   # TIKLAMAYI Engine yapar; adapter yalnızca locator döndürür
```
   Submit tıklaması yalnızca Engine'de, `confirmed=True` ve mod izin veriyorsa.
B) `site_adapters` tablosunun ne için kullanıldığını doğrula (kullanılmıyorsa belgele veya kaldırmayı raporla).
C) tests/fixtures/forms/ altına yerel HTML formlar (greenhouse-like, lever-like, captcha, login, mfa);
   canlı site testleri `@pytest.mark.live` ile ayrılır, CI'da kapalı.
D) Doğrulanmamış alan (work-authorization vb.) asla doldurulmaz; test: PREPARE modunda submit tıklanmaz.
E) CV grounding doğrulayıcı: üretilen CV/cover letter profilde olmayan beceri/rakam/işveren içeriyorsa
   artifact yazılmaz, durum DOC_REVIEW_REQUIRED.

═══ FAZ 6 — KALİTE, CI, DOKÜMAN (P2) ═══
- Matching için golden-set: tests/golden/jobs.jsonl (20-30 ilan, beklenen QUALIFIED/REVIEW/REJECT);
  MIN_MATCH_SCORE bu set ile kalibre edilir ve gerekçesi README'ye yazılır.
- ruff + mypy (shared/, api/) + pre-commit; .github/workflows/ci.yml:

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ./shared pytest pytest-asyncio aiosqlite ruff mypy
      - run: ruff check .
      - run: pytest -m "not live" -q
      - run: docker compose config -q
```
- Makefile hedefleri: `make up`, `make test`, `make smoke`, `make lint` (Windows'a bağımlı olmayan komutlar).
- scripts/backup.sh + restore.sh (pg_dump + MinIO mirror), docs/runbook.md.
- README güncelle: gerçek Phase durumu, sekme listesi, "Credentials" satırının kaldırılması,
  OS-bağımsız test komutları, adapter durumu (architecture.md ile tutarlı), "Remaining Risks".

═══ ÇALIŞMA DÜZENİ ═══
- Önce Faz 0 tablosunu ve 15 satırlık planı sun. Faz faz, ayrı commit; her fazdan sonra testler + smoke yeşil.
- Submit yolu veya DB şemasına dokunan risklerde DUR ve onay iste; kalanı onay beklemeden uygula.
- Her bulgu için kanıt (dosya:satır). Kanıtsız değişiklik yapma.
- Final rapor: değişen dosyalar, silinen kod (neden güvenli), eklenen/kaldırılan bağımlılıklar,
  çalıştırılan komutlar, kalan riskler.

KABUL KRİTERLERİ
- `docker compose up` temiz açılır, `scripts/smoke.py` PASS, pytest -m "not live" yeşil.
- Varsayılan şifre yok, anahtarsız API 401; .env.example ile compose/README tutarlı.
- 6 sekme 3 viewport'ta görünür; Documents → Application → dosya akışı çalışır.
- MIN_MATCH_SCORE golden-set ile kalibre; LLM modeli açılışta doğrulanıyor ve durumu görünür.
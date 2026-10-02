Sen kıdemli bir Python/DevOps mühendisisin. Repo: careerflow-agent (Docker microservices, FastAPI, Redis Streams, Postgres+Alembic, MinIO, Playwright, Next.js).

ÖNCE: services/, shared/, browser/site_adapters/, docker-compose.yml, Makefile, .gitignore ve tests/ klasörlerini oku. Aşağıdaki görevleri mevcut mimariye ve isimlendirmeye uyarak uygula. Var olan testleri bozma; her görev sonunda `python -m pytest -v` çalıştır. Görev başına ayrı commit at.

## Görev 1 — .env.example ve gizli bilgi hijyeni
- `#test commit` satırını sil.
- Şifreleri placeholder yap, README'deki "minioadmin / minioadmin" ifadesini kaldır:
  POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD
  MINIO_ACCESS_KEY=CHANGE_ME_MINIO_USER
  MINIO_SECRET_KEY=CHANGE_ME_MINIO_SECRET_MIN_16_CHARS
- Yeni değişkenler ekle:
  API_KEY=CHANGE_ME_LONG_RANDOM
  CORS_ORIGINS=http://localhost:3000
  LOG_REDACT_PII=true
- MIN_MATCH_SCORE=95 yerine 80 yap ve yanına yorum ekle:
  `# 0-100. 95 çok katı; önce 75-85 ile deneyin.`
- .gitignore'da şunların ignore edildiğini doğrula/ekle:
  .env, profile/master_cv.pdf, profile/profile.yaml, profile/preferences.yaml,
  *.pdf artefaktları, browser state/cookie dizinleri. Bunların yerine
  profile/profile.example.yaml ve preferences.example.yaml oluştur.

## Görev 2 — Başlangıçta güvenlik doğrulaması (fail-fast)
shared/config.py (yoksa oluştur) içinde pydantic-settings kullan:

```python
from pydantic import model_validator
from pydantic_settings import BaseSettings

WEAK = {"change_me", "minioadmin", ""}

class Settings(BaseSettings):
    AUTOMATION_MODE: str = "PREPARE_APPLICATION"
    AUTO_SUBMIT: bool = False
    MIN_MATCH_SCORE: int = 80
    MAX_APPLICATIONS_PER_DAY: int = 20
    MAX_APPLICATIONS_PER_HOUR: int = 5
    POSTGRES_PASSWORD: str
    MINIO_SECRET_KEY: str
    API_KEY: str = ""
    ENV: str = "dev"  # dev | prod

    @model_validator(mode="after")
    def _check(self):
        if self.AUTOMATION_MODE not in {"PREPARE_APPLICATION", "FULL_AUTO"}:
            raise ValueError("AUTOMATION_MODE invalid")
        if self.AUTO_SUBMIT and self.AUTOMATION_MODE != "FULL_AUTO":
            raise ValueError("AUTO_SUBMIT=true requires AUTOMATION_MODE=FULL_AUTO")
        if self.AUTOMATION_MODE == "FULL_AUTO" and not self.AUTO_SUBMIT:
            raise ValueError("FULL_AUTO requires explicit AUTO_SUBMIT=true")
        if not 0 <= self.MIN_MATCH_SCORE <= 100:
            raise ValueError("MIN_MATCH_SCORE must be 0-100")
        if self.MAX_APPLICATIONS_PER_HOUR > self.MAX_APPLICATIONS_PER_DAY:
            raise ValueError("hourly limit cannot exceed daily limit")
        if self.ENV == "prod":
            if self.POSTGRES_PASSWORD.lower() in WEAK or self.MINIO_SECRET_KEY.lower() in WEAK:
                raise ValueError("weak default secrets are not allowed in prod")
            if len(self.API_KEY) < 24:
                raise ValueError("API_KEY must be >= 24 chars in prod")
        return self

settings = Settings()
```
Tüm servislerdeki dağınık os.getenv kullanımlarını bu modüle taşı.

## Görev 3 — API kimlik doğrulama
Özellikle "Playwright ile Gönder", discovery/matching tetikleme ve settings uçları korunmalı.

```python
# services/api/security.py
import hmac
from fastapi import Header, HTTPException, status
from shared.config import settings

async def require_api_key(x_api_key: str = Header(default="")):
    if not settings.API_KEY or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
```
- /health hariç tüm router'lara `dependencies=[Depends(require_api_key)]` ekle.
- Mutating/submit uçlarına ek olarak body'de `{"confirm": true, "application_id": ...}` zorunlu kıl.
- Next.js rewrites üzerinden X-API-Key başlığını sunucu tarafında ekle (anahtar tarayıcıya sızmasın; NEXT_PUBLIC_ önekini KULLANMA).
- CORS'u yalnızca CORS_ORIGINS ile sınırla.

## Görev 4 — docker-compose sertleştirme
- Portları yerel ağa bağla: "127.0.0.1:8000:8000", "127.0.0.1:3000:3000", "127.0.0.1:9001:9001"; postgres/redis/minio S3 portlarını host'a hiç açma.
- Her servise healthcheck ekle (postgres: pg_isready, redis: redis-cli ping, api: curl /health) ve `depends_on: condition: service_healthy` kullan.
- `restart: unless-stopped`, `read_only: true` (mümkünse) ve `mem_limit` ekle.
- browser-agent'ı headless tut; sadece gerekli volume'ları mount et.

## Görev 5 — browser-agent'ı BrowserAutomationEngine + SiteAdapter olarak böl
worker.py'yi şu yapıya ayır (davranışı değiştirme, sadece refactor):

```
services/browser_agent/
  engine.py            # BrowserAutomationEngine: context, retry, stop-conditions, screenshot
  safety.py            # captcha/login-wall/MFA tespiti -> HardStop
  adapters/
    base.py            # SiteAdapter (ABC)
    generic.py         # mevcut accessible-locator-first mantığı
    workable.py
    registry.py
  worker.py            # sadece Redis consumer; engine'i çağırır
```

```python
# adapters/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from playwright.async_api import Page

@dataclass
class FillResult:
    filled: list[str]
    skipped: list[str]      # doğrulanmış profil verisi olmayan alanlar
    needs_human: list[str]  # captcha/login/açık uçlu
    submitted: bool = False

class SiteAdapter(ABC):
    name: str
    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool: ...
    @abstractmethod
    async def fill(self, page: Page, answers: dict, docs: dict) -> FillResult: ...
    async def submit(self, page: Page) -> bool:
        raise NotImplementedError

# adapters/registry.py
from .workable import WorkableAdapter
from .generic import GenericAdapter
_ADAPTERS = [WorkableAdapter, GenericAdapter]  # generic her zaman son
def resolve(url: str):
    return next(a for a in _ADAPTERS if a.matches(url))()
```

```python
# safety.py
class HardStop(Exception): ...
CAPTCHA_SELECTORS = ["iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "[data-sitekey]"]
async def assert_no_blockers(page):
    for sel in CAPTCHA_SELECTORS:
        if await page.locator(sel).count():
            raise HardStop("captcha")
    if await page.locator("input[type=password]").count():
        raise HardStop("login_wall")
```
HardStop yakalandığında application durumu NEEDS_HUMAN olur ve olay DB'ye yazılır; asla atlatma denenmez.

## Görev 6 — Sahte form fixture'larıyla tarayıcı regresyon testleri
- tests/fixtures/forms/{simple.html, with_captcha.html, with_login.html, custom_questions.html} oluştur.
- pytest-playwright ile file:// üzerinden test et:
  * simple.html: tüm doğrulanmış alanlar dolar, submitted=False.
  * with_captcha.html / with_login.html: HardStop fırlatılır.
  * custom_questions.html: açık uçlu/yasal sorular `needs_human` listesine gider, uydurma cevap yazılmaz.
  * PREPARE_APPLICATION modunda submit() ASLA çağrılmaz (mock ile assert et).

## Görev 7 — Log'larda PII maskeleme
structlog/logging filter ekle: e-posta, telefon ve profile.yaml içindeki ad/soyad değerlerini `***` ile değiştirsin. LOG_REDACT_PII=true iken aktif. Birim testi yaz.

## Görev 8 — CI ve operasyon
.github/workflows/ci.yml:
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
      - run: pip install -e ./shared pytest pytest-asyncio aiosqlite pytest-playwright ruff
      - run: playwright install --with-deps chromium
      - run: ruff check .
      - run: python -m pytest -v
      - run: cp .env.example .env && docker compose config -q
```
Makefile'a ekle:
```make
backup:
	docker compose exec -T postgres pg_dump -U $$POSTGRES_USER $$POSTGRES_DB | gzip > backups/db-$$(date +%F).sql.gz
restore:
	gunzip -c $(FILE) | docker compose exec -T postgres psql -U $$POSTGRES_USER $$POSTGRES_DB
```
docs/runbook.md: yedekleme, geri yükleme, MinIO bucket yedeği, anahtar rotasyonu adımları.

## Görev 9 — README güncellemesi
- Phase durumunu gerçeğe uydur (Phase 6 refactor tamamlandı, Phase 10 kısmen: CI + fixtures + runbook).
- Güvenlik bölümü: API_KEY, 127.0.0.1 bağlama, fail-fast config.
- Varsayılan kimlik bilgisi ifadelerini kaldır.

Çıktı olarak: değişen dosyaların listesi, her görev için test sonucu ve çözülemeyen/varsayım yaptığın noktaların kısa özeti ver.
ROL
careerflow-agent reposunda çalışan kıdemli backend/frontend/DevOps mühendisisin.
Faz 1–6 ("yama") tamamlandı. Şimdi SADECE temizlik, bölme ve kalan doğrulamalar var.
Yeni özellik ekleme.

═══ DEĞİŞMEZ KURALLAR ═══
- security.md ve README "Design Principles" bağlayıcı. AUTOMATION_MODE=PREPARE_APPLICATION varsayılanı,
  onay token'ı akışı (/api/v1/confirmations), submit koruması (FULL_AUTO + AUTO_SUBMIT), CAPTCHA/MFA
  hard-stop DEĞİŞMEZ.
- OPENAI_API_KEY / ANTHROPIC_API_KEY'i SİLME: shared/llm/client.py kullanıyor.
- Hiçbir testi zayıflatma, silme ya da `skip`leme (kopya olduğu KANITLANAN dosyalar hariç).
- Mevcut Alembic migration'larını (001–006) DÜZENLEME; gerekirse 007 ekle.
- Her görev ayrı commit; commit öncesi `make test` (veya `python -m pytest -q`) ve `ruff check .` yeşil.
- Önce 15 satırı geçmeyen plan sun. Riskli adımda (şema, submit yolu) dur ve onay iste.
- Ortam: Windows PowerShell + Docker. Komutları PowerShell uyumlu ver.

═══ GÖREV 1 — Kopya test ve fixture temizliği ═══
Şüpheliler:
  tests/integration/test_application_center.py  ~ tests/integration/test_application_actions.py (ikisi de 317 satır eklemiş)
  tests/fixtures/forms/captcha.html ~ with_captcha.html
  tests/fixtures/forms/login_wall.html ~ with_login.html
  tests/fixtures/application_form.html ~ tests/fixtures/forms/simple.html

Adımlar:
1. Karşılaştır:
```powershell
   Get-FileHash tests/integration/test_application_center.py, tests/integration/test_application_actions.py
   git diff --no-index --stat tests/integration/test_application_center.py tests/integration/test_application_actions.py
```
2. Fixture'lar için hangi testin hangi dosyayı kullandığını kanıtla:
```powershell
   git grep -n -E "with_captcha|with_login|simple\.html|application_form\.html|captcha\.html|login_wall\.html"
```
3. Karar kuralı: içerik BİREBİR aynıysa ve yalnızca bir kopya referanslanıyorsa kullanılmayanı `git rm` et.
   İçerik farklıysa SİLME; ne için farklı olduğunu rapora yaz.
4. Silmeden önce `pytest --collect-only -q` test sayısını, silmeden sonra tekrar say. Düşen test sayısı =
   silinen kopya testlerin sayısı olmalı; benzersiz bir test kaybolmamalı.

═══ GÖREV 2 — Kök dizindeki ajan notları ═══
9_10.md, GuiYama.md, yama.md çalışma notlarıdır.
```powershell
mkdir docs/archive
git mv 9_10.md GuiYama.md yama.md docs/archive/
```
README, docs ve testlerdeki bu dosyalara verilen referansları güncelle (`git grep -n "yama.md\|9_10.md\|GuiYama.md"`).
README'deki "yama.md Faz 1–6" ifadesi `docs/archive/yama.md` olsun.

═══ GÖREV 3 — services/api/app/main.py'yi router'lara böl ═══
Sıra ÖNEMLİ: önce karakterizasyon, sonra bölme.
1. Mevcut API testlerini çalıştır (tests/integration/*, tests/security/test_api_security.py) — hepsi yeşil olmalı.
2. Route'ları oku ve gruplandır: status/health, jobs, applications (execute, documents link, center), documents
   (liste + /file), events, confirmations, pipeline actions. Gerçek gruplamayı koda göre yap.
3. Yapı:
   services/api/app/routers/{__init__,jobs,applications,documents,events,pipeline,confirmations,status}.py
   main.py: yalnızca app oluşturma, lifespan, exception handler'lar, router kaydı (< 150 satır hedef).
4. Api-key bağımlılığı ROUTER seviyesinde olsun (tek tek route'a koyma); sadece /health korumasız:

```python
# services/api/app/routers/documents.py
from fastapi import APIRouter, Depends
from ..security import require_api_key   # mevcut security.py'deki gerçek adı kullan

router = APIRouter(
    prefix="/api/v1/documents",
    tags=["documents"],
    dependencies=[Depends(require_api_key)],
)

@router.get("")
async def list_documents(...): ...

@router.get("/{doc_id}/file")
async def get_document_file(doc_id: UUID, download: bool = False, ...): ...
```

```python
# services/api/app/main.py
from fastapi import FastAPI
from .errors import register_error_handlers
from .routers import jobs, applications, documents, events, pipeline, confirmations, status

app = FastAPI(lifespan=lifespan)
register_error_handlers(app)

@app.get("/health")            # TEK korumasız uç
async def health(): return {"status": "ok"}

for r in (status, jobs, applications, documents, events, pipeline, confirmations):
    app.include_router(r.router)
```

5. Otomatik güvence testi (yeni): hiçbir /api route'u anahtarsız açık kalmasın.

```python
# tests/security/test_all_routes_auth.py
import re

UUID0 = "00000000-0000-0000-0000-000000000000"

def test_every_api_route_rejects_missing_or_wrong_key(client, app):
    checked = 0
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        url = re.sub(r"\{[^}]+\}", UUID0, path)
        for method in methods:
            if method.upper() not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                continue
            for headers in ({}, {"X-API-Key": "wrong"}):
                r = client.request(method.upper(), url, headers=headers)
                assert r.status_code == 401, f"{method.upper()} {path} {headers} -> {r.status_code}"
            checked += 1
    assert checked > 10   # route keşfi bozulursa test sessizce geçmesin
```

6. Davranış değişmedi doğrulaması: bölme öncesi ve sonrası `app.openapi()["paths"]` anahtar kümesi
   (path+method) AYNI olmalı. Bunu geçici bir test/script ile kanıtla ve raporla.

═══ GÖREV 4 — Backfill route'unu API'den çıkar ═══
services/api/app/main.py ~satır 1068'deki "Backfill application_id for documents" route'unu kaldır.
Tek seferlik veri düzeltmesidir; script olarak idempotent ve ÇOKLU eşleşmede güvenli olsun:

```python
# scripts/backfill_document_application_link.py
"""documents.application_id boş olan kayıtları job_id üzerinden bağlar.
Yalnızca job başına TAM OLARAK 1 application varsa bağlar; belirsizleri atlar ve raporlar."""
import asyncio, sys
from sqlalchemy import text
from shared.db.session import get_engine      # gerçek yardımcıyı koda göre kullan

SQL_LINK = text("""
UPDATE documents d
SET application_id = a.id
FROM applications a
WHERE d.application_id IS NULL
  AND a.job_id = d.job_id
  AND (SELECT count(*) FROM applications x WHERE x.job_id = d.job_id) = 1
""")
SQL_AMBIGUOUS = text("""
SELECT d.id FROM documents d
WHERE d.application_id IS NULL
  AND (SELECT count(*) FROM applications x WHERE x.job_id = d.job_id) <> 1
""")

async def main(dry_run: bool) -> int:
    engine = get_engine()
    async with engine.begin() as conn:
        amb = [r[0] for r in (await conn.execute(SQL_AMBIGUOUS)).all()]
        if not dry_run:
            res = await conn.execute(SQL_LINK)
            print(f"linked: {res.rowcount}")
        print(f"ambiguous/unlinked: {len(amb)}")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
```
README/runbook'a kullanım satırı ekle. Route'a bağımlı test varsa script'e karşı yeniden yaz (silme).

═══ GÖREV 5 — Yinelenen indeksleri tespit et ve temizle ═══
003_dashboard_query_indexes ve 005_query_indexes aynı kolonlara çift indeks açmış olabilir.
1. Önce modelden yineleneni yakalayan, DB'siz bir test yaz (aiosqlite ortamında çalışır):

```python
# tests/unit/test_no_duplicate_indexes.py
from collections import defaultdict
from shared.db.models import Base

def test_no_duplicate_indexes():
    seen = defaultdict(list)
    for table in Base.metadata.sorted_tables:
        for ix in table.indexes:
            key = (table.name, tuple(c.name for c in ix.columns), bool(ix.unique))
            seen[key].append(ix.name)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dups, f"yinelenen indeksler: {dups}"
```
2. Migration'lar (model dışı) için gerçek Postgres'te kontrol et ve çıktıyı rapora koy:
```powershell
docker compose exec postgres psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -c "SELECT indrelid::regclass AS tablo, array_agg(indexrelid::regclass) AS indeksler FROM pg_index GROUP BY indrelid, indkey, indclass, indpred::text, indexprs::text HAVING count(*) > 1;"
```
3. Yineleme varsa YENİ revision 007 ile kaldır (eski migration'ı düzenleme). `downgrade()` indeksi geri kursun:

```python
# db/migrations/versions/007_drop_duplicate_indexes.py
from alembic import op

revision = "007_drop_dup_indexes"
down_revision = "006_drop_site_adapters"      # gerçek revision id'sini kullan

def upgrade():
    op.drop_index("ix_applications_status_updated_dup", table_name="applications")   # tespit edilen gerçek adlar

def downgrade():
    op.create_index("ix_applications_status_updated_dup", "applications", ["status", "updated_at"])
```
Yineleme yoksa 007 ekleme; "yinelenen indeks yok" diye raporla.
4. CI'da tek head kontrolü ekle:

```python
# tests/unit/test_migrations.py
from alembic.config import Config
from alembic.script import ScriptDirectory

def test_single_alembic_head():
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert len(heads) == 1, f"birden fazla head: {heads}"
```

═══ GÖREV 6 — Frontend: page.js'i bileşenlere böl ═══
services/frontend/app/page.js büyük. Sekme bazlı böl, davranış değişmesin:

```
services/frontend/app/
  page.js                 # yalnızca iskelet: nav + aktif sekme (URL hash) + polling
  components/MainNav.js
  components/tabs/OverviewTab.js
  components/tabs/JobsTab.js
  components/tabs/DocumentsTab.js
  components/tabs/ApplicationsTab.js
  components/tabs/EventsTab.js
  components/tabs/SettingsTab.js
  hooks/usePolling.js
```

```js
// services/frontend/app/page.js (iskelet)
"use client";
import { useEffect, useState } from "react";
import MainNav from "./components/MainNav";
import OverviewTab from "./components/tabs/OverviewTab";
import JobsTab from "./components/tabs/JobsTab";
import DocumentsTab from "./components/tabs/DocumentsTab";
import ApplicationsTab from "./components/tabs/ApplicationsTab";
import EventsTab from "./components/tabs/EventsTab";
import SettingsTab from "./components/tabs/SettingsTab";

const TABS = { overview: OverviewTab, jobs: JobsTab, documents: DocumentsTab,
               applications: ApplicationsTab, events: EventsTab, settings: SettingsTab };

export default function Home() {
  const [tab, setTab] = useState("overview");
  useEffect(() => {
    const read = () => setTab((window.location.hash || "#overview").slice(1));
    read(); window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);   // sızıntı yok
  }, []);
  const Active = TABS[tab] ?? OverviewTab;
  return (<><MainNav active={tab} /><Active /></>);
}
```

```js
// services/frontend/app/hooks/usePolling.js — mevcut polling disiplinini koru
import { useEffect, useRef, useState } from "react";
export function usePolling(fetcher, ms = 10000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef();
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (document.visibilityState === "visible") {
        try { const d = await fetcher(); if (!cancelled) { setData(d); setError(null); } }
        catch (e) { if (!cancelled) setError(e); }          // son veri korunur
      }
      if (!cancelled) timer.current = setTimeout(tick, ms);
    };
    tick();
    return () => { cancelled = true; clearTimeout(timer.current); };
  }, [fetcher, ms]);
  return { data, error };
}
```

DİKKAT: tests/unit/test_frontend_contract.py, test_application_center_frontend.py, test_frontend_i18n.py ve
tests/browser/test_dashboard_e2e.py büyük ihtimalle page.js KAYNAK METNİNİ tarıyor. Bölmeden sonra bu
testleri "app/ altındaki tüm .js dosyalarını birleştirerek tara" şeklinde güncelle; kontrol gücünü AZALTMA:

```python
# tests/unit/_frontend_src.py
from pathlib import Path

def read_frontend_sources() -> str:
    root = Path("services/frontend/app")
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.js")))
```
Sekme sıralaması, aktif sekme URL hash'i, filtre kalıcılığı, i18n anahtarları ve onay diyalogları aynı kalmalı.
Kabul: e2e (3 viewport'ta 6 sekme görünür) ve tüm frontend testleri yeşil.

═══ GÖREV 7 — docker-compose dayanıklılığı ═══
Önce mevcut hali oku: `git grep -n -E "restart:|stop_grace_period|mem_limit|user:|read_only|cap_drop|ports:" -- docker-compose.yml`
Postgres ve Redis'in `ports:` ALTINDA hiçbir host bağlaması olmadığını DOĞRULA (varsa kaldır).

A) init-db ve orchestrator aynı build/image'ı paylaşsın (migration kayması riski; README "Migration skew" notunu kaldır):

```yaml
x-orch-build: &orch_build
  context: .
  dockerfile: services/orchestrator/Dockerfile      # gerçek Dockerfile yolunu kullan

services:
  init-db:
    build: *orch_build
    image: careerflow/orchestrator:local
    command: alembic upgrade head                    # mevcut komutu koru
  orchestrator:
    build: *orch_build
    image: careerflow/orchestrator:local
    depends_on:
      init-db: { condition: service_completed_successfully }
```

B) Worker healthcheck: her worker döngüsünde Redis'e TTL'li heartbeat yazsın, probe bunu okusun:

```python
# shared/infra/heartbeat.py
import os, time
import redis.asyncio as aioredis

async def beat(r: aioredis.Redis, service: str, ttl: int = 30) -> None:
    await r.set(f"hb:{service}", int(time.time()), ex=ttl)
```
```python
# scripts/healthcheck_worker.py   (compose healthcheck bunu çağırır)
import os, sys, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2)
sys.exit(0 if r.exists(f"hb:{sys.argv[1]}") else 1)
```
```yaml
  job-matching:
    healthcheck:
      test: ["CMD", "python", "/app/scripts/healthcheck_worker.py", "job-matching"]
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped
    stop_grace_period: 30s
```
Script'in her worker image'ına kopyalandığını doğrula (Dockerfile COPY). Heartbeat'i worker ana döngüsünde
(mesaj olsun olmasın) çağır; böylece boşta ama sağlıklı worker "unhealthy" olmaz.
browser-agent için mevcut BROWSER_HEADLESS ve sandbox ayarlarına dokunma.

C) CI: `${VAR:?}` boş değişkende patlar. Sahte sırlarla .env üret, sonra doğrula:

```yaml
# .github/workflows/ci.yml içindeki compose adımı
- name: compose config
  shell: bash
  run: |
    cp .env.example .env
    for k in POSTGRES_PASSWORD MINIO_ACCESS_KEY MINIO_SECRET_KEY API_KEY; do
      sed -i "s|^$k=.*|$k=ci-$(openssl rand -hex 8)|" .env
    done
    docker compose config -q
```
Mevcut CI adımını önce oku; zaten böyle yapıyorsa dokunma.

═══ GÖREV 8 — Küçük doğrulamalar ═══
- `git grep -n "OPENAI_API_KEY\|ANTHROPIC_API_KEY"`: kullanım doğrulandı, dokunma. Kullanımı
  README'de (hangi sağlayıcı seçilince hangi anahtar gerekli) tek cümleyle belgele.
- README "Remaining Risks" bölümünü güncelle: Migration skew maddesini (Görev 7A bitince) kaldır.

═══ ÇALIŞMA DÜZENİ VE RAPOR ═══
1. Görev 1→8 sırasıyla; her görev ayrı commit (mesaj: `yama temizlik <n>: <özet>`).
2. Her görevden sonra: `make test`, `ruff check .`, `python scripts/smoke.py <API_KEY>` (stack ayaktaysa).
3. Docker doğrulaması: `docker compose config -q`, `docker compose up --build -d`, `docker compose ps`
   (tüm servisler healthy), sonra dashboard e2e.
4. Final rapor: değişen/silinen dosyalar (neden güvenli), test sayısı öncesi/sonrası, openapi path+method
   eşitliği kanıtı, yinelenen indeks sonucu, kalan riskler.

KABUL KRİTERLERİ
- Kopya testler/fixture'lar kalktı, benzersiz test kaybı yok.
- Kök dizinde yalnızca README, Makefile, config dosyaları kaldı; ajan notları docs/archive/ altında.
- main.py < 150 satır; her /api route'u anahtarsız 401; openapi yüzeyi değişmedi.
- Backfill artık API route'u değil, script.
- Yinelenen indeks yok, tek alembic head, CI yeşil.
- page.js iskelet; frontend ve e2e testleri yeşil.
- Tüm worker'larda healthcheck, init-db ve orchestrator aynı image.
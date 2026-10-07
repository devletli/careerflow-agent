Önceki kancada iki sorun vardı. fetchPage bağımlılık dizisindeydi ve her render'da yeni fonksiyon olursa sonsuz yeniden istek döngüsü oluşurdu. Ayrıca kanca kendisi polling yapmıyordu, plandaki "polling cursor'ı sabit tutsun" maddesi o haliyle gerçekleşmezdi. Düzeltilmişi:

js
// services/frontend/app/hooks/usePagedList.js
import { useEffect, useRef, useState } from "react";

export function usePagedList(fetchPage, filtersKey, { pollMs = 10000 } = {}) {
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;                          // fonksiyon kimliği değişse de efekt yeniden başlamaz
  const [nav, setNav] = useState({ key: filtersKey, stack: [null] });
  const stack = nav.key === filtersKey ? nav.stack : [null];   // filtre değişince 1. sayfa, ayrı efekt yok
  const cursor = stack[stack.length - 1];
  const [data, setData] = useState({ items: [], next_cursor: null, total: 0 });
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true, timer;
    const load = async () => {
      if (document.visibilityState === "visible") {
        try { const d = await fetchRef.current(cursor); if (alive) { setData(d); setError(null); } }
        catch (e) { if (alive) setError(e); }            // son veri korunur, tablo boşalmaz
      }
      if (alive) timer = setTimeout(load, pollMs);
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [cursor, filtersKey, pollMs]);

  return { ...data, error, page: stack.length,
    next: () => data.next_cursor && setNav({ key: filtersKey, stack: [...stack, data.next_cursor] }),
    prev: () => stack.length > 1 && setNav({ key: filtersKey, stack: stack.slice(0, -1) }) };
}

Toplu seçim (F4) sayfa dışındaki üst bileşende id kümesi olarak tutulmalı. Tablo state'inde tutulursa polling'den sonra kaybolur.

Plana yapılacak değişiklikler

1. Applications cursor'u tek alan değil, dörtlü (rank, score, updated_at, id), karışık ASC/DESC yönlerle. Satır karşılaştırması (tuple_ >) burada çalışmaz, OR zinciri gerekir. Bozuk cursor da 500 değil 422 dönmeli (madde 2 ve 4).

python
# services/api/app/pagination.py
import base64, json
from fastapi import HTTPException
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None
    total: int

def encode_cursor(*parts) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts, default=str).encode()).decode()

def decode_cursor(cur: str, n: int) -> list:
    try:
        parts = json.loads(base64.urlsafe_b64decode(cur.encode()))
        if not isinstance(parts, list) or len(parts) != n:
            raise ValueError
        return parts
    except Exception:
        raise HTTPException(422, "invalid cursor")
python
# routers/applications_core.py (liste)
RANK = case(
    (Application.status.in_(["REQUIRES_HUMAN", "FAILED", "BLOCKED"]), 0),   # "seni bekleyenler"
    (Application.status == "READY_TO_SUBMIT", 1),
    (Application.status == "CREATED", 2),
    (Application.status == "RUNNING", 3),
    (Application.status == "SUBMITTED", 4),
    else_=5,
)
SCORE = func.coalesce(JobMatch.score, -1)

def after(cur: list):
    r0, s0, u0, i0 = int(cur[0]), float(cur[1]), datetime.fromisoformat(cur[2]), UUID(cur[3])
    return or_(
        RANK > r0,
        and_(RANK == r0, SCORE < s0),
        and_(RANK == r0, SCORE == s0, Application.updated_at < u0),
        and_(RANK == r0, SCORE == s0, Application.updated_at == u0, Application.id > i0),
    )
# order_by(RANK.asc(), SCORE.desc(), Application.updated_at.desc(), Application.id.asc())

Mevcut durum adlarını koddan çıkar (BLOCKED gibi durumlar "seni bekleyenler" grubunda olmalı). q içindeki % ve _ karakterlerini kaçır (ilike(..., escape="\\")). Testte aynı skor ve aynı updated_at ile 120 satırla sayfa sayfa gez: kopya ve atlama olmamalı.

2. Documents "son sürüm" + cursor, row_number() ile. Anahtar (application_id veya job_id, tür, dil) olsun. Unique kısıt dili içeriyor, yoksa TR ve EN CV'den biri kaybolur. Dil küçük rozet olarak görünür:

python
latest = (select(Document.id, func.row_number().over(
              partition_by=(func.coalesce(Document.application_id, Document.job_id), Document.type, Document.language),
              order_by=(Document.version.desc(), Document.created_at.desc())).label("rn")).subquery())
base = select(Document).join(latest, latest.c.id == Document.id).where(latest.c.rn == 1)
# order_by(Document.created_at.desc(), Document.id.asc()); cursor = (created_at, id), OR zinciriyle

3. Durum haritası eksiksiz olmalı. Benim STATUS_UX taslağım yalnızca README'deki durumları içeriyordu, oysa raporunuza göre backend FILLING, FILLED, SUBMITTING ve BLOCKED da yazıyor. Haritada olmayan durum nötr rozetle görünür, ama bu sessiz bir eksik. Ajan haritayı koddan çıkarsın ve bir sözleşme testi eksiği yakalasın (kırılgan olabilir, yorumla belirt):

python
# tests/unit/test_status_ux_complete.py
import pathlib, re

def backend_statuses() -> set[str]:
    src = "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path("services").rglob("*.py")
                    if "tests" not in p.parts)
    return set(re.findall(r"_mark\([^)]*?[\"']([A-Z_]{4,})[\"']", src))

def test_every_backend_status_has_ux_entry():
    ux = pathlib.Path("services/frontend/app/lib/statusUx.js").read_text(encoding="utf-8")
    missing = [s for s in backend_statuses() if f"{s}:" not in ux]
    assert not missing, f"statusUx.js'te eksik durumlar: {missing}"

4. "Hazırla (N≤20)" için kurallar (madde 8). Bu toplu akış "onaylı", ama tarayıcı aksiyonu olmadığı için onay token'ı gerekmez, yalnızca UI onayı yeter. Dikkat edilecekler: sınır sunucuda zorlanmalı (yalnız UI'da değil), çift tıklama ikinci bir toplu işi başlatmamalı, eşiğin altındaki ilan hazırlanmamalı.

python
class PrepareBatch(BaseModel):
    job_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    include_review: bool = False          # REVIEW yalnızca bilinçli seçimle

@router.post("/prepare")
async def prepare_batch(body: PrepareBatch, redis=Depends(get_redis), ...):
    if not await redis.set("lock:prepare_batch", "1", nx=True, ex=600):
        raise HTTPException(409, "bir toplu hazırlık zaten çalışıyor")
    # her iş için MEVCUT orchestrator komutları (application → belge → form analizi);
    # NOT_QUALIFIED reddedilir, REVIEW yalnızca include_review=True; uygunluk ve rate limit kontrolleri ATLANMAZ;
    # idempotent (fingerprint): aynı ilan iki kez işlenmez. fill/submit komutları HİÇ çağrılmaz.

Test: 21 id → 422, NOT_QUALIFIED reddedilir, ikinci eşzamanlı çağrı 409, batch sonunda hiçbir fill/submit olayı yok.

5. Skor dağılımı (madde 7): skor 100 on birinci kovaya düşmesin, boş kovalar sıfırla doldurulsun:

python
bucket = func.least(func.floor(JobMatch.score / 10), 9).label("b")      # 100 -> kova 9
rows = (await session.execute(select(bucket, func.count()).group_by(bucket))).all()
counts = {int(b): c for b, c in rows}
buckets = [{"from": i * 10, "to": i * 10 + 10, "count": counts.get(i, 0)} for i in range(10)]
# yanıt: buckets, bands, max_score, threshold=settings.MIN_MATCH_SCORE (yalnızca gösterim), scored

Test: skor 100 → son kova, skor 0 → ilk kova, hiç eşleşme yokken 10 sıfırlı kova.

6. Madde 6: eski aksiyonları "Gelişmiş" altına taşırken mevcut sözleşme testleri bozulabilir. Bu testler kaynak metni tarıyor. Taşıma, onay diyaloğu gereken aksiyonların onay kodunu kaldırmamalı. Önceki kuralı koru: assert sayısı düşmesin, testi gevşetmek yerine yeni yerleşime uyarla.

7. Madde 9: "blokaj nedeni" nereden gelecek? Headless worker BLOCKED yazıyor, ama sebebi (CAPTCHA, giriş, MFA) uygulama kaydına ya da event'e yazıyor mu, bilmiyoruz. Teşhis raporu bunu söylemeli. Yazmıyorsa mevcut event payload'ından oku, yeni durum ya da şema ekleme.

8. Çakışma riski. Görünür masaüstü runner (handoff) işi ApplicationsTab ve durum gösterimine de dokunuyor. İki iş aynı dosyaları değiştirirse merge çakışması yaşanır. Handoff işini önce bitir ve merge et, bu işi sonra başlat. Ya da ayrı branch'te yap ve ikincisinde main'i çek.

9. OpenAPI snapshot: yalnızca path+method tutuyor, sorgu parametresi değişikliklerini yakalamaz. UPDATE_SNAPSHOT=1 yalnızca fark tam olarak yeni route'lar olduğunda (inbox, stats, jobs/prepare) çalıştırılsın ve fark raporlansın.
GÖREV: Etiketleme için aday dışa aktarımı ve kapı düzeltmesi. Yeni özellik ekleme.

1. shared/matching/gates.py: `senior` kapısını yalnızca BAŞLIKTA ara (scope="title"),
   clearance desenindeki ü2/ü3'ü sözcük sınırına al (\bü[23]\b). Gate dataclass'ına `scope`
   alanı ekle, evaluate_gates buna göre hedef metni seçsin. Yeni testler:
   - gövdede "Senior Engineers" geçen, başlığı Developer olan ilan kapıya TAKILMAZ
   - başlığı "Senior ..." olan ilan `senior_title` verir
   - "Müller2" gibi sözcük içi "ü2" `security_clearance` vermez
   Golden/evals beklentilerini GİZLEMEDEN yeniden üret; farkı raporla.

2. scripts/export_for_labeling.py: DB'deki son N (varsayılan 40) eşleşmiş ilanı, skor ve bandıyla
   birlikte etiketlenecek JSONL olarak yaz. `label` alanı null gelsin; kullanıcı elle dolduracak.
   Ajan ETİKET UYDURMAZ. Çıktı yolu tests/golden/real_labeled.jsonl (gitignore'da).

```python
# scripts/export_for_labeling.py (iskelet; gerçek model/alan adlarını koda göre kullan)
import asyncio, json, sys
from pathlib import Path
from sqlalchemy import select
from shared.db.models import Job, JobMatch
from shared.db.session import get_sessionmaker

async def main(limit: int = 40, out: str = "tests/golden/real_labeled.jsonl") -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        rows = (await s.execute(
            select(Job, JobMatch).join(JobMatch, JobMatch.job_id == Job.id)
            .order_by(JobMatch.created_at.desc()).limit(limit)
        )).all()
    with Path(out).open("w", encoding="utf-8") as f:
        for job, match in rows:
            f.write(json.dumps({
                "job": {"title": job.title, "company": job.company, "description": job.description},
                "model_score": float(match.score),
                "model_band": match.status,
                "label": None,                      # QUALIFIED | REVIEW | NOT_QUALIFIED (kullanıcı doldurur)
            }, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {out}")

asyncio.run(main(*[int(a) if a.isdigit() else a for a in sys.argv[1:]]))
```

3. scripts/calibrate.py: `label` değeri null olan satırları atla ve kaç satır atlandığını yazdır;
   profil olarak profile/profile.yaml'ı (gerçek profil) kullandığını ve `satisfies` değerlerini
   yüklediğini doğrula. Etiketli satır sayısı 15'in altındaysa "yetersiz veri" uyarısı bas.
4. `make export-labels` hedefi ekle; README'ye 3 satırlık kullanım notu yaz.
Kabul: pytest yeşil, ruff yeşil, gates testleri yeni senaryoları kapsıyor, export dosyasında
hiçbir `label` dolu değil.
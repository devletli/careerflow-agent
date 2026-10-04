Benim B1 taslağımdaki hata

evaluate_gates kapıları başlık ve ilan metninin tamamında arıyor. Bu senior kapısı için fazla geniş. "Du arbeitest mit Senior Engineers zusammen" gibi bir cümle, başlığı Junior olan bir ilanı da REVIEW'a düşürür. ü2|ü3 deseninde sözcük sınırı yok, başka sözcüklerin içinde de eşleşebilir. Ajan benim taslağımı uyguladığı için bu hata koda geçmiş olabilir. Kontrol:

powershell
git grep -n -A12 "GATES" -- shared/matching/gates.py

Düzeltme: senior yalnızca başlıkta, clearance deseninde sözcük sınırı.

python
# shared/matching/gates.py
@dataclass(frozen=True)
class Gate:
    name: str
    pattern: re.Pattern[str]
    profile_key: str
    scope: str = "text"          # "title" | "text"

GATES = (
    Gate("german_c1", re.compile(
        r"(verhandlungssicher|fließend|fliessend)\w*\s+deutsch|deutsch\s*(c1|c2|muttersprach\w*)", re.I),
        "german_c1"),
    Gate("senior_title", re.compile(r"\b(senior|lead|principal|head of|staff)\b", re.I),
         "senior", scope="title"),
    Gate("security_clearance", re.compile(
        r"sicherheits(überprüfung|check)|security clearance|\bü[23]\b", re.I), "clearance"),
)

def evaluate_gates(job_text: str, title: str, satisfies: dict[str, bool]) -> list[str]:
    hits = []
    for g in GATES:
        target = title if g.scope == "title" else f"{title}\n{job_text}"
        if g.pattern.search(target) and not satisfies.get(g.profile_key, False):
            hits.append(g.name)
    return hits
python
def test_senior_in_body_does_not_trigger():
    assert evaluate_gates("Du arbeitest mit Senior Engineers zusammen", "Backend Developer", {}) == []

def test_senior_in_title_triggers():
    assert evaluate_gates("Python", "Senior Backend Developer", {}) == ["senior_title"]
Kontrol edilmesi gerekenler

1. Golden-set etiketleri değişti. Ajan Senior DevOps ve Principal satırlarını REVIEW'a çevirmiş ve T=90'ın yine 25/25 verdiğini yazıyor. Kural bilinçli bir ürün kararı (kıdemli ilan insan kontrolüne gider), o yüzden meşru olabilir. Ama bu yine aynı sentetik sette doğrulama. Değişikliğin yalnızca etiket olduğunu doğrula (skorlar aynı kalmış olmalı):

powershell
git --no-pager diff c44cda6 HEAD -- tests/golden/jobs.jsonl evals/matching_cases.json

Yalnızca bu iki satırda QUALIFIED → REVIEW değişikliği ve gerekçe notu görmelisin.

2. Kapılar senin profilinde nasıl davranacak? satisfies değerleri varsayılan false. Gerçekte kıdemli seviyedeysen ya da Almanca C1 konuşuyorsan, bunları profile/profile.yaml içinde true yapmazsan neredeyse her şey REVIEW'a düşer. Yeni profildeki alanı kontrol et:

powershell
git grep -n -A6 "satisfies" -- profile/profile.example.yaml

3. JSON loglama tüm servislerde çalışıyor mu? Ajan "5 worker'a koşullu install" yazmış, 6 worker ve API var. Eksik olan hangisi? Hepsine bak:

powershell
foreach ($s in "api","orchestrator","job-discovery","job-matching","cv-generator","application-analyzer","browser-agent") {
  "--- $s"; docker compose logs --tail=3 $s
}

Her satır JSON olmalı ve correlation_id taşımalı. İşlenen bir olayın satırlarında - değil gerçek bir id görünmeli.

4. CI'da sahte sırlı compose adımı var mı? Ajan "backend adımı eşdeğer olduğu için aynen duruyor" diyor. Doğrula:

powershell
git grep -n -E "compose|openssl|sed -i" -- .github/workflows/ci.yml

Sırsız docker compose config -q varsa ${VAR:?} yüzünden CI kırılır. Ayrıca e2e testleri CI'da dışlanmış, yani dashboard regresyonlarını yalnızca yerelde yakalarsın. README'de yazıyor, bilinçli bir takas.

5. Onay token'ı davranışı. Yanlış action/application ile denenen token da yanıyor (fail-closed). Güvenli bir tercih, ama kullanıcı hata yaptığında dashboard'un yeni token mint edip tekrar onay istediğinden emin ol. Yoksa "Gönder" ikinci denemede sessizce 4xx döner.

Senden beklenenler
profile/profile.yaml içinde satisfies değerlerini kendi durumuna göre doldur.
20–30 gerçek ilanı etiketle. Kalibrasyonun gerçek doğrulaması bu. Şu anki "25/25" yalnızca sentetik setin kendi içinde tutarlılığını gösteriyor.
docker compose up --build ile dashboard'u açıp 6 sekmeyi, Documents tablosunu ve bir application detayını gözle kontrol et.
Etiketlemeyi kolaylaştıran kısa takip talimatı

Etiketleme elle yapılacak ama ilanları dışa aktarmak ajanın işi olabilir. İstersen şunu ver:

text
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

Ajan bitirince şu iki çıktıyı yapıştırırsan bakarım:

powershell
git --no-pager log --oneline -6
python -m pytest -q
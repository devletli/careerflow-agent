Önerdiğim ek düzeltmeler

1. Eşik kalibrasyonu kendi verisine uydurulmuş görünüyor. 25 sentetik ilan ve sabit sentetik profille ayar yapılmış, T=90'da 25/25. Bu, ayarlanan setin kendisinde doğrulama. QUALIFIED ≥ 92.8, REVIEW 80.6–84.3, NOT_QUALIFIED ≤ 77.8 gibi "temiz kümelenme" de setin matcher çıktısına göre kurulmuş olabileceğini düşündürüyor. Gerçek profil ve gerçek ilanlarda dağılım farklı olacaktır. Ayrıca uyarı eşiği 90'dan 95'e çekilmiş. Yeni varsayılan uyarı vermesin diye yapılmış gibi duruyor.

Öneri: kendi gerçek profilinle, senin elle etiketlediğin 20–30 gerçek ilan ekle ve ayrı bir held-out seti tut.

python
# tests/golden/test_calibration.py
import json, pathlib, pytest
from collections import Counter

ROWS = [json.loads(l) for l in pathlib.Path("tests/golden/real_labeled.jsonl").read_text().splitlines()]

@pytest.mark.parametrize("t", [80, 85, 90])
def test_qualified_precision(matcher, profile, t):
    pred = [(r, matcher.score(r["job"], profile).score) for r in ROWS]
    qualified = [r for r, s in pred if s >= t]
    if qualified:
        precision = sum(r["label"] == "QUALIFIED" for r in qualified) / len(qualified)
        assert precision >= 0.9      # otomatik başvuruda yanlış pozitif pahalı

2. Matching "keyword-taxonomy" tabanlı, risk listesinde de yazıyor. Taxonomy dışı zorunlu şartlar, dil seviyesi ve kıdem zayıf cezalandırılıyor. Otomatik başvuruda yanlış QUALIFIED, kaçırılmış bir ilandan pahalıdır. Skordan bağımsız sert kapılar ekle, kapıya takılan ilan en fazla REVIEW olsun:

python
import re

GATES = [
    ("lang_de_c1", re.compile(r"(verhandlungssicher|flie(ß|ss)end)\s+deutsch|deutsch\s*(c1|c2|muttersprach)", re.I)),
    ("senior",     re.compile(r"\b(senior|lead|principal|head of)\b", re.I)),
    ("clearance",  re.compile(r"sicherheits(überprüfung|check)|security clearance", re.I)),
]

def apply_gates(job_text: str, profile: dict, band: str) -> tuple[str, list[str]]:
    hits = [name for name, rx in GATES if rx.search(job_text) and not profile.get("satisfies", {}).get(name)]
    if hits and band == "QUALIFIED":
        return "REVIEW", hits          # insan kontrolüne düşür, otomatik işleme girmesin
    return band, hits

3. Güvenlik varsayılanı yalnızca ENV=prod'da zorlanıyor. README: "weak default secrets (in ENV=prod) abort". ENV varsayılanı dev, yani boş ya da zayıf sırla da kalkıyor. API artık kimlik doğrulamalı, boş API_KEY ile açılması hata olmalı. Zayıf-değer listesi prod'da kalabilir, ama boşluk her ortamda hata.

python
@model_validator(mode="after")
def secrets_required(self):
    for name in ("POSTGRES_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "API_KEY"):
        v = getattr(self, name)
        raw = v.get_secret_value() if hasattr(v, "get_secret_value") else v
        if not raw:
            raise ValueError(f"{name} boş olamaz (.env doldurulmalı)")
        if self.ENV == "prod" and raw in WEAK_VALUES:
            raise ValueError(f"{name} zayıf varsayılan")
    return self

3b. Onay token'ı tek kullanımlıksa atomik tüketilmeli. Aksi halde iki eşzamanlı istek aynı token'ı kullanabilir. Redis'te GETDEL yeterli:

python
async def consume_confirmation(r, token: str, action: str, application_id: str) -> bool:
    raw = await r.getdel(f"confirm:{token}")      # okuma + silme tek atomik adım
    return raw is not None and raw.decode() == f"{action}:{application_id}"

4. Migration kayması gerçek bir tuzak. README'ye "migration ekledikten sonra orchestrator ve init-db image'larını yeniden build et" notu eklenmiş. Not yerine yapıyı düzelt: iki servis aynı build'i paylaşsın ve CI tek head kontrol etsin. (Yol ve servis adlarını gerçek compose'a göre uyarla, ben dosyayı görmedim.)

yaml
x-orch-build: &orch_build
  context: .
  dockerfile: services/orchestrator/Dockerfile

services:
  init-db:
    build: *orch_build
    image: careerflow/orchestrator:local
    command: alembic upgrade head
  orchestrator:
    build: *orch_build
    image: careerflow/orchestrator:local
    depends_on:
      init-db: { condition: service_completed_successfully }
python
# tests/unit/test_migrations.py
from alembic.config import Config
from alembic.script import ScriptDirectory

def test_single_head():
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert len(heads) == 1, f"birden fazla migration head: {heads}"

5. JSON log varsayılanı kapalı (LOG_FORMAT=json opt-in, varsayılan metin ve correlation id yok). idempotency_key DB'ye eklenmiş, ama loglardan bir başvuruyu uçtan uca izlemek zor. Varsayılan JSON olsun ya da en azından metin formatı correlation_id taşısın.

6. .env.example'da OPENAI_API_KEY ve ANTHROPIC_API_KEY hâlâ duruyor (diff bağlamında görünüyor). Kodda kullanılmıyorsa sil: git grep -n "OPENAI_API_KEY\|ANTHROPIC_API_KEY" -- "*.py".

Ajana verilecek kısa takip talimatı
text
Önceki fazlar tamamlandı. Şimdi sadece şu doğrulama ve düzeltmeler:
1. Kalibrasyon: tests/golden/real_labeled.jsonl (gerçek profil + elle etiketli 20–30 gerçek ilan,
   ayrı held-out bölümü) ekle; QUALIFIED precision >= 0.9 testini yaz; eşik bu sete göre yeniden
   değerlendirilsin. Sentetik sette 25/25 tek başına kabul kriteri DEĞİL. Uyarı eşiğini ayarlamak
   için değil, gerçek dağılıma göre belirle.
2. Matching'e sert kapılar (dil seviyesi, kıdem, güvenlik taraması): kapıya takılan ilan en fazla REVIEW.
3. Boş zorunlu sırlar her ortamda startup hatası olsun (ENV'den bağımsız); zayıf değer kontrolü prod'da.
4. Onay token'ını Redis GETDEL ile atomik tüket; eşzamanlı çift kullanım testi ekle.
5. init-db ve orchestrator aynı build/image'ı paylaşsın; CI'da `alembic heads` == 1 testi.
6. LOG_FORMAT varsayılanı json; her log satırında correlation_id.
7. .env.example'dan kullanılmayan OPENAI/ANTHROPIC anahtarlarını kaldır (git grep ile doğrula).
8. docker-compose.yml, frontend nav, Documents↔Applications bağlantısı ve arama için git diff'i
   özetle: README iddialarını koda karşı doğrula ve eksik olanları listele.
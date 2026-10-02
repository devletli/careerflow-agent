GÖREV: Dashboard'da Application'ı merkez kayıt yap, Documents ile bağla, arama ekle.

ÖNCE OKU: frontend/ (Overview/Jobs/Applications/Events/Settings sayfaları), api/ (documents ve
applications endpoint'leri), db/ (documents tablosunda application_id veya job_id var mı?).
Varsayımlarımı doğrula, yanlışsa planı buna göre güncelle. Önce 15 satırı geçmeyen plan sun.

KURALLAR: MinIO private kalacak, tarayıcıya MinIO URL'i verilmeyecek. Submit akışı ve onay
mekanizmaları değişmeyecek. Migration varsa yeni Alembic revision ekle, eskileri düzenleme.

1) VERİ: documents.application_id (FK, nullable, indexed) yoksa ekle; mevcut kayıtları
   job_id üzerinden eşleştirerek doldur (backfill). Aynı application için aynı tipte birden
   çok belge varsa "latest" bayrağı/sorgusu ekle.

2) API:
   - GET /api/v1/documents?q=&type=&application_id=  -> company, job_title, application
     {id,status} alanlarıyla birlikte
   - GET /api/v1/documents/{id}/file?download=0|1  -> MinIO'dan stream, inline/attachment
   - GET /api/v1/applications?q=&status=&min_score=  -> documents özeti dahil
   - GET /api/v1/applications/{id}  -> job, skor+açıklama, documents, form analizi, events
   - PATCH /api/v1/applications/{id}/documents/{doc_id}  -> belgeyi elle bağla/ayır
   - POST /api/v1/applications/manual {url}  -> Job + Application oluştur (idempotent, fingerprint)

```python
@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: UUID, download: bool = False, svc=Depends(doc_service)):
    doc = await svc.get(doc_id)
    stream = await svc.open_stream(doc)          # MinIO'dan, private bucket
    disp = "attachment" if download else "inline"
    return StreamingResponse(
        stream, media_type=doc.content_type,
        headers={"Content-Disposition": f'{disp}; filename="{doc.filename}"'},
    )
```

3) FRONTEND:
   - Documents tablosu: sütunlar = Tür | Company · Job | Application (status rozeti, linkli) |
     Dosya (linkli, yeni sekmede açar). Kaldır: aday adı sütunu, version, created, ayrı
     Download/Open. Dil küçük rozet; created tooltip; varsayılan sıralama created desc.
   - Applications tablosu: Company · Job (detaya link) | Skor | Status | Belge rozetleri
     (CV/CL, tıklanınca dosya) | Güncellenme | Aksiyonlar.
   - Her tabloda arama kutusu + status/skor filtresi (client-side başla).
   - Yeni sayfa /applications/[id]: ilan+skor, belgeler (aç/indir/yeniden üret/elle bağla),
     form analizi, event zaman çizelgesi, mevcut aksiyon butonları, notlar alanı.
   - "URL ile ilan ekle" diyaloğu (Jobs veya Applications sayfasında).
   - Metinleri i18n dosyasına koy (tr/en), sabit string bırakma.

4) TEST: API testleri (q filtresi, file endpoint inline/attachment, manuel bağlama, manual
   create idempotency); bağlı olmayan belge listede boş Application ile görünmeli, hata
   vermemeli. Frontend için en az bir bileşen testi (belge linki doğru URL'ye gider).

SONUNDA: değişen dosyalar, çalıştırılan testler, kalan riskler, README güncellemesi.
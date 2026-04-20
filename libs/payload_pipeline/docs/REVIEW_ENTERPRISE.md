# Payload Pipeline — Enterprise Review

> Tarih: 2026-04-12 | Skor: 7.5/10
> Temel mimari sagam, ancak enterprise olcekte (1000+ listing/gun) kritik performans ve kaynak yonetimi sorunlari var.

---

## KRITIK — Performans

### 1. HTTP Connection Pooling yok
- **Dosya:** `games/r6/account/media/image_renderer.py:326`
- Her resim icin yeni TCP connection aciliyor (`requests.get()`)
- 30 resimli hesapta ~30 ayri connection = **10-50x yavas**
- **Cozum:** `requests.Session()` + `HTTPAdapter(pool_connections=10, pool_maxsize=10)`

### 2. Image download'lar sequential
- R6ImageRenderer resimleri tek tek indiriyor
- 50 skin x 500ms = 25 saniye bekleme
- ThreadPoolExecutor zaten mevcut (`shared/concurrency.py`)
- **Cozum:** Download'lari parallelize et — **5-10x hizlanma**

### 3. PIL Image handle leak'leri
- `Image.open(path)` sonrasi `.close()` cagirilmiyor
- Context manager (`with`) kullanilmiyor
- Cok sayida resim islendiginde file handle ve memory leak riski
- **Dosya:** `image_renderer.py:319-320`

---

## YUKSEK — Kaynak Yonetimi

### 4. ThreadPoolExecutor lifecycle
- **Dosya:** `shared/concurrency.py`
- Singleton executor sadece `atexit` ile kapaniyor
- Hot-reload/restart'ta orphaned thread'ler kalabilir
- **Cozum:** Context manager veya explicit lifecycle yonetimi

### 5. Cache eviction yok
- `R6ImageRenderer._skins_by_id` bir kez yukleniyor, hic temizlenmiyor
- PIL Image cache'leri de ayni sekilde
- Memory pressure under high load

### 6. Temp dosya cleanup'i yok
- Media pipeline `output/` altina dosya yaziyor
- Upload sonrasi temizleme yok — disk bloat riski

### 7. Cache yazma hatasi sessiz
- **Dosya:** `image_renderer.py:289-292`
- `except Exception: pass` — cache'e yazilamazsa log bile yok
- Sonraki cagri ayni resmi tekrar indirir

---

## ORTA — API Ergonomisi

### 8. marketplace_config type erasure
- Builder'lar runtime'da `isinstance` check yapiyor
- Yanlis tip gecilirse sessizce default'a dusur — debug'i zor
- **Cozum:** Init-time veya build-time type validation

### 9. Context key'ler stringly-typed
- `request.context[ctx.LZT_IMAGE_FETCHER]` — runtime'da key yoksa KeyError
- Tip kontrolu yok

### 10. Source parsing eksik ayrim
- `request.source("lzt")` — source yoksa bos dict donuyor
- "missing" ile "empty" ayrimi yapilmiyor

---

## ORTA — Kod Duplikasyonu (13 oyun x 4 marketplace)

### 11. Resolver credential boilerplate
- 10+ resolver'da ayni credential resolution pattern
- ~390 satir redundant kod
- **Cozum:** Base resolver veya utility function'a extract et

### 12. Eldorado bucketing method'lari
- Her Eldorado builder'da ayni tier-bazli bucketing pattern
- ~650 satir tekrar
- **Cozum:** Reusable bucketing strategy class

### 13. Composer template tekrari
- ListingDraft olusturma kodu hemen hemen ayni
- ~195 satir tekrar
- **Cozum:** Abstract base composer

### 14. `_normalize_image()` duplicate
- Val ve FN'de birebir ayni method
- `shared/` altina tasinabilir

---

## DUSUK — Eksiklikler

### 15. Media strategy coverage
- 13 oyunun sadece 3'unde media strategy var (Val, FN, R6)
- Diger 10 oyunda medya destegi yok

### 16. Pricing validation yok
- Negatif multiplier kabul ediliyor
- `forced_ending > 1.0` kabul ediliyor
- **Cozum:** `__post_init__` validation

### 17. Retry mekanizmasi sinirli
- Sadece Eldorado image upload'da retry var
- Dropbox/ImageShack upload'larinda retry yok, sadece timeout + warning

### 18. `PipelineResult` dead code
- Export ediliyor ama hicbir yerde instantiate edilmiyor

---

## R6 Image Caching Detayi

**Sonuc:** Ayni resim tekrar indirilMIYOR — disk cache duzgun calisiyor.

**Akis** (`image_renderer.py:276-295`):
1. Mevcut cache path kontrol (`cache/r6/skins/`, `cache/r6/operators/`)
2. Legacy cache dizinleri kontrol (3 eski path)
3. Hicbirinde yoksa indir ve cache'e kaydet

**Sorunlar:**
- Cache yazma hatasi sessiz (`except Exception: pass`) — basarisiz olursa sonraki cagri tekrar indirir
- Indirme sequential — parallelize edilebilir

---

## Oncelik Tablosu

| # | Is | Efor | Performans Etkisi |
|---|---|------|------------------|
| 1 | HTTP session pooling | Kucuk | 10-50x |
| 2 | Image download parallelization | Orta | 5-10x |
| 3 | PIL resource management | Kucuk | Memory safety |
| 4 | marketplace_config type safety | Orta | Guvenilirlik |
| 5 | Resolver credential helper | Orta | ~390 satir azalma |
| 6 | Bucketing/composer abstraction | Buyuk | ~1200 satir azalma |

---

## Marketplace Builder Coverage

| Oyun | Eldorado | G2G | GameBoost | PlayerAuctions | Media |
|------|----------|-----|-----------|----------------|-------|
| val | + | + | + | + | + |
| r6 | + | + | + | - | + |
| fn | + | + | + | + | + |
| cs2 | + | + | + | + | - |
| lol | + | + | + | + | - |
| coc | + | + | + | - | - |
| cr | + | + | + | - | - |
| gi | + | - | + | - | - |
| gtav | + | - | + | + | - |
| steam | + | - | + | - | - |
| roblox | + | - | + | - | - |
| bs | + | + | + | - | - |
| ubisoft | + | - | + | - | - |

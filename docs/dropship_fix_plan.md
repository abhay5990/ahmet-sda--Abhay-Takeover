# Dropship — Implementation Spec (AI hand-off)

> **Amaç:** Bu dosya, başka bir AI ajanının (veya geliştiricinin) bu repoda dropship sistemindeki tespit edilen hataları **birebir uygulayabilmesi** için yazılmıştır. Önceki analiz bağlamı olmadan, kendi kendine yeten talimatlardır.
> **Repo kökü:** `/home/ahmet/e-commerce-management-system`
> **Tarih:** 2026-06-06 · **Django:** 5.2.14 · **Branch önerisi:** `fix/dropship-stability`
> **Genel kural:** Her fix'i ayrı commit yap. Mevcut kod stiline (tip ipuçları, docstring, yorum yoğunluğu) uy. Değişiklikten önce ilgili dosyayı oku; aşağıdaki "MEVCUT" blokları birebir eşleşmeli, eşleşmiyorsa dosya değişmiş demektir — dur ve bildir.

---

## FIX 1 — 🔴 LZT bakım modu yanlış sınıflandırması (en yüksek öncelik, düşük risk)

**Sorun:** LZT bakım penceresinde "Engineering works. The market is temporarily unavailable." mesajı dönüyor; kod yalnızca "technical works" eşlediği için bunu maintenance yerine `server` hatası sayıyor → cleaner 5 ardışık hatadan sonra **1 saat cooldown'a** giriyor (son 14 günde ~28 saat offline).

**Dosya:** `libs/apis_sdk/apis_sdk/clients/marketplaces/lzt/client.py` (~satır 568-572)

**MEVCUT kod:**
```python
                    # LZT-specific: detect maintenance mode (503)
                    # LZT returns: "Технические работы // Technical works."
                    _lower = error_text.lower()
                    if "technical works" in _lower or "технические работы" in _lower:
                        details["maintenance"] = True
```

**HEDEF kod:**
```python
                    # LZT-specific: detect maintenance mode (503).
                    # LZT has used several phrasings over time:
                    #   "Технические работы // Technical works."
                    #   "Engineering works. The market is temporarily unavailable."
                    _lower = error_text.lower()
                    _MAINTENANCE_PHRASES = (
                        "technical works",
                        "технические работы",
                        "engineering works",
                        "the market is temporarily unavailable",
                    )
                    if any(phrase in _lower for phrase in _MAINTENANCE_PHRASES):
                        details["maintenance"] = True
```

**Neden güvenli:** `details["maintenance"]=True` set edilince `backend/apps/posting/services/dropship/backoff.py` içindeki `classify_api_error` zaten `'maintenance'` döndürüyor (ilk kontrol satır ~95), ve `cleaner.py` (satır ~197) bunu `MAINTENANCE_WAIT = 120s` bekleme dalına yönlendiriyor — 1 saatlik cooldown yerine. Eşleşmeler spesifik olduğu için yanlış pozitif riski düşük.

**Doğrulama:**
- `grep -n "maintenance" backend/apps/posting/services/dropship/backoff.py` → `details.get('maintenance')` kontrolünün hâlâ orada olduğunu teyit et.
- Mümkünse `libs/apis_sdk` altında client testlerine "Engineering works..." mesajıyla bir vaka ekle ve `classify_api_error(...) == 'maintenance'` doğrula.

---

## FIX 2 — 🟠 Persistent MySQL bağlantıları bayatlıyor ("Lost connection to MySQL server")

**Sorun:** Uzun ömürlü dropship worker süreçlerinde `CONN_MAX_AGE=600` ile tutulan MySQL bağlantısı, sunucu tarafında idle/`wait_timeout` ile kapanıyor; sonraki sorgu "Lost connection to MySQL server during query" (hata 2013/4031) veriyor (son 2 günde ~16 kez, dropbox token yenilemede görünür).

**Dosya:** `backend/config/settings/base.py` (~satır 107-121, MySQL `DATABASES` bloğu)

**MEVCUT kod:**
```python
    DATABASES = {
        'default': {
            'ENGINE': _db_engine,
            'NAME': config('DB_NAME', default='inventory_manager'),
            'USER': config('DB_USER', default='root'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='3306'),
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
```

**HEDEF kod:** (`CONN_HEALTH_CHECKS` satırını ekle — Django 4.1+; bizde 5.2 var)
```python
    DATABASES = {
        'default': {
            'ENGINE': _db_engine,
            'NAME': config('DB_NAME', default='inventory_manager'),
            'USER': config('DB_USER', default='root'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='3306'),
            'CONN_MAX_AGE': 600,
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
```

**Neden güvenli:** `CONN_HEALTH_CHECKS=True`, Django'nun her istek/döngü başında bağlantıyı doğrulayıp bayatsa şeffafça yeniden kurmasını sağlar. Davranışsal yan etkisi yok, yalnızca dayanıklılık artar.

**Doğrulama:** `python backend/manage.py check` hatasız geçmeli. Deploy sonrası journal'da "Lost connection to MySQL" sıklığının düşmesini izle.

---

## FIX 3 — 🔴 "Maximum of N active offers" kalıcı kapatmaya yol açıyor

**Sorun:** Variant-routing'i olmayan platformlarda (ör. PlayerAuctions, 200-offer cap) mağaza dolduğunda dönen `{"code":400,"messages":["Maximum of 200 active offers is allowed."]}` hatası, validation sayılıyor → 1 saatte 3 kez → poster **kalıcı olarak** `enabled=False` yapılıyor ve kendiliğinden geri dönmüyor. (Poster #2 bir aydır bu sebeple kapalı.)

**Kök neden:** `backend/apps/posting/services/dropship/poster.py` satır 496'daki max-offer kontrolü `and game.slug in PLATFORM_PRIORITY` kapısıyla sınırlı. `is_max_offer_error()` mesajı zaten platform-bağımsız yakalıyor (`apps/posting/services/shared/max_offer_error.py` → `'active offers is allowed'`), ama variant'ı olmayan platform bu kapıdan geçemediği için validation dalına düşüyor.

**Önerilen yaklaşım:** Mağaza-dolu durumunu kalıcı kapatmadan ayır. Variant'ı olmayan platformda max-offer = "mağaza dolu" → bu cycle için kalan post'ları atla, **validation sayma, kalıcı kapatma**. Sonraki cycle'da (ürünler satılıp yer açılınca) tekrar denenir.

**Adım 3a — yeni exception ekle.** `poster.py` ~satır 83 civarı (diğer `_MaxOfferError` exception'ının yanına):
```python
class _StoreFullError(Exception):
    """Marketplace store hit its active-offer cap (e.g. PA 200). Capacity
    condition, NOT a payload problem — pause this cycle, do not disable."""
```

**Adım 3b — max-offer'ı tüm platformlar için yakala.** `poster.py` satır 494-499:

MEVCUT:
```python
    if not api_result.ok:
        # Check max offer error before generic classification
        if is_max_offer_error(api_result) and game.slug in PLATFORM_PRIORITY:
            err = api_result.error
            msg = f"Max offer limit: {err.message}" if err else "Max offer limit reached"
            raise _MaxOfferError(msg, variant_slug=variant_slug or '')
```

HEDEF:
```python
    if not api_result.ok:
        # Check max offer error before generic classification
        if is_max_offer_error(api_result):
            err = api_result.error
            msg = f"Max offer limit: {err.message}" if err else "Max offer limit reached"
            if game.slug in PLATFORM_PRIORITY:
                # Variant platform (Eldorado): try the next variant slot
                raise _MaxOfferError(msg, variant_slug=variant_slug or '')
            # Non-variant platform (e.g. PlayerAuctions): whole store is full
            raise _StoreFullError(msg)
```

**Adım 3c — item döngüsünde yakala ve cycle'ı nazikçe durdur.** `poster.py` içinde, bir `target_url` için item'ları işleyen for-döngüsündeki except zincirine (mevcut `except _MaxOfferError as e:` ~satır 251 ile `except _RateLimitError:` ~satır 307 arasına) şu bloğu ekle:
```python
        except _StoreFullError as e:
            _item_id = source_provider.extract_item_id(item)
            logger.info(
                "Store full for %s/%s (%s) — stopping posts this cycle",
                config.game.slug, config.store.name, e,
            )
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.INFO,   # INFO/WARNING — NOT counted toward pause
                message=f"Store full — posting paused this cycle: {config.store.name}",
                detail={'config_id': config.id, 'item_id': _item_id, 'error': str(e)},
                integration_account=config.store,
            )
            break   # exit the items loop for this URL; cycle retries next interval
```
> **Önemli:** `tracker.on_validation_error(...)` ÇAĞIRMA. Amaç tam olarak bunu validation sayımından çıkarmak. `break` bu URL'nin item döngüsünü bitirir; üst akış URL istatistiklerini günceller ve normal şekilde bir sonraki cycle'a geçer.

**Adım 3d — kapalı kalan Poster #2'yi elle aç (deploy sonrası, opsiyonel).** Düzeltme canlıya alınınca, daha önce bu sebeple kapanan config'i geri aç:
```python
# python backend/manage.py shell
from apps.posting.models import DropshippingJobConfig
c = DropshippingJobConfig.objects.get(id=2)
c.disabled_reason = ''
c.enabled = True
c.save(update_fields=['disabled_reason', 'enabled'])
```

**Doğrulama:** `is_max_offer_error` testlerini koştur. Mantığı izle: variant platformda eski davranış korunmalı (variant fallback), variant olmayan platformda `_StoreFullError` → break → kalıcı kapatma YOK.

---

## FIX 4 — 🟡 Cleaner: ürün-başına `refresh_from_db` (performans, isteğe bağlı)

**Sorun:** `backend/apps/posting/services/dropship/cleaner.py` ~satır 108, her LISTED ürün için ayrı bir `SELECT enabled` atıyor (binlerce gereksiz sorgu/cycle).

**MEVCUT (özet):** Her ürün döngüsünde:
```python
            # DB stop check before each product
            cleaner_config.refresh_from_db(fields=['enabled'])
            if not cleaner_config.enabled:
                stop_event.set()
                break
```

**HEDEF yaklaşım:** Her item yerine N item'da bir (ör. her 50) veya zaman-bazlı (ör. 30sn'de bir) kontrol et. Örnek (enumerate sayacıyla):
```python
        for idx, dp_id in enumerate(listed_ids):
            if stop_event.is_set():
                break

            # DB stop check throttled: every 50 items instead of every item
            if idx % 50 == 0:
                cleaner_config.refresh_from_db(fields=['enabled'])
                if not cleaner_config.enabled:
                    stop_event.set()
                    break
            ...
```
> Döngü başındaki `for dp_id in listed_ids:` ifadesini `for idx, dp_id in enumerate(listed_ids):` yap. `stop_event` kontrolü her item'da kalmalı (ucuz, in-memory); sadece DB sorgusu throttle edilir. Bu, kullanıcının "disable" komutuna tepkiyi en fazla 50 item geciktirir — kabul edilebilir.

**Doğrulama:** Cleaner cycle süresinin kısaldığını, DB sorgu sayısının düştüğünü gözle (gerekirse Django debug toolbar / slow query log).

---

## Kod-DIŞI / ayrı ele alınacaklar (bu PR kapsamında DEĞİL)

- **PA Token Service kapalı (ops):** `localhost:8976` çalışmıyor → PA order/offer sync ve cleaner'ın PA delist'i başarısız. Servisi ayağa kaldır / systemd ile kalıcılaştır. Kod değişikliği değil.
- **Eldorado Cognito "Password attempts exceeded" (doğrula):** 18-30 Mayıs arası 541 görsel-yükleme hatası; muhtemelen son commit'lerle (`111a556`, `dd94a87`) çözüldü. 30 Mayıs sonrası tekrar görülmüyorsa kapat.
- **ImageShack SSL/timeout (düşük):** Medya fallback adaptörü kararsız; retry/timeout politikası veya fallback önceliği gözden geçirilebilir.
- **Re-post backlog / churn (tasarım gerektirir):** `deleted=5985` vs `listed=2255`. Fiyat değişiminde tam delist+repost yerine fiyat-güncelleme (edit) yolu; `DELETED` statüsünü "re-post bekliyor" vs "kalıcı silindi" olarak ayırma. Ayrı tasarım çalışması — aceleye getirme.

---

## Test & teslim

1. `cd backend && python manage.py check` — temiz geçmeli.
2. Varsa dropship/backoff/lzt-client testlerini koştur:
   `cd backend && python -m pytest apps/posting/ -k "dropship or backoff" -q` (veya repo'nun test komutu).
   `cd libs/apis_sdk && python -m pytest -k "lzt or maintenance" -q`
3. Her fix ayrı commit. Önerilen mesajlar:
   - `fix(dropship): detect LZT 'engineering works' maintenance phrasing`
   - `fix(db): enable CONN_HEALTH_CHECKS to recover stale MySQL connections`
   - `fix(dropship): treat store-full (max offers) as transient, not a permanent pause`
   - `perf(dropship): throttle cleaner enabled-check DB query`
4. Push → uzaktan pull → `ecom-dropship` servisini restart et → journal'da Bulgu 1/2/FIX2 sinyallerinin azaldığını doğrula.

> Commit gövdelerinin sonuna (repo kuralı):
> `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

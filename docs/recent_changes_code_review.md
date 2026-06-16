# Son Güncellemeler Kod İnceleme Raporu

Tarih: 2026-06-17  
Kapsam: Mevcut `master` çalışma ağacındaki commitlenmemiş değişiklikler ve yeni untracked dosyalar.

## Git Kapsamı

- Aktif branch: `master`
- `master` durumu: `origin/master` ile aynı committe. Bu branch üzerinde pushlanmamış commit yok.
- İncelenen asıl kapsam: modified + untracked working tree değişiklikleri.
- Önemli untracked eklemeler:
  - `backend/apps/posting/services/offer_editor.py`
  - `libs/payload_pipeline/payload_pipeline/games/{fh5,fh6,nw,psn,rust,xbox}/`
  - `libs/payload_pipeline/tests/unit/test_{fh5,fh6,new_world,psn,rust,xbox}.py`
  - `assets/eldorado_templates/accounts/forza-horizon-6.json`
  - `docs/old sda features.pdf`

Not: `git branch -vv` başka worktree branchlerinde ahead commitler gösteriyor:
`feature/content-template-builder` ahead 1, `feature/pipeline-architecture-cleanup` ahead 3/behind 2. Bu rapor mevcut workspace `master` değişikliklerine odaklandı.

## Doğrulama

Çalıştırılan komutlar:

```powershell
cd libs/payload_pipeline
..\..\venv\Scripts\python.exe -m pytest tests/unit/test_fh5.py tests/unit/test_fh6.py tests/unit/test_new_world.py tests/unit/test_psn.py tests/unit/test_rust.py tests/unit/test_xbox.py tests/unit/test_lol.py -q
```

Sonuç: `174 passed`, `2 failed`.

Kırılan testler:

- `tests/unit/test_lol.py::test_lol_pipeline_builds_eldorado_payload`
- `tests/unit/test_lol.py::test_lol_pipeline_builds_all_marketplace_payloads`

Hata:

```text
Eldorado image upload requested but no uploader is configured.
Pass an uploader via EldoradoConfig.image_uploader.
```

Bu, LoL testlerinin medya üretimini kapatmadan Eldorado build çalıştırmasından kaynaklanıyor. Test izolasyonu için ya `ctx.DISABLE_MEDIA: True` verilmeli ya da fake `EldoradoConfig.image_uploader` enjekte edilmeli.

```powershell
cd backend
..\venv\Scripts\python.exe manage.py check
```

Sonuç: `System check identified no issues`.

## Yüksek Öncelikli Bulgular

### 1. New World GameBoost UI'da seçilebilir, fakat account pipeline GameBoost desteklemiyor

Kanıt:

- `backend/apps/posting/views.py:24-28` provider desteğini `GamePlatformMapping` üzerinden game-level hesaplıyor.
- `backend/data/game_mapp.json:2414-2426` `new-world` için `gameboost` mapping içeriyor.
- `libs/payload_pipeline/payload_pipeline/games/nw/account/__init__.py:15-22` `new-world:account` sadece `eldorado` ve `playerauctions` register ediyor.
- `libs/payload_pipeline/payload_pipeline/games/nw/item/__init__.py:15-21` `gameboost` sadece `new-world:item` altında var.
- `backend/apps/posting/pipeline/request.py:54-56` Django adapter her isteği `ListingCategory.ACCOUNT` olarak oluşturuyor.

Mevcut durum:

```py
# backend/apps/posting/pipeline/request.py
return PipelineRequest(
    game=game_slug,
    category=ListingCategory.ACCOUNT,
    kind=kind,
    sources=sources,
    context=ctx,
)
```

Registry doğrulaması:

```text
new-world account: ['eldorado', 'playerauctions']
new-world item: ['gameboost']
```

Etkisi:

New World seçildiğinde UI GameBoost store'u destekli gibi gösterebilir. Kullanıcı GameBoost'a post etmeye çalışırsa worker `new-world:account` için GameBoost builder bulamayacak ve job item fail olacak. Testler `new-world:item` builder'ını doğruluyor ama mevcut UI/worker yolu o category'yi hiç çağırmıyor.

Öneri:

Ya category seçimi uçtan uca desteklenmeli:

```py
def build_request(
    *,
    game_slug: str,
    category: ListingCategory = ListingCategory.ACCOUNT,
    ...
) -> PipelineRequest:
    return PipelineRequest(
        game=game_slug,
        category=category,
        kind=kind,
        sources=sources,
        context=ctx,
    )
```

Ya da kısa vadede New World account flow için GameBoost UI'dan kapatılmalı. Provider filtresi `GamePlatformMapping` yerine pipeline capability bilgisini de dikkate almalı.

### 2. Multi-credential posting sadece GTA diye yorumlanmış ama tüm manual Eldorado/GameBoost joblarına uygulanıyor

Kanıt:

- `backend/apps/posting/services/stock/consumer.py:110-116`
- `backend/apps/posting/services/stock/consumer.py:274-279`

Mevcut kod:

```py
use_multi_cred = (
    self._is_multi_cred_job(job)
    and marketplace in ('eldorado', 'gameboost')
    and len(entries) > 1
)

@staticmethod
def _is_multi_cred_job(job: PostingJob) -> bool:
    manual = job.settings.get('_manual', {})
    if not isinstance(manual, dict):
        return False
    return manual.get('source_type') == 'manual'
```

Etkisi:

Yorum ve docstring "GTA manual" diyor, fakat koşul sadece `source_type == manual`. Bu yüzden FH5, FH6, Rust, PSN, Xbox gibi yeni manual oyunlarda aynı store'a birden fazla credential gönderilirse tek bir marketplace offer altında birleştirilebilir. Eğer ürün modeli "her credential ayrı offer" ise bu ciddi davranış hatasıdır.

Öneri:

Davranış gerçekten sadece GTA içinse gate açık yazılmalı:

```py
@staticmethod
def _is_multi_cred_job(job: PostingJob) -> bool:
    manual = job.settings.get('_manual', {})
    return (
        isinstance(manual, dict)
        and manual.get('source_type') == 'manual'
        and job.game.slug == 'grand-theft-auto-5'
        and manual.get('multi_credential', True) is True
    )
```

Daha temiz çözüm: UI job settings'e explicit `multi_credential_offer: true` yazsın. Servis oyun slug'ından inference yapmak yerine bu capability flag'i okusun.

### 3. PlayerAuctions single edit, eski offer'ı doğrulama yapmadan iptal ediyor

Kanıt:

- `backend/apps/posting/services/offer_editor.py:204-235`
- `backend/apps/posting/services/offer_editor.py:245-268`

Mevcut akış:

```py
# Step 1: Cancel existing offer
cancel_result = provider.delete_listing(client, listing.store_listing_id)

# Step 2: Rebuild payload with changes
raw = listing.raw_data or {}
original_payload = extract_create_payload(raw, 'playerauctions', client=client, proxy_group=proxy_group)
if not original_payload:
    return EditResult(ok=False, error='No original payload found - listing has no raw_data')
```

Etkisi:

`raw_data` eksikse veya payload extract edilemiyorsa kod bunu eski offer iptal edildikten sonra fark ediyor. Aynı risk recreate API failure için de var: remote offer silinmiş oluyor, local `Listing` ise hala `listed` ve eski `store_listing_id` ile kalabiliyor.

Öneri:

Recreate için gereken her şey iptalden önce hazırlanmalı:

```py
raw = listing.raw_data or {}
original_payload = extract_create_payload(raw, 'playerauctions', client=client, proxy_group=proxy_group)
if not original_payload:
    return EditResult(ok=False, error='No original payload found')

lop = listing.listing_owned_products.select_related('owned_product').first()
if not lop:
    return EditResult(ok=False, error='No linked credential found')

_apply_pa_changes(original_payload, changes)
_apply_pa_auto_delivery_credentials(original_payload, lop.owned_product, pool=effective_pool)

# Only now cancel old remote offer.
cancel_result = provider.delete_listing(client, listing.store_listing_id)
```

Ek olarak recreate başarısız olursa local state açıkça işaretlenmeli:

```py
listing.status = ListingStatus.DELETED
listing.removed_at = timezone.now()
listing.raw_data = {**(listing.raw_data or {}), 'edit_recreate_failed': str(exc)}
listing.save(update_fields=['status', 'removed_at', 'raw_data', 'updated_at'])
```

### 4. PlayerAuctions pool bulk edit yeni Listing oluşturuyor, eski Listingleri deaktif etmiyor

Kanıt:

- `backend/apps/posting/services/offer_editor.py:298-328`
- `backend/apps/posting/services/offer_editor.py:436-459`
- `backend/apps/posting/services/offer_editor.py:481`

Mevcut başarı yolu:

```py
new_listing = Listing.objects.create(
    is_instant=True,
    integration_account=store,
    game=pool.game,
    store_listing_id=new_offer_id,
    variant=pool.listing.variant,
    title=changes.get('title', pool.listing.title),
    price=changes.get('price', pool.listing.price),
    currency=pool.listing.currency,
    raw_data=pool.listing.raw_data,
)

ao.store_listing_id = new_offer_id
ao.listing = new_listing
ao.save(update_fields=['store_listing_id', 'listing', 'updated_at'])
```

Eksik:

`ao.listing` ile daha önce bağlı olan eski clone listing `deleted/closed` yapılmıyor ve eski `ListingOwnedProduct` linkleri temizlenmiyor. Sonuçta aynı credential için hem eski hem yeni local listing aktif kalabilir. Bu, sync/order matching ve stock status hesaplarını bozabilir.

Öneri:

Recreate başarılı olduğunda eski listingleri transaction içinde deaktive edin:

```py
old_listing = ao.listing

new_listing = Listing.objects.create(...)
ListingOwnedProduct.objects.create(
    listing=new_listing,
    owned_product=ao.pool_item.owned_product,
)

if old_listing:
    old_listing.status = ListingStatus.DELETED
    old_listing.removed_at = timezone.now()
    old_listing.save(update_fields=['status', 'removed_at', 'updated_at'])
    ListingOwnedProduct.objects.filter(listing=old_listing).delete()

ao.store_listing_id = new_offer_id
ao.listing = new_listing
ao.save(update_fields=['store_listing_id', 'listing', 'updated_at'])
```

### 5. Yeni oyun variantları test fixture'larında var, DB seed migration'ında yok

Kanıt:

- `libs/payload_pipeline/tests/unit/_variant_ctx.py` FH5, New World ve Rust variant context fixture'ları ekliyor.
- `backend/apps/posting/migrations/0010_game_variant_system.py` seed datası sadece Fortnite, GTA V, R6, Valorant, LoL, Genshin kapsıyor.
- `backend/apps/posting/services/variant_context.py:25-130` runtime variant context'i DB'deki `GameVariant`, `GameVariantMapping`, `GameVariantLimit` kayıtlarından kuruyor.

Etkisi:

Payload unit testleri fake `variant_context` ile geçiyor; production worker ise DB'de variant seed yoksa FH5/Rust/New World için external trade environment mapping'i bulamayabilir veya capacity routing beklenenden farklı çalışabilir.

Öneri:

Yeni bir migration ile en azından bu oyunların runtime variantları seed edilmeli:

```py
NEW_GAME_VARIANTS = {
    'forza-horizon-5': [('platform', FH5_PLATFORMS)],
    'new-world': [('region', NW_REGIONS)],
    'rust': [('platform', RUST_PLATFORMS)],
}
```

Ayrıca test sadece pipeline builder'ı değil, Django `build_variant_context()` çıktısını da doğrulamalı.

## Orta Öncelikli Bulgular

### 6. Non-PA consumer her durumda tüm queue'yu drain edip sonra işlemeye başlıyor

Kanıt:

- `backend/apps/posting/services/stock/consumer.py:95-104`

Mevcut kod:

```py
entries: list[tuple[PostingJobItem, dict]] = []
while True:
    entry = queue.get()
    if entry is self._sentinel:
        break
    entries.append(entry)
```

Etkisi:

Bu multi-credential batch için mantıklı, fakat standart tekil posting'de producer/consumer paralelliğini azaltıyor. Önceden prepare edilen item hemen post edilmeye başlanabiliyordu; şimdi store thread sentinel gelene kadar bekliyor. Büyük joblarda ilk post gecikir, cancel/rate-limit etkisi geç görünür.

Öneri:

Queue sadece multi-credential capability varsa batch'e alınmalı. Standart path streaming kalmalı:

```py
if self._should_buffer_for_multi_cred(job, first_item):
    entries = self._drain_all(queue)
    return self._process_multi_cred_batch(entries, job)

for item, prepared_data in self._iter_queue(queue):
    self._process_item(...)
```

### 7. Edit API price validation para için zayıf

Kanıt:

- `backend/apps/listings/views.py:200-208`
- `backend/apps/posting/api/pool.py:388-393`

Mevcut kod:

```py
if 'price' in body and body['price'] is not None:
    changes['price'] = round(float(body['price']), 2)
```

Riskler:

- `float` para için precision riski taşır.
- `0`, negatif veya marketplace minimumunun altındaki fiyatlar engellenmiyor.
- Boş string ile title/description temizlemek mümkün değil, çünkü `if body['title']` false olur.

Öneri:

```py
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def _parse_price(value: object) -> Decimal:
    try:
        price = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid price')
    if price <= 0:
        raise ValueError('Price must be greater than zero')
    return price
```

Title/description için de `"field" in body` kontrolü ile boş string bilinçli update edilebilmeli veya API açıkça "empty value not allowed" demeli.

### 8. Pool edit partial failure stratejisi daha açık olmalı

Kanıt:

- `backend/apps/posting/api/pool.py:401-409`
- `frontend/templates/posting/restock_pool_detail.html:644-676`

Mevcut API `207` döndürüyor ve frontend sayfayı reload ediyor. Bu iyi bir başlangıç; fakat PA bulk edit'te remote cancel başarılı, recreate kısmi başarısız olabilir. Bu durumda hangi credentials pending'e döndü, hangi local listing deaktive edildi, hangi old offer remote'da artık yok gibi lifecycle state'leri ayrı event olarak yazılmalı.

Öneri:

`BulkEditResult` içine `cancelled_offer_ids`, `recreated_offer_ids`, `returned_pool_item_ids`, `deactivated_listing_ids` alanları eklenmeli. UI sadece sayı değil, aksiyon alınabilir detay göstermeli.

## Test Eksikleri

Eklenmesini önerdiğim testler:

1. New World provider/category entegrasyonu:
   - `new-world + gameboost + account` UI/worker tarafından seçilememeli.
   - `new-world + gameboost + item` seçilecekse request category uçtan uca `ITEM` taşınmalı.

2. Multi-credential gate:
   - GTA manual + Eldorado + 2 credential -> tek offer.
   - FH5/Rust/PSN manual + Eldorado/GameBoost + 2 credential -> varsayılan olarak iki ayrı offer.

3. PA single edit failure:
   - `raw_data` boşsa `delete_listing` hiç çağrılmamalı.
   - recreate failure olursa local listing stale `listed` kalmamalı.

4. PA pool bulk edit:
   - Başarılı recreate sonrası eski listing `DELETED` olmalı.
   - Eski `ListingOwnedProduct` linkleri temizlenmeli.

5. Runtime variant seed:
   - `build_variant_context(store, fh5, eldorado)` DB seed sonrası `PC/Xbox/PS5` mapping döndürmeli.
   - `build_variant_context(store, rust, eldorado)` `PC/PlayStation/Xbox` mapping döndürmeli.
   - `build_variant_context(store, new-world, eldorado/playerauctions)` region mapping döndürmeli.

## Repo Hijyeni

- `docs/old sda features.pdf` binary dosyası untracked. Ürüne ait kalıcı dokümansa isimlendirme ve konumu netleştirilmeli; değilse commit dışı kalmalı.
- `backend/data/game_mapp.json` diff'i dosya sonunda newline kaldırmış görünüyor. JSON geçerli ama repo standardı için newline korunmalı.
- `git diff` bazı dosyalarda LF -> CRLF uyarısı verdi. `.gitattributes` ile line ending standardı sabitlenmeli.
- Yeni oyun dizinlerinde lokal `__pycache__` dosyaları görülüyor. `.gitignore` bunları kapsıyor, yine de commit öncesi çalışma ağacından temizlemek iyi olur.

## Genel Değerlendirme

Yeni özelliklerin yönü doğru: provider filtreleme, yeni payload slice'ları, offer edit ve multi-credential restock gibi enterprise app için gerekli operasyonel kabiliyetler eklenmiş. En kritik açıklar integration boundary tarafında:

- UI capability ile pipeline registry capability aynı kaynaktan gelmiyor.
- Remote marketplace state değiştikten sonra local DB state her hata yolunda güvenli kapanmıyor.
- Testler pipeline unit seviyesinde güçlü ama Django runtime entegrasyonunu ve failure recovery'yi yeterince yakalamıyor.

Öncelik sırası:

1. New World provider/category mismatch'i kapat.
2. PA edit akışında cancel-before-validate ve stale listing problemini düzelt.
3. Multi-credential gate'i explicit capability yap.
4. Yeni oyun variantlarını DB migration ile seed et.
5. Price/update validation ve queue streaming performansını temizle.

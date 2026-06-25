# Posting — Start Post Hata Analizi (24 Haziran 2026)

> **Kapsam:** Son güncelleme/restart sonrası (gunicorn restart: **2026-06-24 08:48:51 UTC**, `pull → 28f0726`)
> Posting → **Start Post** ekranından başlatılan tüm stock-post job'ları.
> **İncelenen job aralığı:** `#77 – #90` (14 job)
> **Yöntem:** `posting_jobs` / `posting_job_items` / `posting_logs` tabloları + kod kök-neden incelemesi.
> **Not:** Bu rapor yalnızca tespit/analizdir — kodda değişiklik yapılmadı. Düzeltmeler local'de yapılıp pull edilecek.

## Güncellemeyle Gelen Commit'ler

Restart'tan hemen önce pull edilen, bu testleri etkileyen commit'ler:

| Commit | Tarih | Özet |
|---|---|---|
| `28f0726` | 06-24 11:45 | **Add Roblox API integration** and enhance OfferPool management |
| `de80a2f` | 06-23 11:27 | Add FirstMail and Proxyline service client methods |
| `78c531d` | 06-21 15:08 | Enhance **stock processing and image handling** in posting services |
| `f3f6fa2` | 06-17 22:39 | **Refactor image preset handling** and enhance error messages |
| `484c8e5` | 06-13 20:05 | New **CredentialSpec** model + posting updates |

---

## Özet Tablo

| # | Job(lar) | Oyun | Pazar | Hata | Sınıf | Tip |
|---|---|---|---|---|---|---|
| 1 | #77, #78 | Fortnite | eldorado/gameboost/PA | Proxy connection refused | Altyapı | Geçici — kod değil |
| 2 | #79–#84 | (hepsi) | **playerauctions** | `Unauthorized (authentication)` | **Kod/Tasarım** | **Gerçek regresyon (tasarım açığı)** |
| 3 | #89 | Counter-Strike 2 | gameboost | `image_urls must be an array` | **Kod** | **Regresyon (image refactor)** |
| 4a | #82 | Clash of Clans | eldorado | `clash-of-clans-current-rank not set` | **Kod** | Eksik attribute mapping |
| 4b | #86 | Roblox | eldorado | `roblox-account-type not set` | **Kod** | Yeni oyun — eksik builder |
| 4c | #87 | Genshin Impact | eldorado | `Trade Environment combination invalid` | **Kod** | Region→trade-env eşleme hatası |
| 5 | #87 | Genshin Impact | gameboost | `minimum price ... 0.99 €` | Veri/Config | Fiyat min altında |
| 6 | #88, #90 | Rust / Roblox | (resolve) | `requires the 'manual'/'lzt' source` | Veri/Config | Beklenen validation |
| 7 | #80 | R6 Siege | gameboost | `already listed with this login` | Veri | Beklenen (tekrar test) |

**Öncelik sırası (gerçek kod hataları):** `#2 PlayerAuthorized` → `#3 CS2 image_urls` → `#4a/4b/4c Eldorado attribute`.

---

## 1) Proxy Connection Refused — Altyapı (kod değil)

**Job'lar:** #77 (Fortnite/eldorado), #78 (3 item: eldorado + gameboost + PA)
**Saat:** 08:49 – 09:37
**Hata örneği:**
```
[build] Image upload failed for fortnite_exclusive.png after 2 attempts:
Proxy error ... ProxyError('Unable to connect to proxy',
NewConnectionError("HTTPSConnection(host='154.219.208.141', port=63208):
[Errno 111] Connection refused"))
```

**Kök neden:** Çıkış proxy'leri (`154.219.208.141:63208`, `154.219.209.194:63292`) o anda ayaktaydı değildi → "Connection refused". Tüm pazarlarda (eldorado, gameboost, PA) aynı anda görülmesi proxy'nin tamamen down olduğunu gösteriyor.

**Kanıt — geçici olduğu:** 09:48'den (Job #79) itibaren aynı login ile eldorado **ve** gameboost başarıyla post edildi → proxy toparlandı. Bu bir **kod regresyonu değil**, ağ/proxy kesintisi.

**Aksiyon:** Kodla ilgisi yok. İstenirse proxy health-check + yeniden deneme stratejisi iyileştirilebilir, ama bu hatalar bu rapordaki düzeltmelerin kapsamı dışında.

---

## 2) PlayerAuctions — `Unauthorized (authentication)` ⚠️ EN KRİTİK

**Job'lar:** #79, #80, #81, #82, #83, #84 — **restart sonrası HER PlayerAuctions post'u başarısız** (store: `Csgosmurfkings`). Hiç başarılı PA post'u yok.
**Stage:** `build_playerauctions`
**Hata:** `API error: Unauthorized (category=authentication)`

### Kök Neden: Bayat (expired) token + token-refresh tasarım açığı

PA auth akışı:
- **Credential kaynağı:** `apps/integrations/providers/playerauctions.py:62-74` → `IntegrationCredential.credentials` JSON'undan `access_token` okunur.
- **Header:** `libs/apis_sdk/.../playerauctions/auth.py:160-162` → `Authorization: Bearer {access_token}`. `_expires_at = inf` (auth.py:80-81) olduğu için **proaktif yenileme asla çalışmaz** — yenileme yalnızca 401 sonrası reaktif olarak retry path'inde tetiklenir.
- **401 → AUTHENTICATION:** `libs/apis_sdk/.../playerauctions/client.py:668`.

**Asıl tasarım açığı:** Stock-post yolu **bulk Excel upload** kullanır ve bu yol `execute_once` ile çağrılır (retry **yok**, dolayısıyla 401-refresh **yok**):
- `apps/posting/services/stock/consumer.py:713` → `PABulkUploader.upload_batch`
- `libs/apis_sdk/.../playerauctions/facade.py:316-325` → `bulk_upload` → `_exec.execute_once(...)` ("non-idempotent, no retry")
- Reaktif refresh sadece `execute_with_retry` yolunda var (`libs/apis_sdk/.../infrastructure/retry/runtime.py:76-80`) — bulk yolu buraya hiç girmez.

**Ek açık:** Refresh edilen token **DB'ye geri yazılmıyor.** `set_tokens`/`_do_refresh` (auth.py:91-95,153) yalnızca in-memory `_access_token`'ı günceller. DB'ye yazan `update_token` (`apps/integrations/models.py:110`) sadece Eldorado Cognito broker'ı tarafından çağrılır (`token_broker.py:99`); PA bu broker kapsamında değil (`token_broker.py:26`).

### Neden tam olarak restart anında başladı?

Restart öncesi process'in **belleğinde** geçerli bir PA token'ı vardı (daha önce bir retryable çağrıda reaktif yenilenmişti). Restart → bellek silindi → yeni facade DB'deki **bayat** `credentials['access_token']` ile kuruldu → bulk yolu bunu yenileyemediği için her PA post'u 401.

**Kanıt — token bayat ama altyapı sağlam:** `tmp/sync_logs/playerauctions-csgosmurfkings.log` içinde sync tarafı (retryable read kullanır) `Refreshing PlayerAuctions token via microservice → ... refreshed successfully` logluyor. Yani username/password ve token servisi **geçerli**; sorun sadece bulk-post yolunun token'ı yenileyememesi ve yenilenen token'ın DB'ye yazılmaması.

**484c8e5 (CredentialSpec) suçlu mu? — Hayır.** O commit yalnızca token-servis URL'ini (`localhost:8976 → 31.57.156.36:8976`) ve `X-API-Key` header'ını değiştirdi; refresh çalışıyor. `build_client`'ın `access_token` okuma şeklini değiştirmedi. Bu, o commit'in regresyonu değil; restart'ın açığa çıkardığı **latent tasarım açığı**.

### İlgili dosyalar
- `apps/integrations/providers/playerauctions.py:62-74` — credential/client kurulumu
- `libs/apis_sdk/.../playerauctions/auth.py:80-81,160-162` — sonsuz expiry + Bearer header
- `libs/apis_sdk/.../playerauctions/facade.py:316-325` — `bulk_upload` → `execute_once` (refresh yok)
- `libs/apis_sdk/.../_facade_support.py:447-465` (execute_once) vs `382-445` (execute_with_retry)
- `libs/apis_sdk/.../infrastructure/retry/runtime.py:76-80` — reaktif refresh (sadece retry yolunda)

### Önerilen düzeltme yönü (uygulanmadı)
1. PA bulk-upload öncesi token geçerliliğini proaktif kontrol et / refresh et (`bulk_upload` çağrılmadan önce), **veya**
2. `execute_once` yoluna da 401→refresh→tek-retry ekle, **ve**
3. Refresh edilen PA token'ını `IntegrationCredential`'a geri yaz (Eldorado broker'ındaki `update_token` mantığı gibi) ki restart sonrası bayat kalmasın.

---

## 3) Gameboost — `image_urls must be an array of image URLs` (CS2)

**Job:** #89 — Counter-Strike 2, store `EzSmurfMart`, login `somilee217`
**Stage:** `build_gameboost`
**Hata:** `API error: The image_urls must be an array of image URLs. (category=validation)`
**Not:** Aynı job'da CS2 **eldorado** post'u başarılı oldu — sorun yalnızca gameboost image payload'ında.

### Kök Neden: Boş `image_urls: []` + CS2 builder'da fallback yok

`image_urls` burada kuruluyor:
`libs/payload_pipeline/.../marketplaces/gameboost.py:102`
```python
"image_urls": list(listing.media.external_urls) if listing.media.external_urls else [],
```
CS2, bu base builder'ı override etmeden kullanıyor (`.../games/cs2/account/marketplaces/gameboost.py`). Payload **her zaman bir liste** üretir; ama medya upload'ı başarısız olunca veya geçerli path yokken `external_urls=[]` döner (`shared/media.py:67-68,84`) → `image_urls: []` (boş array). Gameboost (Laravel) sunucu tarafı, boş/geçersiz array'i `"must be an array of image URLs"` mesajıyla reddediyor (CS2 template: `assets/gameboost_templates/accounts/counter-strike-2.json`, `image_urls` → `array, required:false`).

**Neden özellikle CS2?** GTAV/COC/CR gibi oyunların gameboost builder'larında **boş array için default fallback** var:
```python
if not payload["image_urls"]:
    payload["image_urls"] = [_DEFAULT_IMAGE_URL]   # gtav/coc/cr gameboost.py
```
**CS2'de bu fallback yok** → grid görseli üretilemez/upload edilemezse boş array'le açıkta kalıyor.

### Refactor ile ilişki (regresyon)
- `f3f6fa2` kullanıcı görsel-seçimini GTA-only'den **tüm oyunlara** genelleştirdi (`stock_start.html` artık her oyun için `selected_image_preset_id` gönderiyor; orchestrator bunu `MEDIA_OVERRIDE_PATH` olarak geçiriyor — `orchestrator.py:461-472`). **Ancak `CS2MediaStrategy` bu override'ı yok sayıyor** — yalnızca GTAV (ve güncellenen Rust) strateji honor ediyor (`games/cs2/account/media/strategy.py`). Yani CS2 kullanıcı görseli seçse bile grid üretimine düşüyor; o da upload edilemezse `image_urls` boş kalıyor.
- `78c531d` `StockResolver`'da non-lzt kaynaktan LZT fallback'i zorluyor (`resolvers/stock.py`) → CS2 grid'ini besleyen ham veri değişebiliyor, bu da grid render/upload başarısızlığını (boş `image_urls`) tetikleyebiliyor.

Satır 102 Nisan'dan beri değişmedi; ama `f3f6fa2` image işleyişini CS2 gibi **fallback'siz** oyunlara genişleterek boş-array hatasını CS2 için ulaşılabilir hale getirdi.

### İlgili dosyalar
- `libs/payload_pipeline/.../marketplaces/gameboost.py:102` — `image_urls` (fallback yok)
- `libs/payload_pipeline/.../games/cs2/account/marketplaces/gameboost.py` — CS2 builder (override yok)
- `libs/payload_pipeline/.../games/cs2/account/media/strategy.py:33,49` — override'ı yok sayar, başarısızlıkta `[]`
- `libs/payload_pipeline/.../shared/media.py:67-68,84,88` — boş `external_urls` durumları

### Önerilen düzeltme yönü (uygulanmadı)
CS2 gameboost builder'ına GTAV/COC/CR gibi boş-array fallback'i (default görsel) ekle; ve/veya `CS2MediaStrategy`'nin `MEDIA_OVERRIDE_PATH`'i honor etmesini sağla.

---

## 4) Eldorado — Eksik Zorunlu Attribute'lar

Eldorado payload'ları `payload_pipeline` library'sinde, her oyunun `games/<game>/account/marketplaces/eldorado.py` builder'ında kuruluyor. Attribute'lar `build_base_payload`'a verilen `attributes` dict'i ile taşınıyor; `attributes` boşsa **hiç `offerAttributes` gönderilmiyor** (`libs/payload_pipeline/.../marketplaces/eldorado.py:152-157`) → Eldorado "Required attribute X not set" döner.

### 4a) Clash of Clans — `clash-of-clans-current-rank not set` (Job #82)
**Kök neden:** `games/coc/account/marketplaces/eldorado.py:13-26` `build_base_payload`'a **hiç `attributes` vermiyor** → sıfır offerAttribute. Bu eksik veri değil: `CocResolvedAccount` (trophies, town_hall_level, heroes...) doludur (`coc/.../resolver.py:80-111`); rank türetilebilir ama builder'da mapping yok. `clash-of-clans-current-rank` key'i kod tabanında hiç geçmiyor (yalnızca Eldorado'nun sunucu-tarafı zorunlu attribute'u).
**Tip:** Builder eksikliği (attribute mapping yok).

### 4b) Roblox — `roblox-account-type not set` (Job #86)
**Kök neden:** Roblox yeni eklendi (`28f0726`); `games/roblox/account/marketplaces/eldorado.py:13-26` de aynı boş stub — `attributes` yok. Kaynak veri mevcut (`RobloxResolvedAccount`: robux, inventory_price, register_date, verified... — `roblox/.../resolver.py:25-52`); `roblox-account-type` hiç türetilip gönderilmiyor.
**Tip:** Yeni oyun — Eldorado builder attribute resolver'ı eksik.

### 4c) Genshin Impact — `Trade Environment combination invalid` (Job #87)
**Kök neden:** `games/gi/account/marketplaces/eldorado.py:22-24` trade-environment'ı `get_external_id(variant_context, "region", account.region.lower())` ile çözüyor, eşleşme yoksa geçersiz `"1-999"`'a düşüyor.
- `account.region` = LZT ham `mihoyo_region` ("Europe"/"America"/"Asia") → lower → `"europe"`.
- `variant_context` key'i `source_key or slug` (`apps/posting/services/variant_context.py:117`). Genshin seed'inde (`migrations/0010_game_variant_system.py:222-243`) tüm region'ların `source_key`'i **boş** → key'ler slug'a düşüyor: `na`/`eu`/`asia`/`tw`.
- `"europe"` ↔ `eu` eşleşmiyor (case-insensitive fallback da `"eu" != "europe"`) → `None` → `"1-999"` → Eldorado reddi.

**Karşıt kanıt:** Valorant çalışıyor çünkü region seed'lerinde `source_key` dolu (`"EU"`,`"NA"`) ve builder `region.upper()` kullanıyor (`games/val/.../eldorado.py:60-62`). Genshin `.lower()` + boş `source_key` → hiçbir şey hizalanmıyor.
**Tip:** Region→trade-env eşleme hatası (seed `source_key` boş + lower/upper uyumsuzluğu).

### İlgili dosyalar
- `libs/payload_pipeline/.../marketplaces/eldorado.py:92-160` (offerAttributes emission: 152-157)
- `libs/payload_pipeline/.../games/coc/account/marketplaces/eldorado.py` (attributes yok)
- `libs/payload_pipeline/.../games/roblox/account/marketplaces/eldorado.py` (attributes yok)
- `libs/payload_pipeline/.../games/gi/account/marketplaces/eldorado.py:22-24` (region→trade-env + `"1-999"` fallback)
- `apps/posting/services/variant_context.py:117` + `migrations/0010_game_variant_system.py:222-243` (Genshin boş source_key)

### Önerilen düzeltme yönü (uygulanmadı)
- CoC ve Roblox için Eldorado builder'ında zorunlu attribute resolver/mapping'i ekle (`current-rank`, `account-type`).
- Genshin için: ya `GENSHIN_REGIONS` seed'ine doğru `source_key` (ham `mihoyo_region` değerleri) gir, ya da builder'daki region lookup'ını ham değerle eşleşecek şekilde düzelt.

---

## 5) Genshin Impact (gameboost) — `minimum price ... 0.99 €` (Job #87)

**Hata:** `API error: The minimum price for the selected rank is 0.99 € (and 1 more error) (category=validation)`
**Kök neden:** Gameboost, seçilen rank için min fiyat (0.99 €) dayatıyor; gönderilen fiyat bunun altında (artı "1 more error" — muhtemelen ek bir zorunlu alan). Bu öncelikle **fiyatlandırma/config** kaynaklı (Start Post ekranındaki pricing snapshot), salt kod hatası değil.
**Aksiyon:** Genshin için min fiyat eşiğini/pricing snapshot'ını gözden geçir. (Kod tarafında min-fiyat clamp eklenmesi düşünülebilir ama mevcut veri/config sorunu.)

---

## 6) Resolve Source Guard'ları — `requires the 'manual'/'lzt' source` (Beklenen)

**Job'lar:** #88 Rust (`yae_krut` — her iki item), #90 Roblox (`roblox11` — her iki item)
**Stage:** `resolve` (pazara hiç gidilmeden), `error_category=pipeline_error`

**Guard konumları:**
- Rust: `libs/payload_pipeline/.../games/rust/account/resolver.py:22` → `Rust requires the 'manual' source.`
- Roblox: `libs/payload_pipeline/.../games/roblox/account/resolver.py:21` → `Roblox requires the 'lzt' source.`

**Tetik koşulu:** `PipelineRequest.source(name)` (`core/contracts.py:273-275`) `sources` dict'inde ilgili key yoksa `{}` döner → adapter `parse()` `None` → guard fırlar. Post'un `source_key`'i `orchestrator.py:402-420`'de `OwnedProduct.source_account.provider`'dan (ör. `lzt`) veya `raw_data['source']=='manual'`'dan belirlenir; tek key'li `sources` dict'i kurulur.

**Neden `roblox11` patladı ama `pjyggee` (Job #86) geçti?**
İkisi de Roblox → ikisi de `'lzt'` ister. Fark, login'in OwnedProduct kaynağında:
- `pjyggee`: LZT-kaynaklı çözüldü → `sources={'lzt': raw}` → geçti.
- `roblox11`: LZT-kaynaklı **değil** ve enrich edilmedi. `_needs_lzt_enrich` (`orchestrator.py:332-333`) `raw_data['source']=='manual'` girişlerini atlar; `28f0726`'daki LZT-promote yolu (`resolvers/stock.py:177-199`) yalnızca job'da çalışan bir LZT `source_account` varsa devreye girer.

**Verdict:** Bu guard'lar **tasarım gereği input validation** — regresyon değil. Rust manuel kaynak, Roblox LZT-kaynaklı ürün gerektiriyor; bu login'ler doğru kaynakla gelmemiş.
**Aksiyon:** Veri/config — `yae_krut` için manuel giriş, `roblox11` için LZT-destekli ürün (veya job'a çalışan LZT `source_account`) sağla. Opsiyonel: guard mesajını kullanıcıya daha açık bir "bu login için kaynak eksik" uyarısına çevir.

---

## 7) Gameboost — `already listed with this login` (Beklenen)

**Job:** #80 — R6 Siege, `neasufh980@hotmail.com` → `EzSmurfMart`
**Hata:** `You've already listed an account with this login. (category=validation)`
**Kök neden:** Aynı login Gameboost'ta zaten listelenmiş — duplicate. Test sırasında aynı hesabın tekrar post edilmesi beklenen sonuç. Kod hatası değil.
**Aksiyon:** Yok (veya UI'da "zaten listelenmiş" durumunu skip/uyarı olarak ele al).

---

## Sonuç — Düzeltme Öncelik Listesi

| Öncelik | Konu | Tip | Etki |
|---|---|---|---|
| 🔴 P1 | **PlayerAuctions token refresh açığı** (#2) | Tasarım açığı | Restart sonrası **tüm** PA post'ları ölü |
| 🔴 P1 | **CS2 gameboost `image_urls` fallback** (#3) | Regresyon | Görseli upload olamayan oyunlar gameboost'a post edilemiyor |
| 🟠 P2 | **Eldorado CoC/Roblox attribute mapping** (#4a/4b) | Eksik builder | İlgili oyunlar Eldorado'ya post edilemiyor |
| 🟠 P2 | **Genshin Eldorado region→trade-env** (#4c) | Eşleme hatası | Genshin Eldorado post'u ölü |
| 🟡 P3 | Genshin gameboost min fiyat (#5) | Veri/config | Tekil |
| ⚪ — | Rust/Roblox resolve guard (#6), Gameboost duplicate (#7), Proxy (#1) | Beklenen/Altyapı | Kod düzeltmesi gerekmez |

**Genel değerlendirme:** Asıl gerçek kod regresyonları **#2 (PA auth)** ve **#3 (CS2 image_urls)**. **#4** grubu yeni eklenen/eksik kalan Eldorado attribute mapping'leri. Geri kalanlar (proxy, duplicate, source guard, min fiyat) ya altyapı ya da beklenen veri/config durumları.

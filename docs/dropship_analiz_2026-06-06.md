# Dropship Sistemi — Detaylı Analiz Raporu

**Tarih:** 2026-06-06 (analiz anı ~15:30 CEST / 13:30 UTC)
**Kapsam:** `backend/apps/posting/services/dropship/*`, `libs/apis_sdk` (LZT/PA client), `PostingLog` DB (12.340+ dropship kaydı), `django.log`, systemd journal (`ecom-dropship`).
**Not:** Bu rapor yalnızca analizdir — hiçbir kod değiştirilmedi.

---

## 1. Sistem Sağlık Özeti (anlık)

| Bileşen | Durum | Not |
|---|---|---|
| Scheduler | ✅ Sağlıklı | heartbeat ~2sn önce, pid 1763711 |
| Poster #1 (GandalfRivendell → Store4Gamers/Fortnite) | ⚠️ Çalışıyor ama döngü bitmiyor | `running=True`, ama `poster_last_cycle_at = 06-05 15:45` → bir tam döngü ~22 saattir tamamlanmadı |
| Poster #2 | 🔴 Sistemce kalıcı kapatıldı | "Maximum of 200 active offers" — bkz. Bulgu 2 |
| Poster #3 | ⚪ Kullanıcı tercihiyle kapalı | last_cycle 05-14 |
| Cleaner #1 (acct=1) | ✅ Aktif | son 1 saatte aktif temizlik yapıyor; ama düzenli 1h cooldown'a giriyor — bkz. Bulgu 1 |

**Stok tablosu (DropshipProduct):**
- `listed` = **2.255**
- `deleted` = **5.985**  ← *awaiting re-post + kaynakta silinmiş, ikisi birbirine karışık*
- `sold` = **891**

**Son 7 gün hareket:** cleaner 559 fiyat-değişimi + 498 "gone" delist = **1.057 delist**; poster yalnızca 45 SUCCESS log + 68 ERROR. → **Re-post backlog'u büyüyor** (Bulgu 7).

---

## 2. Bulgular (öncelik sırasıyla)

### 🔴 Bulgu 1 — LZT bakım modu yanlış sınıflandırılıyor → cleaner her gün ~1 saat boşta

**Kanıt (sayısal):** Son 14 günde **28 adet 1-saatlik cooldown** olayı (≈28 saat cleaner offline):
```
05-23 … 06-03: günde 1   (LZT günlük bakım penceresi ~01:18 UTC)
06-04: 7   06-05: 9   06-06: 1   (LZT platform instabilitesi günleri)
```
06-04 sonrası dönemde journal'da **32 kez** "Engineering works. The market is temporarily unavailable." mesajı.

**Örnek log:**
```
cleaner  Source check server error for item 224371012: Engineering works. The market is temporarily unavailable.
backoff  Server error, backing off 4.0s (attempt 1/5) … (5/5)
cleaner  Cleaner temporary cooldown: 5x consecutive server errors (5xx) — waiting 3600s then resuming
```

**Kök neden:** `libs/apis_sdk/apis_sdk/clients/marketplaces/lzt/client.py:571` bakım modunu yalnızca şu string'lerle tanıyor:
```python
if "technical works" in _lower or "технические работы" in _lower:
    details["maintenance"] = True
```
LZT artık **"Engineering works. The market is temporarily unavailable."** döndürüyor → eşleşmiyor → `details["maintenance"]` set edilmiyor → `backoff.py:classify_api_error` (satır 93-96) maintenance dalına giremiyor → hata `server` (5xx) sayılıyor → `cleaner.py:217 on_server_error()` → 5 ardışık → **1 saat cooldown**.

Oysa doğru yol `cleaner.py:197` maintenance dalı: yalnızca `MAINTENANCE_WAIT = 120s` bekleyip döngüyü tekrar deniyor.

**Etki:** Cleaner her gün en az 1 saat (kötü günlerde 7-9 saat) tamamen duruyor. Bu sürede satılan/fiyatı değişen ürünler temizlenmiyor → **bayat ilanlar canlı kalıyor** → satılmış ürünü satma / yanlış fiyattan satış riski.

**Çözüm yönü:** `lzt/client.py` bakım eşleşmesini genişlet ("engineering works", "temporarily unavailable", "the market is temporarily unavailable"). İsteğe bağlı olarak maintenance'ı gerçek `'maintenance'` kategorisine yönlendirip 120sn bekleme davranışına bağla. **En düşük riskli, en yüksek kazançlı düzeltme.**

---

### 🔴 Bulgu 2 — "Maximum of 200 active offers" kalıcı kapatmaya yol açıyor (Poster #2)

**Kanıt:** Poster #2 `disabled_reason`:
```
3x validation errors in 1 hour (400) | last: … messages: ['Maximum of 200 active offers is allowed.']
```
`poster_last_cycle_at = 2026-05-06` → bir aydır kapalı, kendiliğinden geri dönmedi.

**Kök neden:** "200 aktif teklif limiti" bir **kapasite** durumu, bozuk-payload değil. Ama `backoff.py:117-125` bunu HTTP 400 → `validation` sınıflıyor → `poster.py:327 on_validation_error()` → 1 saatte 3 kez → **kalıcı PauseRequired**. Eldorado tarafında `_MaxOfferError` ön-kontrolü var; PA 200-cap için yok.

**Etki:** Mağaza dolunca dropship sessizce duruyor; ürünler satılıp yer açılınca otomatik devam etmiyor, elle resume gerekiyor. (Hafızadaki "prepare_item kapalı offer kontrolü" bilinen sorunuyla örtüşüyor.)

**Çözüm yönü:** "maximum of N active offers" desenini yumuşak kapasite durumu olarak ayır (skip + backoff, kalıcı pause değil) veya PA için ön-kontrol ekle.

---

### 🟠 Bulgu 3 — Persistent MySQL bağlantıları bayatlıyor ("Lost connection to MySQL server")

**Kanıt (son ~2 gün):** journal'da **18× "Dropbox token refresh failed"**, **16× "Lost connection to MySQL server during query"** (hata 2013) ve daha önce "client was disconnected … because of inactivity (wait_timeout)" (4031).

**Kök neden:** `backend/config/settings/base.py:115` `CONN_MAX_AGE: 600` (persistent connection) **ama `CONN_HEALTH_CHECKS` yok** (Django 4.1+). Uzun ömürlü dropship worker thread'lerinde 600sn tutulan bağlantı, MySQL `wait_timeout`/idle-kill ile sunucu tarafında kapanabiliyor; sonraki sorgu bayat bağlantıyı kullanınca "Lost connection" patlıyor. Görünür kurban `dropbox_adapter` ama **risk her DB sorgusu için geçerli**.

**Etki:** Sporadik DB hataları; token yenileme ve diğer arka plan işlerinde kesinti.

**Çözüm yönü:** `'CONN_HEALTH_CHECKS': True` ekle (Django bağlantıyı her döngü başında doğrulayıp şeffafça yeniden kursun). Alternatif: uzun thread döngülerinde `close_old_connections()` çağır.

---

### 🟠 Bulgu 4 — Eldorado Cognito "Password attempts exceeded" → 541 görsel-yükleme/post hatası (tarihsel)

**Kanıt:** 565 poster ERROR'unun **541'i**:
```
Pipeline build failed [build]: Image upload failed for fortnite_*.png …
Eldorado Cognito authentication failed: (NotAuthorizedException) … Password attempts exceeded
```
Yoğunluk 18-30 Mayıs (19 May: 373). **30 Mayıs'tan sonra durmuş** — muhtemelen `111a556`/`dd94a87` (Imgur downloader + Eldorado image upload error handling refactor) commit'leriyle çözüldü.

**Kalıcı zayıflık:** Pipeline-build hataları `poster.py:332` generic `except` ile "Post failed" loglanıp tracker'a SAYILMIYOR → kalıcı kapatmıyor (iyi) ama **devre kesici de yok** → her döngü boşuna tekrar deniyor.

**Çözüm yönü:** Çözüldüğünü doğrula. Ardından pipeline-build için tekrarlayan başarısızlıkta circuit-breaker düşün.

---

### 🟠 Bulgu 5 — ImageShack yükleme hataları (SSL/timeout)

**Kanıt (son 2 gün):** journal'da **8× "ImageShack upload failed"**:
```
ImageShack upload failed … ('Connection aborted.', TimeoutError('write operation timed out'))
ImageShack upload failed … SSLError(SSLEOFError(8, 'EOF occurred in violation of protocol'))
```

**Etki:** Medya fallback adaptörlerinden biri kararsız; fatal değil (başka adaptör devrede) ama gecikme/gürültü ekliyor, post süresini uzatıyor (Bulgu 7'yi besliyor).

**Çözüm yönü:** ImageShack'in fallback önceliğini düşür veya retry/timeout politikasını gözden geçir.

---

### 🟡 Bulgu 6 — PA Token Service (localhost:8976) kapalı → PA sync + delist çalışmıyor

**Kanıt (django.log):**
```
Token service unreachable: … localhost:8976/authenticate: Connection refused
playerauctions operation exhausted retries → SyncRun … failed
```

**Etki:** PA order/offer sync sürekli patlıyor; ayrıca cleaner'ın PA mağazalarında `delete_listing` yapmasını engeller (`cleaner.py:391`). **Kod hatası değil**, çalışmayan yan servis.

**Çözüm yönü:** PA token servisini ayağa kaldır / systemd ile kalıcılaştır.

---

### 🟡 Bulgu 7 — Re-post backlog'u / churn dengesizliği

**Kanıt:** `deleted=5.985` vs `listed=2.255`. Son 7 günde **559 fiyat-değişimi + 498 gone**; poster bir tam döngüyü ~22 saatte bile bitiremiyor (her re-post tam görsel yeniden üretimi gerektiriyor, ~2 dk/öğe).

**Kök neden(ler):**
1. Fiyat değişiminde **tam delist + tam yeniden post** yapılıyor (`cleaner.py:_handle_price_change` → `poster` re-post). Pahalı.
2. `%3` fiyat toleransı `~2.255` listede haftada `559` değişim tetikliyor (~%25/hafta churn) — gerçek olabilir, ama eşik gözden geçirilmeli.
3. `DELETED` durumu "fiyat değişti, yeniden post et" ile "kaynakta silindi, post etme"yi **aynı statüde birleştiriyor** → backlog şişiyor, izlenmesi zor.
4. Cleaner cooldown'ları (Bulgu 1) backlog'u büyütüyor.

**Çözüm yönü:** (a) Fiyat değişiminde tam re-post yerine fiyat-güncelleme (edit) yolu mümkün mü incele; (b) `DELETED`'i "re-post bekliyor" vs "kalıcı silinmiş" olarak ayır; (c) tolerans eşiğini değerlendir.

---

### 🟡 Bulgu 8 — Cleaner ürün-başına `refresh_from_db` (performans)

`cleaner.py:108` her LISTED ürün için ayrı bir `SELECT enabled` atıyor. ~2.255 (geçmişte ~8.300) ürünle her döngü binlerce gereksiz sorgu. İşlevsel hata değil; N item'da bir veya zaman-bazlı kontrol yeterli.

---

## 3. Önceliklendirme

| # | Sorun | Etki | Aciliyet | Zorluk |
|---|---|---|---|---|
| 1 | LZT bakım yanlış sınıflama | Cleaner günde 1-9h offline, bayat ilan | 🔴 Yüksek | Kolay |
| 2 | 200-offer → kalıcı kapatma | Poster sessiz duruş, geri dönmüyor | 🔴 Yüksek | Orta |
| 3 | MySQL bayat bağlantı | Sporadik DB hataları | 🟠 Orta | Kolay |
| 6 | PA token servisi kapalı | PA sync + delist çalışmıyor | 🟡 Orta (ops) | Kolay |
| 4 | Cognito image upload | Tarihsel, muhtemelen çözüldü | 🟠 Doğrula | — |
| 5 | ImageShack hataları | Gecikme/gürültü | 🟡 Düşük | Kolay |
| 7 | Re-post backlog/churn | Verimsizlik, gecikmeli temizlik | 🟡 Orta | Yüksek |
| 8 | Cleaner DB yükü | Performans | 🟡 Düşük | Kolay |

**Önerilen başlangıç sırası:** Bulgu 1 → Bulgu 3 → Bulgu 2 (en yüksek kazanç / en düşük risk).

---

## 4. Önemli Dosya Referansları

- `backend/apps/posting/services/dropship/cleaner.py` — cleaner döngüsü, maintenance/server dalları (satır 192-248), `refresh_from_db` (108)
- `backend/apps/posting/services/dropship/backoff.py` — `classify_api_error` (76-127), eşikler (28-39)
- `backend/apps/posting/services/dropship/poster.py` — hata yönetimi (307-345)
- `libs/apis_sdk/apis_sdk/clients/marketplaces/lzt/client.py:571` — bakım string eşleşmesi (Bulgu 1 kök neden)
- `backend/config/settings/base.py:115` — `CONN_MAX_AGE`, `CONN_HEALTH_CHECKS` eksik (Bulgu 3)

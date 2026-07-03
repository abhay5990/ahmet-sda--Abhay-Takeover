# R6 (Rainbow Six) Tracker — Server Kurulum & Gereklilikler

Rainbow Six hesaplarını Google Sheet'ten ekleyip listelerken, ilan verisini
**R6Locker tracker** (`r6skins.locker`) besliyor. Bu site **Cloudflare Turnstile**
arkasında olduğu için tracker çağrısı düz bir HTTP isteği değil — gerçek bir
tarayıcının challenge'ı çözüp `cf_clearance` cookie'si üretmesi gerekiyor.

> **Durum (2026-07-03): ÇALIŞIYOR.** nodriver + Turnstile tıklaması + residential
> sticky proxy ile `cf_clearance` üretiliyor, sonra aynı sticky IP üzerinden
> curl_cffi ile veri çekiliyor. Detay aşağıda.

Bu doküman, **yeni bir sunucuya kurarken** gerekli tüm sistem bağımlılıklarını,
mimariyi ve tuzakları özetler.

> İlgili kod:
> `libs/apis_sdk/.../auth/cf_cookie_provider.py` (nodriver solve, subprocess, bütçe),
> `libs/apis_sdk/.../infrastructure/proxy/sticky.py` (StickyResidentialProxy + rotate),
> `libs/apis_sdk/.../infrastructure/proxy/relay.py` (LocalProxyRelay — Chrome için auth enjekte),
> `libs/apis_sdk/.../trackers/r6locker/facade.py` (escalation ladder + IP pinning),
> `backend/apps/posting/services/shared/tracker_fetcher.py` (`_get_r6locker_facade`, DB proxy),
> `backend/apps/posting/api/manual.py` (`_create_r6_sheet_job`),
> `backend/apps/posting/services/stock/orchestrator.py` (prepare_once).

---

## Uçtan uca zincir (nereye ne besliyor)

1. **Sheet okuma** — `fetch_r6_accounts`: satırları okur, `TrackerLink`'ten UUID
   çıkarır. API'ye gitmez.
2. **Job oluşturma** — `_create_r6_sheet_job`: `OwnedProduct.raw_data` içine
   `source='tracker_sheet'`, `uplay_id=<uuid>` yazar. Tracker fetch ertelenir.
3. **Job çalışınca** — orchestrator `fetch_tracker_data('rainbow-six-siege', raw_data)`
   çağırır → `R6LockerFacade.get_account_data(uuid)`:
   - `CfCookieProvider.get_cookies(solve_url=.../profile/<uuid>)` → cache boşsa/eskiyse
     **ayrı bir subprocess'te** nodriver ile Chrome açar (Xvfb `:99`), residential
     relay üzerinden gider, **Turnstile "Verify you are human" kutucuğuna tıklar**,
     `cf_clearance` + `connect.sid` + user-agent + `proxy_url` çıkarır.
   - `CurlCffiTransport` (`chrome124` impersonate) **aynı `proxy_url` (sticky IP)** ile
     `GET /accounts/<uuid>` → JSON.
4. Tracker **None** dönerse job item `source_missing` / **"Tracker fetch failed"**
   ile düşer. Tracker verisi zorunlu, fallback yok.

**Önemli kavramlar:**
- `cf_clearance` **çıkış IP'sine** bağlı (JA3'e değil) — bu yüzden tarayıcı ve curl
  **aynı sticky residential IP**'den çıkmalı (`proxy_url` cookie ile birlikte taşınır).
- `cf_clearance` **domain-geneli** — tek cookie seti tüm hesaplara yeter. İlk hesap
  bir solve tetikler, kalanlar cache'ten hızlı curl ile gider (single-flight: eşzamanlı
  istekler tek Chrome paylaşır).
- **Sabit seed profil YOK** — solve, o an işlenen hesabın profili üzerinde yapılır.

---

## Sistem gereklilikleri

| Bağımlılık | Neden | Kurulum |
|-----------|-------|---------|
| **Xvfb (`:99`)** | Cloudflare HeadlessChrome'u bloklar; Chrome'u sanal ekranda (non-headless) çalıştırmak şart | `apt-get install -y xvfb` + `xvfb.service` |
| **Gerçek Google Chrome** | nodriver'ın JS/Turnstile challenge'ı çözmesi için gerçek Chrome binary gerek | aşağıdaki `.deb` yöntemi |
| **nodriver** | Chrome'u CDP'den sürer, Turnstile tıklar (`verify_cf`) | `requirements/base.txt` |
| **opencv-python** | `nodriver.verify_cf()` kutucuğu template-match ile bulur | `requirements/base.txt` |
| **curl-cffi** | cf_clearance ile asıl API isteğini atar (TLS impersonation) | `requirements/base.txt` |
| **Residential proxy (DB)** | Tarayıcı + curl aynı temiz sticky IP'den çıkmalı; datacenter IP CF'i geçemez | DB `Proxy` kaydı (aşağıda) |

### ⚠️ Tuzak: `apt install chromium-browser` KULLANMA

Ubuntu 22.04'te `chromium-browser` apt paketi **snap'e yönlendiren transitional
bir shim** (`Pre-Depends: snapd`). Snap chromium, confinement yüzünden Xvfb altında
düzgün sürülemez. **Gerçek Google Chrome** kur:

```bash
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
apt-get install -y /tmp/chrome.deb
google-chrome --version   # doğrula
```

`deploy/deploy.sh` bunu otomatik yapar (adım 2): Xvfb + Chrome yoksa kurar.

### Residential proxy konfigürasyonu

Tarayıcı **ve** curl aynı sticky residential IP'den çıkmalı (yoksa cf_clearance
IP-uyuşmazlığından 403 alır). Proxy DB'deki `Proxy` tablosundan okunur:

- Varsayılan: `Proxy` id=1 (DataImpulse residential, `gw.dataimpulse.com:823`).
- Değiştirmek için `settings.R6_RESIDENTIAL_PROXY_ID`.
- Sticky IP: `StickyResidentialProxy` username'e `;sessid.<id>` ekler; `rotate()`
  yeni `sessid` → yeni çıkış IP (ban/429/bütçe için).
- **Chrome** şifreli proxy'yi kabul etmez → `LocalProxyRelay` (127.0.0.1, ephemeral
  port) araya girip `Proxy-Authorization`'ı enjekte eder. **curl_cffi** relay'e
  gerek duymaz (user:pass proxy'yi doğrudan kullanır).

Proxy kaydı yoksa `_get_r6locker_facade` `None` döner → R6 tracker devre dışı.

---

## Doğrulama (kurulumdan sonra)

Sistem bağımlılıkları:

```bash
command -v Xvfb            # /usr/bin/Xvfb
command -v google-chrome   # /usr/bin/google-chrome
systemctl is-active xvfb    # active  (DISPLAY=:99)
venv/bin/python -c "import nodriver, cv2, curl_cffi; print('py deps OK')"
```

Uçtan uca (gerçek CF solve + curl reuse) — posting giriş noktasından:

```bash
DISPLAY=:99 venv/bin/python tests/manual/test_r6locker_e2e.py
# beklenen: 1. hesap ~15sn (solve dahil), 2-3. hesap ~0.4sn (cache reuse), 3/3 ✅
```

`cf_clearance` üretilemiyorsa (title "Just a moment..."ta takılı) → genelde
residential proxy yok/kötü demektir (aşağıya bak).

---

## ✅ Çözülen engel: datacenter IP (2026-07-03)

**Eskiden** (2026-07-02, DrissionPage + proxy'siz): Chrome + Xvfb kurulu olsa bile
Cloudflare **"Just a moment..." döngüsünde takılıyordu**, çünkü sunucunun datacenter
IP'si flag'liydi ve challenge pasif beklemeyle geçilmiyordu.

**Çözüm** (nodriver + residential + Turnstile):
- **Residential sticky proxy** — tarayıcı DataImpulse IP'sinden çıkıyor (relay ile),
  curl da **aynı** IP'den (`;sessid.<id>`). cf_clearance IP-bağlı olduğu için ikisi
  aynı olmalı.
- **Turnstile tıklaması** — pasif bekleme yetmiyor; `nodriver.verify_cf()` kutucuğu
  bulup tıklıyor → cf_clearance ~5-15sn'de üretiliyor.
- **curl reuse** — cf_clearance domain-geneli; tek solve, çok hesap (~0.3sn/hesap).
- **Rotasyon** — ~50 istek (jitter'lı) VEYA süre dolunca ya da 403/429'da yeni IP
  (`rotate()` + re-solve). Escalation ladder facade'de:
  `403 → aynı IP re-solve → yine 403 → rotate` · `429 → backoff → ısrarcıysa rotate`.

Not: solve güvenilirliği IP kalitesine göre değişir; provider **3 deneme** yapar ve
başarısız denemeler arası IP rotate eder.

---

## Mimari özeti (kod)

| Katman | Sorumluluk |
|--------|-----------|
| `StickyResidentialProxy` | Tek residential upstream + rotate edilebilir `sessid` (çıkış IP kontrolü) |
| `LocalProxyRelay` | Chrome için authsuz localhost proxy → upstream'e `Proxy-Authorization` enjekte |
| `CfCookieProvider` | nodriver solve (ayrı subprocess), single-flight, bütçe/rotasyon, cf_clearance cache |
| `R6LockerFacade` | cookie+proxy_url pinning, 403/429 escalation ladder, curl'e delege |
| `CurlCffiTransport` | `chrome124` impersonate + sticky proxy ile asıl istek |

**Neden subprocess?** nodriver aynı process'te tekrarlı `uc.start()`'ta takılıyor;
her solve ayrı `spawn` subprocess'te → uzun-ömürlü Django/Celery process nodriver
event-loop'una hiç dokunmuyor. (Bu yüzden solve'u tetikleyen giriş noktaları
`if __name__ == "__main__"` guard'ı ile korunmalı.)

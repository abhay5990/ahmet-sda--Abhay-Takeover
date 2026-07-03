# Deploy & Service Runbook

Bu sunucudaki servislerin **tek script ile** nasıl kurulup çalıştığını ve
bir şey çalışmazsa **adım adım nasıl teşhis edileceğini** anlatır.

Tüm servis tanımları versiyon-kontrollü: [deploy/systemd/](../deploy/systemd/).
Tek komutla kurulum/güncelleme: `bash deploy/deploy.sh` (root olarak).

---

## 1. Servis haritası

```
xvfb.service            → Sanal ekran :99 (headless Chrome / R6 Cloudflare için)
  ├─ ecom-gunicorn      → Web (Django/Gunicorn) — DISPLAY=:99
  ├─ ecom-dropship      → Dropship poster + cleaner — DISPLAY=:99
  └─ ecom-scheduler     → Sync scheduler (APScheduler) — DISPLAY=:99
nginx                   → Reverse proxy → gunicorn 127.0.0.1:8000
```

`ecom-*` servisleri R6Locker tracker'ı çözerken headless Chrome'u `:99`
ekranında çalıştırır (bkz. [r6-tracker-server-setup.md](r6-tracker-server-setup.md)).
Bu yüzden hepsi `xvfb.service`'e `Wants=` + `After=` ile bağlı ve `DISPLAY=:99` alır.

> **Tarihsel not:** Eskiden `adspower.service` + `pa-adspower.service` (yerel
> Node.js PA-token) vardı. PA token uzak microservice'e (`31.57.156.36:8976`)
> taşınınca bunlar atıl kaldı ve 2026-07-03'te kaldırıldı. `xvfb.service` ise
> R6 için tutuldu ve repo'ya alındı. AdsPower artık hiçbir yerde kullanılmıyor.

---

## 2. Tek-script deploy

```bash
cd /home/ahmet/e-commerce-management-system
bash deploy/deploy.sh
```

deploy.sh sırasıyla: env kontrol → git pull → **Xvfb + Google Chrome kur** (yoksa)
→ pip install → migrate + collectstatic → nginx config → **systemd unit'leri
render+kur** (`${PROJECT_DIR}`, `${GUNICORN_WORKERS}` envsubst) → enable → restart
→ durum tablosu.

Beklenen çıktı: sonda tüm servisler `✓`. Biri `✗` ise aşağıdaki teşhise geç.

---

## 3. Hızlı sağlık kontrolü

```bash
# Tüm servisler tek bakışta
systemctl is-active xvfb ecom-gunicorn ecom-dropship ecom-scheduler nginx

# Ekran :99 ayakta mı + Chrome bağlanabiliyor mu
pgrep -af 'Xvfb :99'
DISPLAY=:99 google-chrome --headless=new --no-sandbox --dump-dom about:blank >/dev/null && echo "chrome :99 OK"

# Chrome kurulu mu (R6 için şart)
google-chrome --version
```

---

## 4. Adım adım teşhis (bir şey çalışmıyorsa)

### A. Bir ecom servisi ayağa kalkmıyor
```bash
systemctl status ecom-gunicorn --no-pager
journalctl -u ecom-gunicorn -n 50 --no-pager
```
- `ModuleNotFound / ImportError` → `venv/bin/pip install -r requirements/prod.txt`
- `.env` hatası → `.env` var mı, `PROJECT_DIR`/`DOMAIN` set mi
- `address already in use` → 8000 portunu tutan eski süreç: `ss -lntp | grep 8000`

### B. Xvfb / DISPLAY sorunu
```bash
systemctl status xvfb --no-pager
journalctl -u xvfb -n 30 --no-pager
DISPLAY=:99 xdpyinfo | head -3      # display cevap veriyor mu (xdpyinfo yoksa: apt install x11-utils)
```
- Xvfb down → `systemctl restart xvfb`
- Servis DISPLAY görmüyor → `systemctl show ecom-dropship -p Environment` `DISPLAY=:99` içermeli;
  yoksa unit güncel değil → `bash deploy/deploy.sh` (veya `daemon-reload` + restart)

### C. R6 tracker Cloudflare geçemiyor
Bkz. [r6-tracker-server-setup.md](r6-tracker-server-setup.md) → "Bilinen engel".
Sırayla kontrol:
1. Chrome kurulu mu? (`google-chrome --version`) — yoksa deploy.sh kurar.
2. Ekran :99 ayakta mı? (yukarıdaki B)
3. Residential proxy (DB Proxy id=1, DataImpulse) **sticky** mi? Sticky formatı:
   username'e `;sessid.<id>` eklemek IP'yi sabitler.
4. "Just a moment" 45sn+ takılıyorsa → datacenter IP / bot-tespiti. Çözüm:
   nodriver + sticky residential + Turnstile tıklama (kanıtlandı) VEYA captcha servisi.
5. cf_clearance alınıp curl'e taşınınca 403 → JA3 uyuşmazlığı; API'yi **aynı tarayıcı
   içinde** `fetch()` ile çek.

### D. PlayerAuctions sync "Token refresh failed: HTTP 500"
Bu, **uzak** PA token microservice'i (`31.57.156.36:8976`) kaynaklı — bu sunucunun
sorunu değil. O servisin ayakta olduğunu doğrula; `token_service_url`
[playerauctions_factory.py](../libs/apis_sdk/apis_sdk/factories/playerauctions_factory.py).

---

## 5. Faydalı komutlar

```bash
# Canlı log takibi
journalctl -u ecom-dropship -f

# Tek servisi elle başlat/durdur/yeniden başlat
systemctl restart ecom-scheduler

# Bir R6 solve'u canlı izlemek için :99'a VNC bağla (opsiyonel debug)
#   x11vnc -display :99 -localhost -nopw   → ssh tüneli ile bağlan

# Unit dosyası değişince (deploy.sh dışında elle)
systemctl daemon-reload && systemctl restart <svc>
```

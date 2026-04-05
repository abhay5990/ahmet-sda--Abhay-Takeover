# Management Commands

## Hizli Referans

| Komut | Amac | Ornek |
|---|---|---|
| `sync_orders` | Marketplace siparislerini sync et | `python manage.py sync_orders eldorado-store4gamers` |
| `sync_offers` | Marketplace offer/listing'leri sync et | `python manage.py sync_offers gameboost-store4gamers` |
| `import_lzt_orders` | LZT JSON'dan bulk import | `python manage.py import_lzt_orders lzt-main data.json` |
| `reprocess_raw_payloads` | Failed/pending payload'lari yeniden parse et | `python manage.py reprocess_raw_payloads eldorado-store4gamers` |
| `reset_parsed_data` | Domain verisini silip sifirdan parse et | `python manage.py reset_parsed_data --all --resource owned_products` |
| `seed_games` | Oyun + kategori + platform mapping seed et | `python manage.py seed_games` |

---

## Sync App

### sync_orders

Marketplace siparislerini API uzerinden senkronize eder.

```bash
# Incremental sync (varsayilan — sadece yeni siparisler)
python manage.py sync_orders <account-slug>

# Full backfill (tum gecmis)
python manage.py sync_orders <account-slug> --mode backfill

# Sadece raw ingest (parse yok)
python manage.py sync_orders <account-slug> --phase ingest

# Sadece parse (API cagrisi yok)
python manage.py sync_orders <account-slug> --phase process

# Dry-run (baglanti + ayar kontrolu)
python manage.py sync_orders <account-slug> --dry-run
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `account` | positional | — | IntegrationAccount slug |
| `--mode` | backfill / incremental | incremental | Sync modu |
| `--phase` | full / ingest / process | full | Calisma fazi |
| `--resource` | orders / listings / owned_products | orders | Resource type |
| `--dry-run` | flag | — | Dogrulama yapar, sync yapmaz |

Desteklenen provider'lar: `eldorado`, `gameboost`, `playerauctions`

---

### sync_offers

Marketplace offer/listing'lerini API uzerinden senkronize eder.

```bash
# Incremental sync (varsayilan)
python manage.py sync_offers <account-slug>

# Full backfill
python manage.py sync_offers <account-slug> --mode backfill

# Sadece raw ingest
python manage.py sync_offers <account-slug> --phase ingest

# Sadece parse (API cagrisi yok)
python manage.py sync_offers <account-slug> --phase process

# Dry-run
python manage.py sync_offers <account-slug> --dry-run
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `account` | positional | — | IntegrationAccount slug |
| `--mode` | backfill / incremental | incremental | Sync modu |
| `--phase` | full / ingest / process | full | Calisma fazi |
| `--dry-run` | flag | — | Dogrulama yapar, sync yapmaz |

Desteklenen provider'lar: `eldorado`, `gameboost`, `playerauctions`

---

### import_lzt_orders

LZT JSON dosyasindan bulk import (RawPayload + OwnedProduct).

```bash
# Tam import (ingest + parse)
python manage.py import_lzt_orders <account-slug> <json-path>

# Sadece raw ingest
python manage.py import_lzt_orders <account-slug> <json-path> --phase ingest

# Batch size ayarla
python manage.py import_lzt_orders <account-slug> <json-path> --batch-size 1000

# Dry-run (item sayisini goster)
python manage.py import_lzt_orders <account-slug> <json-path> --dry-run
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `account` | positional | — | IntegrationAccount slug |
| `json_path` | positional | — | JSON dosya yolu |
| `--batch-size` | int | 500 | Batch buyuklugu |
| `--phase` | full / ingest | full | full = ingest + parse |
| `--dry-run` | flag | — | Sayim yapar, import yapmaz |

---

### reprocess_raw_payloads

Raw payload'lari API cagirmadan yeniden parse eder. Mapper/model degisikliklerinden sonra kullanilir.

```bash
# Failed olanlari yeniden isle
python manage.py reprocess_raw_payloads <account-slug>

# Parsed dahil hepsini yeniden isle
python manage.py reprocess_raw_payloads <account-slug> --status failed --status parsed

# Farkli resource type
python manage.py reprocess_raw_payloads <account-slug> --resource owned_products

# Limit ile
python manage.py reprocess_raw_payloads <account-slug> --status failed --limit 100

# Dry-run
python manage.py reprocess_raw_payloads <account-slug> --dry-run
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `account` | positional | — | IntegrationAccount slug |
| `--status` | failed / pending / parsed | failed | Hangi durumdakileri isle (birden fazla verilebilir) |
| `--resource` | orders / owned_products | orders | Resource type |
| `--limit` | int | 0 (sinirsiz) | Maks satir sayisi |
| `--dry-run` | flag | — | Sayim goster, isleme yapma |

---

### reset_parsed_data

Domain verilerini silip RawPayload'lari pending'e cevirir. Model/mapper degisikliklerinden sonra temiz reparse icin.

```bash
# Tek account
python manage.py reset_parsed_data <account-slug> --resource owned_products

# Tum account'lar
python manage.py reset_parsed_data --all --resource owned_products

# Sil + yeniden parse
python manage.py reset_parsed_data --all --resource owned_products --reparse

# Dry-run
python manage.py reset_parsed_data --all --resource owned_products --dry-run
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `account` | positional (opsiyonel) | — | IntegrationAccount slug (`--all` ile atlanabilir) |
| `--all` | flag | — | Tum account'lari hedefle |
| `--resource` | owned_products / orders | — (zorunlu) | Resource type |
| `--reparse` | flag | — | Sildikten sonra otomatik reparse |
| `--batch-size` | int | 500 | Reparse batch buyuklugu |
| `--dry-run` | flag | — | Ne olacagini goster |

> **Dikkat:** Bu komut destructive'dir — domain satirlarini siler. Calistirmadan once `--dry-run` ile kontrol edin.

---

## Inventory App

### seed_games

Kategori, oyun ve platform mapping'lerini JSON'dan seed eder.

```bash
# Varsayilan dosyadan seed
python manage.py seed_games

# Farkli dosyadan
python manage.py seed_games --file /path/to/mapping.json
```

| Arguman | Tip | Varsayilan | Aciklama |
|---|---|---|---|
| `--file` | str | `data/game_platform_mapping.json` | Mapping JSON dosyasi |

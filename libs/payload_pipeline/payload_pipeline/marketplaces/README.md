# Marketplace Common Layer

Bu klasor tum marketplace implementasyonlarini toplamak icin degil,
oyunlar arasinda ortaklasan marketplace kodunu tutmak icindir.

## Buraya ne girer

- marketplace base class'lari
- ortak helper'lar
- ortak upload/policy kodu
- birden fazla game slice tarafindan kullanilan marketplace davranisi

## Buraya ne girmez

- tek bir oyuna ozel payload mapping kodu
- `games/<slug>/<kind>/marketplaces/` altinda durmasi gereken builder'lar

## Bugunku durum

Su an burada sadece Eldorado ortak katmani var, cunku:

- ortak base builder var
- ortak image upload davranisi var
- bu davranis birden fazla oyunda tekrar kullaniliyor

Game-specific marketplace builder'lari su path'te kalmali:

```text
payload_pipeline/games/<slug>/<kind>/marketplaces/
```

Ornek:

- `payload_pipeline/games/val/account/marketplaces/eldorado.py`
- `payload_pipeline/games/r6/account/marketplaces/eldorado.py`

Bu dosyalar oyun-spesifik mapping yapar.
Bu klasor ise ortak marketplace altyapisini tasir.

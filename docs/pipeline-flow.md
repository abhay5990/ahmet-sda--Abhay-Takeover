# Payload Pipeline — Tam Veri Akisi

## Genel Gorunum

```
[Django UI / API]
        |
        v
[StockOrchestrator]
        |
        +-- _load_templates()           PostingDefault FK --> template body strings
        +-- _build_resolver()           source account --> StockResolver
        +-- _build_image_fetcher()      LZT credentials --> LztDefaultImageFetcher
        |
        v
[pipeline/adapter.py]
        |
        +-- build_request()             --> PipelineRequest
        +-- _get_pipeline()             --> PayloadPipeline (singleton)
        |
        v
[PayloadPipeline.prepare_once()]
        |
        +--[1] registry lookup          --> GameDefinition
        +--[2] resolver.resolve()       --> ResolvedAccount (dataclass)
        +--[3] validate_resolved()      --> validation pass/fail
        +--[4] media prepare+publish    --> MediaBundle (non-fatal)
        +--[5] composer.compose()       --> ListingDraft
        |
        v
[PreparedListing]  -->  store queues  -->  per-store consumer threads
        |
        v
[PayloadPipeline.build()]
        |
        +-- builder.build_payload()     --> dict (marketplace payload)
        |
        v
[provider.create_listing()]             --> marketplace API call
```

---

## Asama 0 — Giris Noktalari

### 0A — Template Yonetimi (UI)

**Dosya:** `backend/apps/posting/views.py:94` — `content_templates_page()`

| Istek | Endpoint | Amac |
|-------|----------|------|
| GET | `/api/content-templates/?game_id=X` | Template listesi |
| GET | `/api/content-templates/metadata/?game_id=X` | Field palette (field adi, aciklama, sample) |
| POST | `/api/content-templates/create/` | Yeni template olustur |
| POST | `/api/content-templates/<id>/` | Template guncelle |
| DELETE | `/api/content-templates/<id>/` | Template sil |
| POST | `/api/content-templates/preview/` | Sample context ile anlik render |

Frontend: Alpine.js `contentTemplates()` componenti (`content_templates.html`).

### 0B — Stock Posting Baslatma

`POST /api/jobs/` --> `PostingJob` + `PostingJobItem` kayitlari olusturulur, ardindan `StockOrchestrator.execute(job_id)` thread'de tetiklenir.

---

## Asama 1 — Template Yuklemesi

**Dosya:** `backend/apps/posting/services/stock/orchestrator.py:117` — `_load_templates()`

```
PostingDefault.objects.filter(game_id=game_id)
    .select_related('title_template', 'description_template')
```

**Cikti:**

```python
# Her marketplace icin PostingDefault uzerindeki FK'lardan body string'leri cekilir
defaults = {
    "eldorado": <PostingDefault title_template=<ContentTemplate>, desc_template=...>,
    "g2g":      <PostingDefault title_template=None, desc_template=<ContentTemplate>>,
}
```

**Dosya:** `backend/apps/posting/pipeline/templates.py:10` — `load_templates_for_posting()`

| Parametre | Tip | Aciklama |
|-----------|-----|----------|
| `game_id` | `int` | Oyun PK |
| `posting_defaults` | `dict[str, PostingDefault]` | marketplace --> PostingDefault |

**Cikti:**

```python
title_templates = {
    "eldorado": "R6 Account | Lv {level} | {current_rank} | {black_ice_count} BI",
    "g2g":      "R6 Siege | {level} | {peak_rank}",
}
description_templates = {
    "eldorado": "Level: {level}\nRank: {current_rank}\n...",
}
# Hic secili yoksa --> None
```

---

## Asama 2 — PipelineRequest Insasi

**Dosya:** `backend/apps/posting/pipeline/request.py:9` — `build_request()`

| Parametre | Tip | Ornek |
|-----------|-----|-------|
| `game_slug` | `str` | `"r6"`, `"valorant"` |
| `sources` | `dict` | `{"lzt": {...}, "tracker": {...}}` |
| `kind` | `ListingKind` | `STOCK` veya `DROPSHIPPING` |
| `disable_media` | `bool` | `False` |
| `lzt_image_fetcher` | `ImageFetcher \| None` | LZT gorsel indirici |
| `title_templates` | `dict[str, str] \| None` | marketplace --> body |
| `description_templates` | `dict[str, str] \| None` | marketplace --> body |

**Cikti: `PipelineRequest`**

```python
PipelineRequest(
    game="r6",
    category=ListingCategory.ACCOUNT,
    kind=ListingKind.STOCK,
    sources={
        "lzt":     { ...raw LZT data... },
        "tracker": { ...tracker data... },
    },
    context={
        "disable_media":         False,
        "lzt_image_fetcher":     <LztDefaultImageFetcher>,
        "title_templates":       {"eldorado": "...", "g2g": "..."},
        "description_templates": {"eldorado": "..."},
    }
)
```

> `context` anahtarlari `ContextKey[T]` tipinde typed string'lerdir (`core/context_keys.py`).
> `TITLE_TEMPLATES`, `DESCRIPTION_TEMPLATES`, `DISABLE_MEDIA` vb.

---

## Asama 3 — Pipeline Adapter

**Dosya:** `backend/apps/posting/pipeline/adapter.py:93` — `prepare()`

1. `build_request(...)` cagirir --> `PipelineRequest`
2. `_get_pipeline().prepare_once(request)` cagirir --> `PrepareResult`

**`_get_pipeline()`** singleton `PayloadPipeline` instance doner. Ilk cagirida:

1. `build_default_registry()` --> tum oyun slice'larini kayit eder
2. `_build_media_publisher()` --> Dropbox + ImageShack credential okur --> `HostedMediaPublisher` veya `NullMediaPublisher`

---

## Asama 4 — `PayloadPipeline.prepare_once()`

**Dosya:** `libs/payload_pipeline/payload_pipeline/core/pipeline.py:56`

4 sirali adim. Her biri hata olursa `PrepareResult(success=False, error_stage=...)` doner:

### 4.1 — Registry Lookup

```python
definition = self.registry.get_game("r6", "account")
# definition icerir: .resolver, .composer, .media_strategy, .get_builder(mp)
```

- Hata --> `error_stage="registry"`

### 4.2 — Resolve

```python
subject: R6ResolvedAccount = definition.resolver.resolve(request)
```

Resolver ne yapar:
- `request.source("lzt")` --> raw LZT dict'i parse eder
- `request.source("tracker")` --> tracker verisini merge eder
- Sonuc: game-specific `ResolvedAccount` dataclass

```python
R6ResolvedAccount(
    item_id="12345",
    price=45.0,
    level=120,
    current_rank="Diamond",
    peak_rank="Champions",
    black_ice_count=12,
    operators=["Ash", "Jager", ...],
    inventory=R6InventoryBreakdown(...),
    credentials=CredentialBundle(login="user@x.com", password="..."),
    ...
)
```

- Hata --> `error_stage="resolve"`

### 4.3 — Validate

```python
validate_resolved(subject, game="r6", kind=ListingKind.STOCK)
```

Price, credentials vb. minimum kontroller.

- Hata --> `error_stage="validate"`

### 4.4 — Media (non-fatal)

```python
local_paths = definition.media_strategy.prepare(subject, request)
# LZT'den gorsel indir, cache'le, disk'e yaz

media = self.media_publisher.publish(local_paths, request=request)
# Dropbox'a yukle --> ImageShack album olustur --> URL al
```

**Cikti:** `MediaBundle(local_paths=[...], external_urls=[...], album_url="https://...")`

Basarisiz olursa `warnings` listesine eklenir, akis kesilmez.

### 4.5 — Compose

```python
listing: ListingDraft = definition.composer.compose(subject, request, media)
```

Detayi --> Asama 5

**Asama 4 Nihai Ciktisi: `PrepareResult`**

```python
PrepareResult(
    success=True,
    prepared=PreparedListing(
        subject=<R6ResolvedAccount>,
        listing=<ListingDraft>,
        media=<MediaBundle>,
        game="r6",
        category="account",
        warnings=[],
    )
)
```

---

## Asama 5 — Compose (Icerik Uretimi)

**Dosya:** `libs/.../games/r6/account/content/composer.py:34` — `R6Composer.compose()`

### 5.1 — Legacy Draft Olusturulur

Her zaman ilk adim olarak legacy title/description uretilir. Bu, template olmayan marketplace'ler icin fallback gorevi gorur.

```python
title          = self.title_generator.generate(account, site="default")
g2g_title      = self.title_generator.generate(account, site="g2g")
eldorado_title = self.title_generator.generate(account, site="eldorado")
description    = self.description_generator.generate(account, media, site="default")
player_desc    = self.description_generator.generate(account, media, site="player")

draft = ListingDraft(
    default=ListingContent(title=title, description=description, tags=[...]),
    media=media,
    marketplace_overrides={
        "g2g":      MarketplaceListingOverride(title=g2g_title),
        "eldorado": MarketplaceListingOverride(title=eldorado_title),
        "player":   MarketplaceListingOverride(description=player_desc),
    }
)
```

### 5.2 — Template Overlay (varsa)

```python
title_templates = ctx.TITLE_TEMPLATES.get(request)      # dict[str,str] | None
desc_templates  = ctx.DESCRIPTION_TEMPLATES.get(request) # dict[str,str] | None

if title_templates or desc_templates:
    apply_template_overrides(
        draft,
        build_r6_context(account, request, media),
        title_templates=title_templates,
        description_templates=desc_templates,
    )
```

> `draft.default` hic degismez — legacy icerik her zaman fallback olarak kalir.
> Template sonuclari sadece `draft.marketplace_overrides` icine yazilir.

### 5.2a — Context Dict Olusturma

**Dosya:** `libs/.../games/r6/account/content/template_content.py:17` — `build_r6_context()`

Account dataclass field'lari + nested inventory + computed properties tek seviye dict'e duzlestirilir:

```python
{
    # Dataclass field'lari
    "level": 120,
    "current_rank": "Diamond",
    "peak_rank": "Champions",
    "black_ice_count": 12,
    "operator_count": 45,
    "operators": ["Ash", "Jager", ...],
    "renown": 45000,
    ...

    # Inventory (nested --> flat)
    "glacier_count": 2,
    "glacier_items": ["Glacier MP5", ...],
    "black_ice_items": ["Black Ice R4-C", ...],
    "seasonal_count": 8,
    "elite_count": 4,
    ...

    # Computed properties
    "ranked_ready": True,
    "available_platforms": ["PC", "PlayStation"],
    "linkable_platforms": ["PC"],
    "ownership_text": "This account has the game...",
    "platform_type_text": "Uplay Account | Has The Game",

    # Media & request
    "album_url": "https://imageshack.com/a/...",
    "is_stock": True,
}
```

### 5.2b — Template Rendering

**Dosya:** `libs/.../content_templates/compose.py:131` — `apply_template_overrides()`

```
apply_template_overrides(draft, context, title_templates, description_templates)
    |
    +-- compose_with_templates(context, title_templates, description_templates)
    |       |
    |       +-- for each marketplace in title_templates:
    |       |       SimpleTemplateRenderer.render(body, context) --> rendered title
    |       |
    |       +-- for each marketplace in description_templates:
    |               SimpleTemplateRenderer.render(body, context) --> rendered desc
    |
    +-- Rendered sonuclari draft.marketplace_overrides'a yaz
```

**Dosya:** `libs/.../content_templates/renderer.py:32` — `SimpleTemplateRenderer`

```python
# Input:
body    = "R6 Account | Lv {level} | {current_rank} | {black_ice_count} BI"
context = {"level": 120, "current_rank": "Diamond", "black_ice_count": 12, ...}

# Regex: \{([a-zA-Z_][a-zA-Z0-9_]*)\}
# Her match icin context'ten deger alinir, format edilir

# Output:
"R6 Account | Lv 120 | Diamond | 12 BI"
```

Degerlerin format kurallari (`_format_value`):
- `None` --> `""`
- `bool` --> `"Yes"` / `"No"`
- `list` --> `", ".join(items)`
- Diger --> `str(value)`

### 5.2c — Sonuc ListingDraft

```python
ListingDraft(
    default=ListingContent(
        title="[legacy title]",           # <-- degismez, fallback
        description="[legacy desc]",      # <-- degismez, fallback
        tags=["r6", "rainbow-six", "account"],
    ),
    media=<MediaBundle>,
    marketplace_overrides={
        "eldorado": MarketplaceListingOverride(
            title="R6 Account | Lv 120 | Diamond | 12 BI",    # template
            description="Level: 120\nRank: Diamond\n...",      # template
        ),
        "g2g": MarketplaceListingOverride(
            title="R6 Siege | 120 | Champions",                 # template
        ),
        "player": MarketplaceListingOverride(
            description="[legacy player desc]",                 # legacy
        ),
    }
)
```

---

## Asama 6 — Producer --> Consumer Fan-out

**Dosya:** `backend/apps/posting/services/stock/orchestrator.py:247` — `_produce()`

```
for each login:
    |
    +-- _resolve_items()       OwnedProduct'i coz (yoksa fallback)
    |
    +-- _prepare_once()        adapter.prepare() cagir
    |       |
    |       +-- sources = {"lzt": owned_product.raw_data, "tracker": ...}
    |       +-- adapter.prepare(game_slug, sources, kind, templates)
    |       +-- Basarili --> {"ok": True, "data": {"prepared": PreparedListing}}
    |       +-- Basarisiz --> {"ok": False, "stage": "...", "error": "..."}
    |
    +-- Her store queue'ya push:
            store_queues[store_id].put((item, prepared_data))

Tum login'ler bittikten sonra:
    for q in store_queues.values():
        q.put(SENTINEL)    # consumer thread'e "bitti" sinyali
```

---

## Asama 7 — `PayloadPipeline.build()` (Store Thread)

**Dosya:** `backend/apps/posting/pipeline/adapter.py:130` — `build()`

| Parametre | Tip | Aciklama |
|-----------|-----|----------|
| `prepared` | `PreparedListing` | Asama 4 ciktisi |
| `marketplace` | `str` | `"eldorado"`, `"g2g"`, vb. |
| `pricing_defaults` | duck-typed | multiplier_low/mid/high, min_price, forced_ending |
| `store` | `IntegrationAccount` | G2G seller_id vb. icin |
| `kind` | `ListingKind` | STOCK veya DROPSHIPPING |
| `sub_platform` | `str` | `"PC"`, `"PSN"`, vb. |

**Dosya:** `libs/.../core/pipeline.py:133` — `PayloadPipeline.build()`

```python
# 1. Registry'den marketplace builder'i al
builder = definition.get_builder("eldorado")   # EldoradoPayloadBuilder

# 2. Payload dict uret
payload: dict = builder.build_payload(prepared.subject, prepared.listing, build_ctx)
```

Builder icinde `listing.content_for(marketplace)` cagrilir:

```python
# content_for("eldorado") mantiği:
override = listing.marketplace_overrides.get("eldorado")
if override:
    title = override.title if override.title is not None else default.title
    desc  = override.description if override.description is not None else default.description
else:
    title = default.title
    desc  = default.description
```

**Cikti: `PipelineResult`**

```python
PipelineResult(
    success=True,
    subject=<R6ResolvedAccount>,
    listing=<ListingDraft>,
    payload={
        "title": "R6 Account | Lv 120 | Diamond | 12 BI",
        "description": "Level: 120\nRank: Diamond\n...",
        "price": 90.99,
        "category_id": 42,
        ...  # marketplace-specific fields
    },
    marketplace="eldorado",
)
```

---

## Asama 8 — Marketplace API Call

**Dosya:** `backend/apps/posting/services/stock/orchestrator.py:427` — `_post_with_backoff()`

```
provider = registry.get_provider("eldorado")
facade   = registry.get_or_build_client("eldorado", credential, proxy_pool)

result = provider.create_listing(facade, {"payload": payload})

if 429 (rate limited):
    exponential backoff: 1s --> 2s --> 4s --> 8s --> 16s (max 30s)
    max 5 retry, sonra give up

if OK:
    PostingJobItem.status = SUCCESS
    Listing kaydedilir

if FAIL:
    PostingJobItem.status = FAILED
    error_message kaydedilir
```

---

## Template Rendering Ozel Akisi (ozet)

```
[ContentTemplate]  (DB)
    body = "R6 | Lv {level} | {current_rank}"
    game = R6, marketplace = eldorado, type = title
                |
                v
[PostingDefault]  (DB)
    game = R6, marketplace = eldorado
    title_template_id --> ContentTemplate.id
                |
                v
[load_templates_for_posting()]
    title_templates["eldorado"] = "R6 | Lv {level} | {current_rank}"
                |
                v
[build_request()]
    PipelineRequest.context["title_templates"] = {"eldorado": "R6 | Lv {level}..."}
                |
                v
[R6Composer.compose()]
    ctx.TITLE_TEMPLATES.get(request)  -->  {"eldorado": "R6 | Lv {level}..."}
                |
                v
[apply_template_overrides(draft, context, title_templates)]
                |
    +-----------+
    |
    v
[build_r6_context(account, request, media)]
    {"level": 120, "current_rank": "Diamond", ...}     <-- flat dict
                |
                v
[compose_with_templates(context, title_templates)]
                |
                v
[SimpleTemplateRenderer.render(body, context)]
    "R6 | Lv {level} | {current_rank}"
        + {"level": 120, "current_rank": "Diamond"}
        = "R6 | Lv 120 | Diamond"
                |
                v
[draft.marketplace_overrides["eldorado"].title]
    = "R6 | Lv 120 | Diamond"
                |
                v
[builder.build_payload()]
    listing.content_for("eldorado").title
        = "R6 | Lv 120 | Diamond"
                |
                v
[payload["title"]]
    = "R6 | Lv 120 | Diamond"
                |
                v
[provider.create_listing()]
    --> marketplace API
```

---

## Veri Tipleri Referansi

| Tip | Dosya | Aciklama |
|-----|-------|----------|
| `PipelineRequest` | `core/contracts.py:216` | Prepare fazina giris: game, sources, context |
| `PrepareResult` | `core/contracts.py:250` | prepare_once ciktisi: success, prepared, error |
| `PreparedListing` | `core/contracts.py:238` | subject + listing + media paketi |
| `ListingDraft` | `core/contracts.py:186` | default icerik + marketplace overrides |
| `ListingContent` | `core/contracts.py:168` | title, description, tags |
| `MarketplaceListingOverride` | `core/contracts.py:177` | per-marketplace title/desc override |
| `MediaBundle` | `core/contracts.py:155` | local_paths, external_urls, album_url |
| `BuildContext` | `core/contracts.py:32` | Build fazina giris: marketplace, pricing, config |
| `PipelineResult` | `core/contracts.py:275` | build ciktisi: payload dict |
| `ResolvedAccountBase` | `core/contracts.py:120` | Tum oyun modellerinin base class'i |
| `FieldMeta` | `core/contracts.py:16` | Template editor metadata: description, sample, source |
| `CredentialBundle` | `core/contracts.py:61` | login, password, email bilgileri |
| `ContextKey[T]` | `core/context_keys.py:19` | Typed string key for PipelineRequest.context |
| `TemplateComposeResult` | `content_templates/compose.py:38` | Render sonucu: per-marketplace titles/descs |
| `ContentTemplate` | `posting/models.py:226` | Django model: game, marketplace, type, name, body |
| `PostingDefault` | `posting/models.py:124` | Django model: game, marketplace, pricing, template FK'lari |

---

## Hata Yonetimi Ozeti

| Asama | Hata | Sonuc |
|-------|------|-------|
| Registry lookup | Oyun/kategori bulunamaz | `error_stage="registry"` |
| Resolve | LZT data parse hatasi | `error_stage="resolve"` |
| Validate | Price/credential eksik | `error_stage="validate"` |
| Media prepare | Gorsel indirme hatasi | Warning (akis devam eder) |
| Media publish | Upload hatasi | Warning (akis devam eder) |
| Compose | Template render hatasi | `error_stage="compose"` |
| Build | Payload olusturma hatasi | `error_stage="build"` |
| API POST | 429 rate limit | Exponential backoff, max 5 retry |
| API POST | Diger hata | `PostingJobItem.status = FAILED` |

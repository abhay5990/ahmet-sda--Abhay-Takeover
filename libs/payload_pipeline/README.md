# Payload Pipeline

Game listing payload builder. Takes prepared source data, resolves it into a
unified model, generates media, composes listing content, and builds
marketplace-ready payloads.

## API

Two methods:

```python
from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.core import context_keys as ctx

pipeline = PayloadPipeline(registry=build_default_registry())

# 1. Prepare once — resolve + media + compose (shared across all stores)
request = PipelineRequest(
    game="valorant",
    listing_kind="account",
    mode="stock",
    sources={"lzt": lzt_data},
    context={ctx.LZT_CLIENT: lzt_client},
)
prepared = pipeline.prepare_once(request)

# 2. Build per store — each store gets its own BuildContext
payload = pipeline.build(prepared, BuildContext(
    marketplace="eldorado",
    eldorado_client=eldorado_client,
    pricing_rules=pricing_rules,
))
```

### Multi-store

Same `prepared`, different contexts:

```python
prepared = pipeline.prepare_once(request)

for store in eldorado_stores:
    payload = pipeline.build(prepared, BuildContext(
        marketplace="eldorado",
        eldorado_client=store.client,
        pricing_rules=store.rules,
        current_subplatform=store.subplatform,
    ))

for store in g2g_stores:
    payload = pipeline.build(prepared, BuildContext(
        marketplace="g2g",
        g2g_seller_id=store.seller_id,
        pricing_rules=store.rules,
    ))
```

## Context separation

| Where | What goes here | When used |
|-------|---------------|-----------|
| `request.context` | Shared/source: `LZT_CLIENT`, `MEDIA_OUTPUT_DIR`, `DISABLE_MEDIA` | `prepare_once` |
| `BuildContext` | Per-store: `eldorado_client`, `pricing_rules`, `g2g_seller_id`, `current_subplatform` | `build` |

## Structure

```
payload_pipeline/
  core/              # contracts, pipeline, registry, exceptions
  shared/            # image processing, uploads, LZT image fetcher
  marketplaces/      # shared marketplace builders (Eldorado base, media upload)
  pricing/           # PricingRule and calculate_price
  docs/              # reference docs (source fields, pipeline flow)
  games/
    <slug>/
      account/
        sources/     # source adapters (LZT, tracker)
        models.py    # resolved dataclass
        resolver.py  # source -> resolved model
        content/     # composer, title/description generators
        media/       # media strategy (image download/generation)
        marketplaces/# per-game marketplace builders
```

## Supported games

13 games: `rainbow-six-siege`, `counter-strike-2`, `valorant`, `brawl-stars`,
`clash-of-clans`, `clash-royale`, `fortnite`, `genshin-impact`, `league-of-legends`,
`roblox`, `steam`, `ubisoft-connect`, `grand-theft-auto-5`.

## Media

Image fetching uses `LZT_CLIENT` (authenticated API) with plain HTTP fallback.
Pass the client in `request.context`:

```python
request = PipelineRequest(
    ...,
    context={ctx.LZT_CLIENT: lzt_client},
)
```

Eldorado image upload happens per-store during `build`, using `BuildContext.eldorado_client`.

For Dropbox/ImageShack upload, pass a `HostedMediaPublisher` to the pipeline:

```python
from payload_pipeline.shared.media import HostedMediaPublisher

publisher = HostedMediaPublisher(
    dropbox_uploader=DropboxUploadProcessor(),
    imageshack_processor=ImageShackAlbumProcessor(),
)
pipeline = PayloadPipeline(registry=registry, media_publisher=publisher)
```

## Output paths

Media output directories resolved by `shared/paths.py`:

1. `request.context[ctx.MEDIA_OUTPUT_DIR]`
2. `PAYLOAD_PIPELINE_OUTPUT_DIR` env var
3. CWD-relative `output/payload_pipeline/...`

## Naming conventions

| Context | Format | Example |
|---------|--------|---------|
| Directory names | Short code (legacy) | `r6/`, `val/`, `gi/` |
| Class names | Full game name, PascalCase | `ValorantComposer` |
| Registry key | Canonical slug from game_mapp.json | `valorant`, `rainbow-six-siege` |

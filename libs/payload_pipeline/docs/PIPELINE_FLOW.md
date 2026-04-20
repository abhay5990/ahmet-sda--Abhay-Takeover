# Payload Pipeline Flow

This file is a living schema for how data moves through `payload_pipeline`.
Update it when stage boundaries, contracts, or responsibilities change.

## Core Flow

```text
Prepared source payloads
  -> parse
  -> resolve
  -> media
  -> compose
  -> build
  -> marketplace payload
```

## Stage Map

| Stage | Primary input | Primary output | Responsibility |
| --- | --- | --- | --- |
| input | `PipelineRequest` | same request | Carry prepared source payloads and explicit context into the pipeline |
| parse | raw source dicts from `request.sources` | typed source models | Normalize each source independently without merge rules |
| resolve | typed source models + request mode/context | one resolved subject model | Apply precedence, fallback, validation, and derived-field rules |
| media | resolved subject + request | local media paths | Prepare local images before optional publication |
| compose | resolved subject + media + request | `ListingDraft` | Produce listing title/description/tags and attach media bundle |
| build | resolved subject + listing draft + request | marketplace payload dict | Build marketplace-specific payload and do marketplace-side uploads if needed |

## Current R6 Flow

### 1. Input

Input:
- `PipelineRequest`
- `sources["lzt"]`: prepared LZT payload dict
- `sources["tracker"]`: prepared tracker payload dict
- `context`: explicit runtime dependencies such as `eldorado_client`, output dir, or overrides

Output:
- unchanged request object

Notes:
- No remote source fetching happens inside this module.
- The request is the only inbound container for raw prepared payloads.

### 2. Parse

Input:
- raw `lzt` dict
- raw `tracker` dict

Output:
- `R6LztSource`
- `R6TrackerSource`

Owned by:
- `games/r6/account/sources/lzt.py`
- `games/r6/account/sources/tracker.py`

Rules:
- Parse source-local fields only.
- Do not merge sources here.
- Do not compose text or upload media here.

### 3. Resolve

Input:
- `R6LztSource | None`
- `R6TrackerSource | None`
- `PipelineRequest.mode`
- selected context overrides

Output:
- `R6ResolvedAccount`

Owned by:
- `games/r6/account/resolver.py`

Rules:
- Validate required source presence.
- Apply source precedence and fallback rules.
- Compute derived values such as effective credentials, level, rank, counts, platforms, tracker URL, and builder-facing flags.
- This stage should become the canonical truth for the rest of the slice.

### 4. Media

Current input:
- `R6ResolvedAccount`
- `PipelineRequest`

Current internal dependency:
- `R6LztSourceAdapter`
- `R6TrackerSourceAdapter`
- `R6LztImageGenerator`
- `R6TrackerImageGenerator`

Current output:
- local image file paths

Owned by:
- `games/r6/account/media/strategy.py`

Current reality:
- R6 media now runs from typed source models instead of raw snapshots.
- Mixed-source flow is explicit: tracker drives skin collages, LZT drives operator collage.

### 5. Compose

Current input:
- `R6ResolvedAccount`
- `MediaBundle`
- `PipelineRequest`

Current internal dependency:
- `R6ResolvedTitleGenerator`
- `R6ResolvedDescriptionGenerator`

Current output:
- `ListingDraft`

Owned by:
- `games/r6/account/content/composer.py`

Current reality:
- The composer now reads only the resolved account plus prepared media.
- Target-specific title length remains an explicit composer concern through listing overrides.

### 6. Build

Input:
- `R6ResolvedAccount`
- `ListingDraft`
- `PipelineRequest`

Output:
- marketplace payload dict, e.g. Eldorado payload

Owned by:
- `games/r6/account/marketplaces/eldorado.py`
- `marketplaces/eldorado.py`

Rules:
- Keep marketplace-specific payload quirks here.
- Do marketplace-side image upload here if a marketplace client is explicitly provided in request context.

## Current R6 Data Flow in One Line

```text
request(raw lzt/tracker)
  -> source adapters
  -> R6ResolvedAccount
  -> media strategy
  -> composer
  -> marketplace builder
  -> payload
```

## Current Boundary Status

Today, `resolve` is the canonical truth boundary for R6 listing output.

Why:
- `media` consumes typed source models instead of raw dict snapshots.
- `compose` consumes only `R6ResolvedAccount` plus `MediaBundle`.

Effect:
- Listing text, media, and marketplace payloads now read from the same resolved domain view.

## Marketplace Clean Flow

Marketplace direction:

```text
request(raw prepared sources)
  -> source adapters
  -> resolved subject
  -> media generator driven by resolved data
  -> composer driven by resolved data + media
  -> marketplace builder
  -> payload
```

In the clean version:
- `resolve` is the single canonical truth stage.
- `media` does not need raw source payloads.
- `compose` does not need raw source payloads.
- Legacy support, if still needed, sits behind one explicit adapter boundary.

## Important Constraint for the Clean Version

Moving image/title/description generation to resolved-data-driven inputs is correct only if the resolved model, or a dedicated typed generator input model, contains every field required to reproduce the intended behavior.

That means:
- if title logic needs ownership state, premium-series flags, or charm-derived rank, those must already exist after `resolve`
- if image logic needs operator names and curated skin assets, those must already exist after `resolve`
- if description logic needs tracker URL, skin summaries, and special category counts, those must already exist after `resolve`

## Recommended Long-Term Shape

Preferred direction:

```text
raw request
  -> parse
  -> resolve
  -> `R6ResolvedAccount`
  -> optional thin legacy adapter fed by typed data
  -> media/compose
  -> build
```

This keeps:
- raw payload knowledge at the edge
- merge logic in the resolver
- content/media generation dependent on resolved domain truth
- marketplace behavior isolated in builders

## Update Rule

Whenever one of these changes, update this file:
- stage responsibilities
- canonical input/output types
- legacy boundaries
- which stage owns a derived field
- which stage is allowed to read raw source payloads

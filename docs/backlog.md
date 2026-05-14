# Technical Backlog

Refactoring and improvement items to address when time permits.

## Code Quality

- [ ] **Game model: `has_pipeline_support` field** — Currently `SUPPORTED_GAME_SLUGS` is imported from the pipeline lib enum and filtered in views (`slug__in=SUPPORTED_GAME_SLUGS`). This creates coupling between view layer and pipeline internals. Better approach: add a `has_pipeline_support` boolean field to `Game` model, filter with `Game.objects.filter(has_pipeline_support=True)`. Optionally add a custom manager method `Game.objects.with_pipeline_support()` for DRY.

- [ ] **Centralize game queryset helpers** — `Game.objects.filter(is_active=True, slug__in=SUPPORTED_GAME_SLUGS)` is repeated in 3+ views (stock_start, content_templates, content_template_editor). Extract to a `GameQuerySet.supported()` manager method.

## Template Engine

- [ ] **Phase 3: Title Separator Assembly** — `postprocess.py` with `assemble_title_segments()`, integration in `compose.py`
- [ ] **Phase 4: Marketplace Length Validation** — Validate at compose time per marketplace limits
- [ ] **Phase 2 edge cases** — Additional edge case tests per implementation plan

## UI/UX

- [ ] **Marketplace-specific game support** — Some games may be supported on one marketplace but not another. Consider a `GameMarketplace` through-table or JSON config field.

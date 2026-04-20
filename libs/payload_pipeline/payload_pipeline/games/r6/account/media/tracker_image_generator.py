"""Tracker-driven image generation for R6."""

from __future__ import annotations

from dataclasses import dataclass, field

from .image_renderer import R6ImageRenderEntry, R6ImageRenderer, _DEFAULT_R6_OUTPUT_DIR
from ..source_normalization import R6WeaponSkin
from ..sources.tracker import R6TrackerSource


@dataclass(slots=True)
class R6TrackerImageInput:
    """Minimum typed tracker data required to render local listing media."""

    product_id: str
    weapon_skins: list[R6WeaponSkin] = field(default_factory=list)

    @classmethod
    def from_source(
        cls,
        source: R6TrackerSource,
        *,
        product_id: str | None = None,
    ) -> "R6TrackerImageInput":
        resolved_product_id = product_id or source.user_id or source.masked_id or source.username
        return cls(
            product_id=str(resolved_product_id).strip() or "tracker",
            weapon_skins=list(source.weapon_skins),
        )


class R6TrackerImageGenerator(R6ImageRenderer):
    """Render tracker-based R6 skin collages without raw source dicts."""

    def generate_account_images(
        self,
        inp: R6TrackerImageInput,
        output_folder: str = _DEFAULT_R6_OUTPUT_DIR,
    ) -> list[str]:
        return self.generate_skin_images(inp, output_folder=output_folder)

    def generate_skin_images(
        self,
        inp: R6TrackerImageInput,
        *,
        output_folder: str = _DEFAULT_R6_OUTPUT_DIR,
    ) -> list[str]:
        return self.render_skin_entries(
            self._build_skin_entries(inp.weapon_skins),
            product_id=inp.product_id,
            output_folder=output_folder,
        )

    def _build_skin_entries(
        self,
        weapon_skins: list[R6WeaponSkin],
    ) -> list[R6ImageRenderEntry]:
        skins_by_name = self._load_skins_by_name()
        entries: list[R6ImageRenderEntry] = []
        seen: set[str] = set()

        for skin in weapon_skins:
            normalized_name = self._normalize_name(skin.name)
            cache_token = skin.source_id or normalized_name.replace(" ", "_")
            if not cache_token:
                continue

            cache_key = f"skin:{cache_token}"
            if cache_key in seen:
                continue

            urls: list[str] = []
            fallback_skin = skins_by_name.get(normalized_name)
            if fallback_skin is not None:
                urls.extend(fallback_skin.image_urls)

            if skin.image_url:
                urls.append(skin.image_url)
            if skin.source_id:
                urls.append(self._build_tracker_asset_cdn_url(skin.source_id))

            deduped_urls = list(dict.fromkeys(url for url in urls if url))
            if not deduped_urls:
                continue

            seen.add(cache_key)
            entries.append(
                R6ImageRenderEntry(
                    cache_key=cache_key,
                    title=skin.name,
                    image_urls=deduped_urls,
                )
            )

        return entries

    def _build_tracker_asset_cdn_url(self, asset_id: str) -> str:
        return f"https://cdn.r6skins.locker/assets/images/{asset_id}.webp"

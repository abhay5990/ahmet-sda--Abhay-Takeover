"""LZT-driven image generation for R6."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .image_renderer import R6ImageRenderEntry, R6ImageRenderer, _DEFAULT_R6_OUTPUT_DIR
from ..source_normalization import R6WeaponSkin


if TYPE_CHECKING:
    from ..sources.lzt import R6LztSource


@dataclass(slots=True)
class R6LztImageInput:
    """Minimum typed LZT data required to render local listing media."""

    product_id: str
    weapon_skins: list[R6WeaponSkin] = field(default_factory=list)
    operator_names: list[str] = field(default_factory=list)

    @classmethod
    def from_source(
        cls,
        source: R6LztSource,
        *,
        product_id: str | None = None,
    ) -> "R6LztImageInput":
        resolved_product_id = product_id or source.item_id or source.uplay_id or "unknown"
        return cls(
            product_id=str(resolved_product_id).strip() or "unknown",
            weapon_skins=list(source.weapon_skins),
            operator_names=list(source.operators),
        )


class R6LztImageGenerator(R6ImageRenderer):
    """Render LZT-based R6 local media without raw source dicts."""

    def generate_account_images(
        self,
        inp: R6LztImageInput,
        output_folder: str = _DEFAULT_R6_OUTPUT_DIR,
    ) -> list[str]:
        created = self.generate_skin_images(inp, output_folder=output_folder)
        operator_path = self.generate_operator_image(inp, output_folder=output_folder)
        if operator_path:
            created.append(operator_path)
        return created

    def generate_skin_images(
        self,
        inp: R6LztImageInput,
        *,
        output_folder: str = _DEFAULT_R6_OUTPUT_DIR,
    ) -> list[str]:
        return self.render_skin_entries(
            self._build_skin_entries(inp.weapon_skins),
            product_id=inp.product_id,
            output_folder=output_folder,
        )

    def generate_operator_image(
        self,
        inp: R6LztImageInput,
        *,
        output_folder: str = _DEFAULT_R6_OUTPUT_DIR,
    ) -> str | None:
        return self.render_operator_entries(
            self._build_operator_entries(inp.operator_names),
            product_id=inp.product_id,
            output_folder=output_folder,
        )

    def _build_skin_entries(self, weapon_skins: list[R6WeaponSkin]) -> list[R6ImageRenderEntry]:
        catalog_by_id = self._load_skins_by_id()
        catalog_by_name = self._load_skins_by_name()
        entries: list[R6ImageRenderEntry] = []
        seen: set[str] = set()

        for skin in weapon_skins:
            skin_id = str(skin.source_id or "").strip()
            skin_name = str(skin.name or "").strip()
            if not skin_id:
                skin_id = skin_name
            if not skin_id:
                continue

            entry = catalog_by_id.get(skin_id)
            if entry is None:
                entry = catalog_by_name.get(self._normalize_name(skin_name or skin_id))
            if entry is None or entry.cache_key in seen:
                continue

            seen.add(entry.cache_key)
            entries.append(
                R6ImageRenderEntry(
                    cache_key=entry.cache_key,
                    title=entry.title,
                    image_urls=list(entry.image_urls),
                )
            )

        return entries

    def _build_operator_entries(self, operator_names: list[str]) -> list[R6ImageRenderEntry]:
        catalog = self._load_operators_by_name()
        entries: list[R6ImageRenderEntry] = []
        seen: set[str] = set()

        for raw_name in operator_names:
            name = str(raw_name).strip()
            if not name:
                continue

            entry = catalog.get(self._normalize_name(name))
            if entry is None or entry.cache_key in seen:
                continue

            seen.add(entry.cache_key)
            entries.append(
                R6ImageRenderEntry(
                    cache_key=entry.cache_key,
                    title=entry.title,
                    image_urls=list(entry.image_urls),
                )
            )

        return entries

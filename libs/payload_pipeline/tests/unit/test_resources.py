"""Tests for resource path resolution and cache/media output directories."""

from __future__ import annotations

from pathlib import Path


def test_valorant_catalog_resources_dir_is_file_relative() -> None:
    from payload_pipeline.games.val.account.catalog import _RESOURCES_DIR

    assert _RESOURCES_DIR.is_absolute()
    assert (_RESOURCES_DIR / "dataAgents.json").exists()
    assert (_RESOURCES_DIR / "dataSkins.json").exists()
    assert (_RESOURCES_DIR / "dataBuddies.json").exists()


def test_valorant_catalog_loads_from_any_cwd() -> None:
    """Catalog loading works regardless of CWD because paths are __file__-relative."""
    from payload_pipeline.games.val.account.catalog import (
        ValorantCatalog,
        _RESOURCES_DIR,
        _load_mapping,
    )

    catalog = ValorantCatalog(
        agents_by_id=_load_mapping(str(_RESOURCES_DIR / "dataAgents.json")),
        skins_by_id=_load_mapping(str(_RESOURCES_DIR / "dataSkins.json")),
        buddies_by_id=_load_mapping(str(_RESOURCES_DIR / "dataBuddies.json")),
    )
    # At minimum, we should have some loaded data
    assert len(catalog.agents_by_id) > 0 or len(catalog.skins_by_id) > 0


def test_r6_image_renderer_defaults_are_file_relative() -> None:
    from payload_pipeline.games.r6.account.media.image_renderer import (
        _SLICE_RESOURCES_DIR,
        _SHARED_RESOURCES_DIR,
        _DEFAULT_CACHE_BASE,
    )

    resources_dir = Path(_SLICE_RESOURCES_DIR)
    shared_dir = Path(_SHARED_RESOURCES_DIR)

    assert resources_dir.is_absolute()
    assert shared_dir.is_absolute()
    assert (resources_dir / "RainbowSkins.json").exists()
    assert (resources_dir / "RainbowOperators.json").exists()
    assert (shared_dir / "cmss10.ttf").exists()

    # Cache dir should point under output/, not under assets/
    assert "output" in _DEFAULT_CACHE_BASE
    assert "assets" not in _DEFAULT_CACHE_BASE


def test_r6_skin_lookup_uses_slice_local_resources() -> None:
    from payload_pipeline.games.r6.account.skin_lookup import _SKINS_JSON

    assert _SKINS_JSON.is_absolute()
    assert _SKINS_JSON.exists()


def test_r6_skin_lookup_count_black_ice_works() -> None:
    from payload_pipeline.games.r6.account.skin_lookup import count_black_ice

    # With empty list
    assert count_black_ice([]) == 0
    # With non-existent IDs
    assert count_black_ice(["nonexistent_999"]) == 0


def test_r6_skin_lookup_resolve_skin_names_works() -> None:
    from payload_pipeline.games.r6.account.skin_lookup import resolve_skin_names

    assert resolve_skin_names([]) == []


def test_r6_skin_lookup_resolve_skin_name_map_works() -> None:
    from payload_pipeline.games.r6.account.skin_lookup import resolve_skin_name_map

    assert resolve_skin_name_map([]) == {}


def test_r6_image_renderer_cache_writes_to_output_dir() -> None:
    """Verify the default cache directory is under output/, not source tree."""
    from payload_pipeline.games.r6.account.media.image_renderer import _DEFAULT_CACHE_BASE

    cache_path = Path(_DEFAULT_CACHE_BASE)
    # Should not be under assets/
    assert "assets" not in str(cache_path)
    # Should contain output/payload_pipeline pattern
    parts = cache_path.parts
    assert "output" in parts
    assert "payload_pipeline" in parts
    assert "cache" in parts
    assert "r6" in parts


def test_r6_default_output_dir_is_centralized() -> None:
    """All R6 generators share one _DEFAULT_R6_OUTPUT_DIR constant."""
    from payload_pipeline.games.r6.account.media.image_renderer import _DEFAULT_R6_OUTPUT_DIR
    from payload_pipeline.games.r6.account.media.lzt_image_generator import _DEFAULT_R6_OUTPUT_DIR as lzt_dir
    from payload_pipeline.games.r6.account.media.tracker_image_generator import _DEFAULT_R6_OUTPUT_DIR as tracker_dir

    assert lzt_dir == _DEFAULT_R6_OUTPUT_DIR
    assert tracker_dir == _DEFAULT_R6_OUTPUT_DIR
    output_path = Path(_DEFAULT_R6_OUTPUT_DIR)
    assert "output" in output_path.parts
    assert "r6" in output_path.parts


def test_lol_catalog_resources_dir_is_file_relative() -> None:
    """LoL catalog data file lives next to the module, not at repo root."""
    from payload_pipeline.games.lol.account.catalog import _RESOURCES_DIR, _DEFAULT_ASSETS_PATH

    assert _RESOURCES_DIR.is_absolute()
    assert _DEFAULT_ASSETS_PATH.exists(), f"Missing: {_DEFAULT_ASSETS_PATH}"


def test_shared_paths_default_media_output_dir() -> None:
    """shared.paths produces CWD-relative output dirs by default."""
    from payload_pipeline.shared.paths import default_media_output_dir

    r6_dir = Path(default_media_output_dir("r6"))
    val_dir = Path(default_media_output_dir("valorant", suffix="abc123"))

    # Both should contain the expected game slug and structure
    assert "output" in r6_dir.parts
    assert "payload_pipeline" in r6_dir.parts
    assert "r6" in r6_dir.parts
    assert "images" in r6_dir.parts

    assert "valorant" in val_dir.parts
    assert "abc123" in val_dir.parts


def test_shared_paths_default_cache_base_dir() -> None:
    from payload_pipeline.shared.paths import default_cache_base_dir

    cache_dir = Path(default_cache_base_dir("r6"))
    assert "output" in cache_dir.parts
    assert "payload_pipeline" in cache_dir.parts
    assert "cache" in cache_dir.parts
    assert "r6" in cache_dir.parts


def test_shared_paths_env_override(monkeypatch) -> None:
    """PAYLOAD_PIPELINE_OUTPUT_DIR env var overrides the CWD-relative default."""
    from payload_pipeline.shared.paths import default_media_output_dir, default_cache_base_dir

    # Use a distinctive marker that won't collide with CWD path parts
    monkeypatch.setenv("PAYLOAD_PIPELINE_OUTPUT_DIR", "CUSTOM_OVERRIDE_ROOT")

    media = default_media_output_dir("r6")
    cache = default_cache_base_dir("r6")

    assert "CUSTOM_OVERRIDE_ROOT" in media
    assert "r6" in Path(media).parts
    assert "CUSTOM_OVERRIDE_ROOT" in cache
    assert "cache" in Path(cache).parts


def test_hosted_media_publisher_requires_explicit_uploaders() -> None:
    """HostedMediaPublisher must not silently import from src.services."""
    from payload_pipeline.shared.media import HostedMediaPublisher

    # Without explicit uploaders, construction must fail (TypeError for missing args)
    import inspect
    sig = inspect.signature(HostedMediaPublisher.__init__)
    params = sig.parameters
    # Both should be keyword-only and required (no default)
    assert params["dropbox_uploader"].default is inspect.Parameter.empty
    assert params["imageshack_processor"].default is inspect.Parameter.empty


def test_no_src_imports_in_payload_pipeline_module_code() -> None:
    """Importable module code must not contain runtime 'from src.' imports."""
    import payload_pipeline as pkg
    pkg_dir = Path(pkg.__file__).resolve().parent

    violations = []
    for py_file in pkg_dir.rglob("*.py"):
        # Skip demo scripts (they run inside the host repo on purpose)
        if py_file.name.startswith("demo_"):
            continue
        content = py_file.read_text(encoding="utf-8", errors="replace")
        in_docstring = False
        for i, line in enumerate(content.splitlines(), 1):
            # Track triple-quote docstring blocks
            triple_count = line.count('"""') + line.count("'''")
            if triple_count == 1:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "from src." in stripped or "import src." in stripped:
                violations.append(f"{py_file.relative_to(pkg_dir)}:{i}: {stripped}")

    assert violations == [], "Found src.* imports in module code:\n" + "\n".join(violations)

"""Tests for the GTA V account slice."""

from __future__ import annotations

from dataclasses import replace

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import BuildContext, CredentialBundle, PipelineRequest
from payload_pipeline.games.gtav.account import GtavMediaStrategy, GtavResolver
from payload_pipeline.games.gtav.account.media import GtavAccountCardRenderer, GtavCardData
from payload_pipeline.games.gtav.account.credentials import (
    format_platform_credentials,
    resolve_platform_credentials,
)
from payload_pipeline.games.gtav.account.sources.manual import GtavManualSourceAdapter
from payload_pipeline.marketplaces.g2g import G2GConfig


# -- source adapter tests -------------------------------------------------

class TestGtavManualSourceAdapter:
    def test_parse_returns_none_for_empty_input(self):
        adapter = GtavManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_core_fields(self, load_fixture):
        adapter = GtavManualSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source is not None
        assert source.item_id == "330012001"
        assert source.category_id == 22
        assert source.main_platform == "PC - Enhanced"
        assert source.level == 350
        assert source.cash_amount == 120
        assert source.cash_unit == "Million"
        assert source.cars_count == 45
        assert source.tags == ["Modded", "High Level", "Full Access"]

    def test_parse_extracts_credentials(self, load_fixture):
        adapter = GtavManualSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source.credentials.login == "rockstar_user@example.com"
        assert source.credentials.password == "RockstarPass123"
        assert source.credentials.email_login == "backup_email@example.com"
        assert source.credentials.email_password == "EmailPass456"

    def test_parse_extracts_security_fields(self, load_fixture):
        adapter = GtavManualSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source.security_email == "security@example.com"
        assert source.security_email_password == "SecPass789"
        assert source.birthday == "1995-06-15"
        assert source.email_backup_codes == "CODE1-ABCD\nCODE2-EFGH\nCODE3-IJKL"

    def test_parse_extracts_title_from_offer_details(self, load_fixture):
        adapter = GtavManualSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert "Level 350" in source.title
        assert "120M Cash" in source.title


    def test_parse_extracts_credential_extras(self):
        adapter = GtavManualSourceAdapter()
        raw = {
            "loginData": {"login": "steam_user", "password": "steam_pass"},
            "price": 10.0,
            "offer_details": {"main_platform": "PC - Legacy"},
            "steam_id": "steam_user",
            "steam_pass": "steam_pass",
            "rock_id": "rockstar_user",
            "rock_pass": "rockstar_pass",
        }
        source = adapter.parse(raw)
        assert source is not None
        assert source.credential_extras["steam_id"] == "steam_user"
        assert source.credential_extras["rock_id"] == "rockstar_user"
        assert source.credential_extras["rock_pass"] == "rockstar_pass"


# -- credential formatting tests ------------------------------------------

class TestGtavCredentials:
    """Platform-aware credential formatting."""

    def test_psn_format_labels(self):
        creds = CredentialBundle(
            login="psn_user", password="psn_pass",
            email_login="email@test.com", email_password="epass",
        )
        raw = {"dob": "1990-01-15"}
        pairs = resolve_platform_credentials("PlayStation 5", creds, raw)
        labels = [label for label, _ in pairs]

        assert labels[0] == "PSN ID"
        assert labels[1] == "PSN Password"
        assert "Email" in labels
        assert "Date of Birth" in labels

    def test_xbox_format_no_dob(self):
        creds = CredentialBundle(login="xbox_user", password="xbox_pass")
        pairs = resolve_platform_credentials("Xbox One", creds)
        labels = [label for label, _ in pairs]

        assert labels[0] == "Xbox ID"
        assert labels[1] == "Xbox Password"
        assert "Date of Birth" not in labels

    def test_pc_format_dual_credentials(self):
        creds = CredentialBundle(
            login="steam_user", password="steam_pass",
            email_login="email@test.com", email_password="epass",
        )
        raw = {"rock_id": "rockstar_user", "rock_pass": "rockstar_pass"}
        pairs = resolve_platform_credentials("PC - Legacy", creds, raw)
        labels = [label for label, _ in pairs]
        values = {label: val for label, val in pairs}

        assert labels[0] == "Steam ID"
        assert labels[1] == "Steam Password"
        assert "Rockstar ID" in labels
        assert "Rockstar Password" in labels
        assert values["Steam ID"] == "steam_user"
        assert values["Rockstar ID"] == "rockstar_user"

    def test_pc_raw_data_overrides_credential_bundle(self):
        """When raw_data has steam_id, it takes priority over CredentialBundle.login."""
        creds = CredentialBundle(login="fallback_login", password="fallback_pass")
        raw = {"steam_id": "real_steam", "steam_pass": "real_pass"}
        pairs = resolve_platform_credentials("PC - Enhanced", creds, raw)
        values = {label: val for label, val in pairs}

        assert values["Steam ID"] == "real_steam"
        assert values["Steam Password"] == "real_pass"

    def test_unknown_platform_uses_default(self):
        creds = CredentialBundle(login="user", password="pass")
        pairs = resolve_platform_credentials("Unknown Platform", creds)
        labels = [label for label, _ in pairs]

        assert labels[0] == "Login"
        assert labels[1] == "Password"

    def test_format_platform_credentials_output(self):
        creds = CredentialBundle(login="psn_user", password="psn_pass")
        result = format_platform_credentials("PlayStation 4", creds)

        assert "PSN ID: psn_user" in result
        assert "PSN Password: psn_pass" in result

    def test_format_with_custom_separator(self):
        creds = CredentialBundle(login="user", password="pass")
        result = format_platform_credentials(
            "Xbox Series X/S", creds, separator="<br><br>",
        )
        assert "<br><br>" in result
        assert "\n" not in result

    def test_format_with_disclaimer(self):
        creds = CredentialBundle(login="user", password="pass")
        result = format_platform_credentials(
            "PlayStation 5", creds, disclaimer="Do not dispute!",
        )
        assert result.endswith("Do not dispute!")

    def test_format_strip_url_scheme(self):
        creds = CredentialBundle(
            login="user", password="pass",
            email_login_link="https://mail.example.com/login",
        )
        result = format_platform_credentials(
            "PlayStation 5", creds, strip_url_scheme=True,
        )
        assert "https://" not in result
        assert "mail.example.com/login" in result

    def test_empty_values_omitted(self):
        creds = CredentialBundle(login="user", password="pass")
        pairs = resolve_platform_credentials("PlayStation 5", creds)
        labels = [label for label, _ in pairs]

        assert "Email" not in labels
        assert "Security Email" not in labels

    def test_security_email_from_credential_bundle(self):
        creds = CredentialBundle(
            login="user", password="pass",
            security_email="sec@test.com",
            security_email_password="secpass",
        )
        pairs = resolve_platform_credentials("Xbox One", creds)
        values = {label: val for label, val in pairs}

        assert values["Security Email"] == "sec@test.com"
        assert values["Security Email Password"] == "secpass"


# -- resolver tests --------------------------------------------------------

class TestGtavResolver:
    def test_resolver_populates_all_fields(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)

        assert account.main_platform == "PC - Enhanced"
        assert account.level == 350
        assert account.cash_amount == 120
        assert account.cash_unit == "Million"
        assert account.cars_count == 45
        assert account.tags == ["Modded", "High Level", "Full Access"]
        assert account.has_email_access is True
        assert account.security_email == "security@example.com"
        assert account.birthday == "1995-06-15"

    def test_resolver_populates_credential_extras(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)

        assert "dob" in account.credential_extras
        assert account.credential_extras["dob"] == "1995-06-15"
        assert "security_email_login_link" in account.credential_extras

    def test_resolver_rejects_missing_source(self):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={},
        )
        with pytest.raises(Exception, match="manual|lzt"):
            GtavResolver().resolve(request)

    def test_resolver_dropshipping_clears_credentials(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="dropshipping",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        assert account.credentials.is_empty


# -- composer tests --------------------------------------------------------

class TestGtavComposer:
    def test_compose_produces_listing_draft(self, load_fixture):
        from payload_pipeline.games.gtav.account.content import GtavComposer
        from payload_pipeline.core.contracts import MediaBundle

        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        draft = GtavComposer().compose(account, request, MediaBundle())

        assert draft.default.title
        assert "GTA V" in draft.default.description or "Platform" in draft.default.description
        assert "gta-v" in draft.default.tags

    def test_compose_g2g_override_shorter(self, load_fixture):
        from payload_pipeline.games.gtav.account.content import GtavComposer
        from payload_pipeline.core.contracts import MediaBundle

        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        draft = GtavComposer().compose(account, request, MediaBundle())

        g2g_content = draft.content_for("g2g")
        assert len(g2g_content.title) <= 120 or g2g_content.title == draft.default.title


# -- registry tests --------------------------------------------------------

class TestGtavRegistration:
    def test_gtav_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("grand-theft-auto-5")

    def test_gtav_has_all_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("grand-theft-auto-5", "account")
        assert set(defn.marketplaces.keys()) == {
            "eldorado", "gameboost", "g2g", "playerauctions",
        }


# -- media strategy tests --------------------------------------------------

class TestGtavMediaStrategy:
    def test_media_strategy_uses_override_path(self, load_fixture, tmp_path):
        override = tmp_path / "selected.png"
        override.write_bytes(b"selected-image")
        output_dir = tmp_path / "generated"
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
            context={
                ctx.MEDIA_OUTPUT_DIR: str(output_dir),
                ctx.MEDIA_OVERRIDE_PATH: str(override),
            },
        )
        account = GtavResolver().resolve(request)

        result = GtavMediaStrategy().prepare(account, request)

        assert result == [str(override)]
        assert not output_dir.exists()

    def test_media_strategy_generates_cached_card(self, load_fixture, tmp_path):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
            context={ctx.MEDIA_OUTPUT_DIR: str(tmp_path)},
        )
        account = GtavResolver().resolve(request)
        strategy = GtavMediaStrategy()

        first = strategy.prepare(account, request)
        second = strategy.prepare(account, request)

        assert len(first) == 1
        assert first == second
        assert first[0].startswith(str(tmp_path))
        assert first[0].endswith(".png")
        assert len(list(tmp_path.glob("gtav_account_*.png"))) == 1

    def test_media_fingerprint_ignores_private_account_fields(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        changed_private_fields = replace(
            account,
            item_id="different-item",
            credentials=CredentialBundle(login="private@example.com", password="secret"),
            security_email="private-security@example.com",
            email_backup_codes="PRIVATE-CODE",
        )

        renderer = GtavAccountCardRenderer()
        first = GtavCardData.from_account(account, delivery_text="INSTANT DELIVERY")
        second = GtavCardData.from_account(changed_private_fields, delivery_text="INSTANT DELIVERY")

        assert first == second
        assert renderer.fingerprint(first) == renderer.fingerprint(second)


# -- end-to-end pipeline tests --------------------------------------------

class TestGtavPipeline:
    def test_pipeline_builds_all_marketplaces(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        marketplaces = ["eldorado", "gameboost", "g2g", "playerauctions"]
        results = {}
        for mp in marketplaces:
            build_ctx = BuildContext(kind="stock", marketplace=mp)
            if mp == "g2g":
                build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
            result = pipeline.build(prepared, build_ctx)
            assert result.success
            results[mp] = result.payload
        assert set(results.keys()) == {"eldorado", "gameboost", "g2g", "playerauctions"}

    def test_eldorado_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
        assert result.success

        assert result.payload["augmentedGame"]["gameId"] == "25"
        assert result.payload["augmentedGame"]["category"] == "Account"
        assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "5"  # PC - Enhanced -> 5
        assert result.payload["details"]["pricing"]["pricePerUnit"]["amount"] == 450.0
        # Platform-aware delivery: PC - Enhanced → Steam labels
        secret = result.payload["accountSecretDetails"][0]
        assert "Steam ID:" in secret or "Login:" in secret  # depending on raw_data
        assert "Backup Codes:" in secret

    def test_gameboost_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))
        assert result.success

        assert result.payload["game"] == "grand-theft-auto-v"
        assert result.payload["account_data"]["platform"] == "PC \u00b7 Enhanced"
        assert result.payload["account_data"]["account_level"] == 350
        assert result.payload["account_data"]["cars_count"] == 45
        assert result.payload["account_data"]["cash_amount"] == "120 Million"
        assert result.payload["image_urls"]  # static image URL

    def test_g2g_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
        assert result.success

        assert result.payload["brand_id"] == "lgc_game_24333"
        assert result.payload["softpin_data"]
        assert len(result.payload["offer_attributes"]) == 1
        assert result.payload["offer_attributes"][0]["dataset_id"] == "lgc_24333_platform_26098"

    def test_playerauctions_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        prepared.listing.media.external_urls.append("https://cdn.example.com/gtav.png")
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success

        assert result.payload["gameId"] == 5917
        assert result.payload["serverId"] == 14270
        assert result.payload["categoryId"] == 14270
        assert result.payload["screenShot"] == "https://cdn.example.com/gtav.png"
        assert result.payload["autoDelivery"]["loginName"] == "rockstar_user@example.com"
        assert result.payload["autoDelivery"]["choose5"] is True

    def test_prepare_once_populates_subject(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        subject = prepared.subject

        assert subject.main_platform == "PC - Enhanced"
        assert subject.level == 350


# -- determinism & mapping intent tests ------------------------------------

class TestGtavG2GDeterminism:
    """G2G payloads must be identical across repeated builds for the same input."""

    def test_g2g_payload_is_deterministic(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        payloads = []
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
            assert result.success
            payloads.append(result.payload)
        first = payloads[0]
        for p in payloads[1:]:
            assert p == first, "G2G payload must be deterministic across invocations"

    def test_g2g_platform_is_always_android(self, load_fixture):
        """Legacy fallback: always Android (lgc_24333_platform_26098)."""
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
            assert result.success
            attrs = result.payload["offer_attributes"]
            assert len(attrs) == 1
            assert attrs[0]["collection_id"] == "lgc_24333_platform"
            assert attrs[0]["dataset_id"] == "lgc_24333_platform_26098"


class TestGtavPlayerAuctionsMappingIntent:
    """PlayerAuctions mapping values should follow the GTA V template."""

    def test_server_value_is_platform_specific(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True})
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success
        assert result.payload["serverId"] == 14270
        assert result.payload["categoryId"] == 14270

    def test_game_id_matches_template(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True})
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success
        assert result.payload["gameId"] == 5917

    def test_playerauctions_payload_is_deterministic(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        payloads = []
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019", ctx.DISABLE_MEDIA: True})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
            assert result.success
            payloads.append(result.payload)
        first = payloads[0]
        for p in payloads[1:]:
            assert p == first, "PA payload must be deterministic across invocations"

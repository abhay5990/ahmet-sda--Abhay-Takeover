"""Tests for the CS2 account slice — eldorado, gameboost, g2g builders."""

from __future__ import annotations

from payload_pipeline.core.contracts import (
    BuildContext,
    CredentialBundle,
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.games.cs2.account.models import CS2ResolvedAccount
from payload_pipeline.games.cs2.account.marketplaces.eldorado import CS2EldoradoBuilder
from payload_pipeline.games.cs2.account.marketplaces.gameboost import CS2GameBoostBuilder
from payload_pipeline.games.cs2.account.marketplaces.g2g import CS2G2GBuilder
from payload_pipeline.games.cs2.account.sources.lzt import CS2LztSourceAdapter
from payload_pipeline.games.cs2.account.resolver import CS2Resolver
from payload_pipeline.games.cs2.account.content.composer import CS2Composer
from payload_pipeline.pricing import PricingRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(**overrides) -> CS2ResolvedAccount:
    defaults = dict(
        item_id="12345",
        category_id=1,
        price=5.0,
        kind="stock",
        credentials=CredentialBundle(
            login="user1",
            password="pass1",
            email_login="user1@mail.com",
            email_password="emailpass1",
            email_login_link="https://mail.com/login",
        ),
        rank="Gold Nova",
        rank_id=7,
        premier_elo=12000,
        medals=["2020", "2021", "2022"],
        is_prime=True,
        has_email_access=True,
        hours_played=500,
    )
    defaults.update(overrides)
    return CS2ResolvedAccount(**defaults)


def _make_listing(**overrides) -> ListingDraft:
    defaults = dict(
        default=ListingContent(
            title="CS2 | Gold Nova | 12000 Premier | Prime | 3 Medals",
            description="Counter-Strike 2 Account\n---\nRank: Gold Nova",
            tags=["cs2", "counter-strike-2", "account"],
        ),
        media=MediaBundle(),
        marketplace_overrides={
            "g2g": MarketplaceListingOverride(
                title="CS2 | Gold Nova | 12000 Premier | Prime",
            ),
        },
    )
    defaults.update(overrides)
    return ListingDraft(**defaults)


def _make_request(marketplace: str = "eldorado", mode: str = "stock", **ctx_extra) -> PipelineRequest:
    if marketplace == "g2g" and ctx.G2G_SELLER_ID not in ctx_extra:
        ctx_extra[ctx.G2G_SELLER_ID] = "1000959019"
    return PipelineRequest(
        game="counter-strike-2",
        kind=mode,
        sources={"lzt": {}},
        context=ctx_extra,
    )


def _make_build_ctx(
    marketplace: str = "eldorado",
    kind: str = "stock",
    pricing_rules: dict | None = None,
    g2g_seller_id: str = "",
    g2g_service_id: str = "",
) -> BuildContext:
    from payload_pipeline.marketplaces.g2g import G2GConfig

    marketplace_config = None
    if marketplace == "g2g":
        marketplace_config = G2GConfig(
            seller_id=g2g_seller_id or "1000959019",
            service_id=g2g_service_id,
        )
    return BuildContext(
        kind=kind,
        marketplace=marketplace,
        pricing_rules=pricing_rules,
        marketplace_config=marketplace_config,
    )


# ===========================================================================
# Registration
# ===========================================================================

def test_registration_includes_all_three_marketplaces():
    from payload_pipeline.core.registry import PipelineRegistry
    from payload_pipeline.games.cs2.account import register

    registry = PipelineRegistry()
    register(registry)
    definition = registry.get_game("counter-strike-2", "account")
    assert set(definition.marketplaces.keys()) == {"eldorado", "gameboost", "g2g"}


# ===========================================================================
# Source adapter — new fields
# ===========================================================================

def test_lzt_adapter_parses_rank_id_and_hours():
    raw = {
        "item_id": "999",
        "price": "10",
        "rank": "Silver",
        "steam_cs2_rank_id": "3",
        "hours_played": "120",
        "premier_elo": "5000",
        "is_prime": True,
        "medals": ["2020"],
        "loginData": {"login": "u", "password": "p"},
    }
    source = CS2LztSourceAdapter().parse(raw)
    assert source is not None
    assert source.rank_id == 3
    assert source.hours_played == 120


def test_lzt_adapter_defaults_missing_new_fields():
    raw = {"item_id": "1", "price": "5", "loginData": {"login": "u", "password": "p"}}
    source = CS2LztSourceAdapter().parse(raw)
    assert source is not None
    assert source.rank_id == 0
    assert source.hours_played == 0


# ===========================================================================
# Resolver — new fields flow through
# ===========================================================================

def test_resolver_passes_new_fields():
    request = PipelineRequest(
        game="counter-strike-2", kind="stock",
        sources={
            "lzt": {
                "item_id": "1", "price": "5",
                "loginData": {"login": "u", "password": "p"},
                "steam_cs2_rank_id": "7",
                "hours_played": "300",
            }
        },
    )
    account = CS2Resolver().resolve(request)
    assert account.rank_id == 7
    assert account.hours_played == 300


# ===========================================================================
# Eldorado — legacy attribute parity
# ===========================================================================

def _offer_attrs_to_dict(offer_attributes: list[dict]) -> dict[str, str]:
    """Convert offerAttributes array to {id: value} dict for easy assertions."""
    return {a["id"]: a["value"] for a in offer_attributes}


def test_eldorado_attribute_keys_match_legacy():
    account = _make_account(is_prime=True, medals=["a"] * 15)
    listing = _make_listing()
    ctx = _make_build_ctx("eldorado")
    payload = CS2EldoradoBuilder().build_payload(account, listing, ctx)

    attrs = _offer_attrs_to_dict(payload["augmentedGame"]["offerAttributes"])
    assert "counter-strike-2-prime-status" in attrs
    assert "counter-strike-2-medals" in attrs
    assert attrs["counter-strike-2-prime-status"] == "active-prime"
    assert attrs["counter-strike-2-medals"] == "10-19-medals"
    # Legacy keys should NOT be present
    assert "primeStatus" not in attrs
    assert "medalCount" not in attrs
    assert "rank" not in attrs


def test_eldorado_medal_buckets():
    builder = CS2EldoradoBuilder()
    assert builder._medal_bucket(0) == "0-9-medals"
    assert builder._medal_bucket(9) == "0-9-medals"
    assert builder._medal_bucket(10) == "10-19-medals"
    assert builder._medal_bucket(19) == "10-19-medals"
    assert builder._medal_bucket(20) == "20-29-medals"
    assert builder._medal_bucket(30) == "30-39-medals"
    assert builder._medal_bucket(40) == "40+-medals"
    assert builder._medal_bucket(99) == "40+-medals"


def test_eldorado_non_prime():
    account = _make_account(is_prime=False)
    payload = CS2EldoradoBuilder().build_payload(account, _make_listing(), _make_build_ctx())
    attrs = _offer_attrs_to_dict(payload["augmentedGame"]["offerAttributes"])
    assert attrs["counter-strike-2-prime-status"] == "non-prime"


def test_eldorado_trade_environment_tiers():
    builder = CS2EldoradoBuilder()
    assert builder._resolve_trade_environment_id(0) == "0"
    assert builder._resolve_trade_environment_id(1) == "1"
    assert builder._resolve_trade_environment_id(4999) == "1"
    assert builder._resolve_trade_environment_id(5000) == "2"
    assert builder._resolve_trade_environment_id(35000) == "8"


def test_eldorado_game_id():
    payload = CS2EldoradoBuilder().build_payload(_make_account(), _make_listing(), _make_build_ctx())
    assert payload["augmentedGame"]["gameId"] == "20"


# ===========================================================================
# GameBoost — stock
# ===========================================================================

def test_gameboost_stock_payload_structure():
    account = _make_account()
    listing = _make_listing()
    ctx = _make_build_ctx("gameboost")
    payload = CS2GameBoostBuilder().build_payload(account, listing, ctx)

    assert payload["game"] == "counter-strike-2"
    assert payload["login"] == "user1"
    assert payload["password"] == "pass1"
    assert payload["email_login"] == "user1@mail.com"
    assert payload["email_password"] == "emailpass1"
    assert payload["is_manual"] is False
    assert payload["delivery_time"] == {}
    assert payload["has_2fa"] is False
    assert payload["level_up_method"] == "by_hand"
    assert "slug" in payload
    assert payload["account_data"]["premier_rating_count"] == 12000
    assert payload["account_data"]["prime_enabled"] is True
    assert payload["account_data"]["hours_played_count"] == 500
    assert payload["account_data"]["trade_banned"] is False
    assert "dump" in payload


def test_gameboost_stock_delivery_instructions_format():
    account = _make_account()
    payload = CS2GameBoostBuilder().build_payload(account, _make_listing(), _make_build_ctx("gameboost"))
    di = payload["delivery_instructions"]
    assert "Steam Account -> user1" in di
    assert "Steam Account Password -> pass1" in di
    assert "E-mail -> user1@mail.com" in di
    assert "Important:" in di


def test_gameboost_stock_email_fallback():
    """When no email_login, email fields should be 'cometochat'."""
    account = _make_account(
        credentials=CredentialBundle(login="u", password="p"),
    )
    payload = CS2GameBoostBuilder().build_payload(account, _make_listing(), _make_build_ctx("gameboost"))
    assert payload["email_login"] == "cometochat"
    assert payload["email_password"] == "cometochat"


# ===========================================================================
# GameBoost — dropshipping
# ===========================================================================

def test_gameboost_dropshipping_payload():
    account = _make_account(kind="dropshipping", credentials=CredentialBundle())
    listing = _make_listing()
    ctx = _make_build_ctx("gameboost", kind="dropshipping")
    payload = CS2GameBoostBuilder().build_payload(account, listing, ctx)

    assert payload["is_manual"] is True
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["email_login"] is None
    assert payload["email_password"] is None
    assert "Thanks for purchase" in payload["delivery_instructions"]


# ===========================================================================
# GameBoost — pricing
# ===========================================================================

def test_gameboost_applies_pricing_rule():
    rule = PricingRule(multiplier_low=3.0)
    build_ctx = _make_build_ctx("gameboost", pricing_rules={"gameboost": rule})
    account = _make_account(price=5.0)
    payload = CS2GameBoostBuilder().build_payload(account, _make_listing(), build_ctx)
    assert payload["price"] == 15.0


# ===========================================================================
# GameBoost — dump tags
# ===========================================================================

def test_gameboost_dump_tags():
    account = _make_account(is_prime=True, premier_elo=15000, hours_played=200)
    payload = CS2GameBoostBuilder().build_payload(account, _make_listing(), _make_build_ctx("gameboost"))
    dump = payload["dump"]
    assert "prime cs2 account" in dump
    assert "15000 PR" in dump
    assert "200 hours" in dump


def test_gameboost_dump_tags_no_prime():
    account = _make_account(is_prime=False, premier_elo=0, hours_played=0)
    payload = CS2GameBoostBuilder().build_payload(account, _make_listing(), _make_build_ctx("gameboost"))
    assert "no prime" in payload["dump"]


# ===========================================================================
# G2G — stock payload
# ===========================================================================

def test_g2g_stock_payload_structure():
    account = _make_account()
    listing = _make_listing()
    ctx = _make_build_ctx("g2g")
    payload = CS2G2GBuilder().build_payload(account, listing, ctx)

    assert payload["brand_id"] == "lgc_game_22539"
    assert payload["service_id"] == "f6a1aba5-473a-4044-836a-8968bbab16d7"
    assert payload["seller_id"] == "1000959019"
    assert payload["delivery_method_ids"] == ["instant_inventory"]
    assert payload["delivery_speed"] == "instant"
    assert payload["currency"] == "USD"
    assert payload["offer_type"] == "public"
    assert payload["min_qty"] == 1
    assert payload["qty"] == 0
    # G2G title override should be used
    assert payload["title"] == "CS2 | Gold Nova | 12000 Premier | Prime"
    assert len(payload["offer_attributes"]) == 5


# ===========================================================================
# G2G — offer attributes
# ===========================================================================

def test_g2g_prime_attribute():
    builder = CS2G2GBuilder()
    account_prime = _make_account(is_prime=True)
    attrs = builder._build_offer_attributes(account_prime)
    prime_attr = attrs[0]
    assert prime_attr["collection_id"] == "50af404e"
    assert prime_attr["dataset_id"] == "25d9928f"

    account_no_prime = _make_account(is_prime=False)
    attrs2 = builder._build_offer_attributes(account_no_prime)
    assert attrs2[0]["dataset_id"] == "66431b9f"


def test_g2g_elo_tiers():
    from payload_pipeline.games.cs2.account.marketplaces.g2g import _dataset_for_elo

    assert _dataset_for_elo(0) == "249dd800"    # UnRated
    assert _dataset_for_elo(1) == "73fde4a8"    # 1-5k
    assert _dataset_for_elo(4999) == "73fde4a8"
    assert _dataset_for_elo(5000) == "c0642e14"  # 5-10k
    assert _dataset_for_elo(9999) == "c0642e14"
    assert _dataset_for_elo(10000) == "95871f79"  # 10-15k
    assert _dataset_for_elo(15000) == "1b7bfd08"  # 15-20k
    assert _dataset_for_elo(20000) == "7090e0f8"  # 20-25k
    assert _dataset_for_elo(25000) == "1e176870"  # 25-30k
    assert _dataset_for_elo(30000) == "9762e3c7"  # 30k+
    assert _dataset_for_elo(50000) == "9762e3c7"


def test_g2g_rank_id_mapping():
    from payload_pipeline.games.cs2.account.marketplaces.g2g import _dataset_for_rank_id

    assert _dataset_for_rank_id(0) == "7d397218"   # UnRanked
    assert _dataset_for_rank_id(1) == "e651dde8"   # Silver
    assert _dataset_for_rank_id(6) == "e651dde8"   # Silver
    assert _dataset_for_rank_id(7) == "61d844c6"   # Gold Nova
    assert _dataset_for_rank_id(11) == "38b1679f"  # Master Guardian
    assert _dataset_for_rank_id(13) == "547b39ec"  # MG Elite
    assert _dataset_for_rank_id(14) == "6a89a15c"  # DMG
    assert _dataset_for_rank_id(15) == "f4645f9e"  # LE
    assert _dataset_for_rank_id(16) == "e481dcd2"  # LEM
    assert _dataset_for_rank_id(17) == "49af889e"  # Supreme
    assert _dataset_for_rank_id(18) == "6c61f581"  # Global Elite
    assert _dataset_for_rank_id(99) == "7d397218"  # Unknown → UnRanked


def test_g2g_medal_tiers():
    from payload_pipeline.games.cs2.account.marketplaces.g2g import _dataset_for_medals

    assert _dataset_for_medals(0) == "4fefd16a"    # 0-5
    assert _dataset_for_medals(5) == "4fefd16a"
    assert _dataset_for_medals(6) == "2bd1eae0"    # 6-9
    assert _dataset_for_medals(9) == "2bd1eae0"
    assert _dataset_for_medals(10) == "2659e8e8"   # 10-19
    assert _dataset_for_medals(20) == "8c3b1b3b"   # 20-29
    assert _dataset_for_medals(30) == "85957da6"   # 30-39
    assert _dataset_for_medals(40) == "0a4ee878"   # 40-49
    assert _dataset_for_medals(50) == "7ce240e4"   # 50+
    assert _dataset_for_medals(100) == "7ce240e4"


# ===========================================================================
# G2G — softpin CSV
# ===========================================================================

def test_g2g_softpin_csv():
    account = _make_account()
    csv = CS2G2GBuilder().prepare_softpin_data(account)
    assert csv.startswith("user1,pass1,,,,,,,,user1@mail.com,emailpass1,")
    assert csv.endswith("\r\n")
    assert "Important:" in csv


def test_g2g_softpin_csv_password_1():
    account = _make_account(
        credentials=CredentialBundle(login="u", password="1", email_login="e@m.com"),
    )
    csv = CS2G2GBuilder().prepare_softpin_data(account)
    assert csv.startswith("u,noneedpsswd,")


# ===========================================================================
# G2G — pricing
# ===========================================================================

def test_g2g_applies_pricing_rule():
    rule = PricingRule(multiplier_low=2.5)
    build_ctx = _make_build_ctx("g2g", pricing_rules={"g2g": rule})
    account = _make_account(price=8.0)
    payload = CS2G2GBuilder().build_payload(account, _make_listing(), build_ctx)
    assert payload["unit_price"] == 20.0


def test_g2g_no_pricing_rule_uses_raw():
    build_ctx = _make_build_ctx("g2g")
    account = _make_account(price=7.5)
    payload = CS2G2GBuilder().build_payload(account, _make_listing(), build_ctx)
    assert payload["unit_price"] == 7.5


# ===========================================================================
# G2G — images
# ===========================================================================

def test_g2g_external_images_mapping():
    listing = _make_listing(
        media=MediaBundle(external_urls=["https://img1.com/a.png", "https://img2.com/b.png"]),
    )
    payload = CS2G2GBuilder().build_payload(_make_account(), listing, _make_build_ctx("g2g"))
    images = payload["external_images_mapping"]
    assert len(images) == 2
    assert images[0] == {"image_name": "image_1", "image_url": "https://img1.com/a.png"}


def test_g2g_album_fallback():
    listing = _make_listing(
        media=MediaBundle(album_url="https://album.com/123"),
    )
    payload = CS2G2GBuilder().build_payload(_make_account(), listing, _make_build_ctx("g2g"))
    images = payload["external_images_mapping"]
    assert len(images) == 1
    assert images[0] == {"image_name": "album", "image_url": "https://album.com/123"}


# ===========================================================================
# Composer — existing behavior preserved
# ===========================================================================

def test_composer_produces_g2g_override():
    account = _make_account()
    request = _make_request("g2g")
    listing = CS2Composer().compose(account, request, MediaBundle())
    assert "g2g" in listing.marketplace_overrides
    g2g_title = listing.content_for("g2g").title
    assert len(g2g_title) <= 120


# ===========================================================================
# Full integration: resolver → composer → builder
# ===========================================================================

def test_full_stock_eldorado_pipeline():
    request = PipelineRequest(
        game="counter-strike-2", kind="stock",
        sources={
            "lzt": {
                "item_id": "55", "price": "10",
                "loginData": {"login": "u", "password": "p"},
                "premier_elo": "20000", "is_prime": True,
                "medals": ["2020", "2021"],
            },
        },
    )
    account = CS2Resolver().resolve(request)
    listing = CS2Composer().compose(account, request, MediaBundle())
    build_ctx = _make_build_ctx("eldorado")
    payload = CS2EldoradoBuilder().build_payload(account, listing, build_ctx)

    assert payload["augmentedGame"]["gameId"] == "20"
    attrs = _offer_attrs_to_dict(payload["augmentedGame"]["offerAttributes"])
    assert attrs["counter-strike-2-prime-status"] == "active-prime"
    assert attrs["counter-strike-2-medals"] == "0-9-medals"


def test_full_stock_gameboost_pipeline():
    request = PipelineRequest(
        game="counter-strike-2", kind="stock",
        sources={
            "lzt": {
                "item_id": "55", "price": "10",
                "loginData": {"login": "u", "password": "p"},
                "premier_elo": "15000", "is_prime": False,
                "medals": [],
            },
        },
    )
    account = CS2Resolver().resolve(request)
    listing = CS2Composer().compose(account, request, MediaBundle())
    build_ctx = _make_build_ctx("gameboost")
    payload = CS2GameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["game"] == "counter-strike-2"
    assert payload["account_data"]["premier_rating_count"] == 15000
    assert payload["account_data"]["prime_enabled"] is False


def test_full_stock_g2g_pipeline():
    request = PipelineRequest(
        game="counter-strike-2", kind="stock",
        sources={
            "lzt": {
                "item_id": "55", "price": "10",
                "loginData": {"login": "u", "password": "p"},
                "premier_elo": "25000", "is_prime": True,
                "medals": ["a"] * 35, "steam_cs2_rank_id": "18",
            },
        },
        context={ctx.G2G_SELLER_ID: "1000959019"},
    )
    account = CS2Resolver().resolve(request)
    listing = CS2Composer().compose(account, request, MediaBundle())
    build_ctx = _make_build_ctx("g2g", g2g_seller_id="1000959019")
    payload = CS2G2GBuilder().build_payload(account, listing, build_ctx)

    assert payload["brand_id"] == "lgc_game_22539"
    attrs = payload["offer_attributes"]
    # Prime = True → 25d9928f
    assert attrs[0]["dataset_id"] == "25d9928f"
    # ELO 25000 → 1e176870
    assert attrs[2]["dataset_id"] == "1e176870"
    # Rank 18 → Global Elite → 6c61f581
    assert attrs[3]["dataset_id"] == "6c61f581"
    # 35 medals → 85957da6 (30-39 range)
    assert attrs[4]["dataset_id"] == "85957da6"


def test_full_dropshipping_gameboost_pipeline():
    request = PipelineRequest(
        game="counter-strike-2", kind="dropshipping",
        sources={
            "lzt": {
                "item_id": "55", "price": "10",
                "loginData": {"login": "u", "password": "p"},
                "premier_elo": "5000", "is_prime": True,
                "medals": [],
            },
        },
    )
    account = CS2Resolver().resolve(request)
    listing = CS2Composer().compose(account, request, MediaBundle())
    build_ctx = _make_build_ctx("gameboost", kind="dropshipping")
    payload = CS2GameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ===========================================================================
# G2G — seller / service ID override via context
# ===========================================================================

def test_g2g_uses_default_seller_and_service_ids():
    build_ctx = _make_build_ctx("g2g")
    payload = CS2G2GBuilder().build_payload(_make_account(), _make_listing(), build_ctx)

    assert payload["seller_id"] == "1000959019"
    assert payload["service_id"] == "f6a1aba5-473a-4044-836a-8968bbab16d7"


def test_g2g_seller_id_overridden_via_context():
    build_ctx = _make_build_ctx("g2g", g2g_seller_id="9999999999")
    payload = CS2G2GBuilder().build_payload(_make_account(), _make_listing(), build_ctx)

    assert payload["seller_id"] == "9999999999"
    assert payload["service_id"] == "f6a1aba5-473a-4044-836a-8968bbab16d7"


def test_g2g_service_id_overridden_via_context():
    build_ctx = _make_build_ctx("g2g", g2g_service_id="custom-service-id")
    payload = CS2G2GBuilder().build_payload(_make_account(), _make_listing(), build_ctx)

    assert payload["seller_id"] == "1000959019"
    assert payload["service_id"] == "custom-service-id"


def test_g2g_both_ids_overridden_via_context():
    build_ctx = _make_build_ctx("g2g", g2g_seller_id="1111", g2g_service_id="2222")
    payload = CS2G2GBuilder().build_payload(_make_account(), _make_listing(), build_ctx)

    assert payload["seller_id"] == "1111"
    assert payload["service_id"] == "2222"

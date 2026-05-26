"""Create GameVariant, GameVariantMapping, GameVariantLimit models and seed data.

Seed data covers all games with variant routing:
- Fortnite: 6 platform variants
- GTA V: 6 platform variants
- Rainbow Six Siege: 3 platform variants
- Valorant: 6 region + 3 platform (Eldorado-only) variants
- League of Legends: 16 region variants
- Genshin Impact: 4 region variants

Also migrates existing SubplatformLimit data to GameVariantLimit.
"""

from django.db import migrations, models
import django.db.models.deletion


# ── Seed data ────────────────────────────────────────────────────

# Format: (slug, label, sort_order, source_key, {marketplace: (external_id, external_name)})
# source_key: account field value for lookup. Empty string = use slug.
# external_name is optional — empty string means not set.

FORTNITE_PLATFORMS = [
    ("pc", "PC", 0, "", {
        "eldorado": ("0", ""),
        "playerauctions": ("7877", "PC"),
        # GameBoost: no hardcoded platform ID — uses account props directly
    }),
    ("psn", "PlayStation", 1, "", {
        "eldorado": ("1", ""),
        "playerauctions": ("7878", "PlayStation"),
    }),
    ("xbox", "Xbox", 2, "", {
        "eldorado": ("2", ""),
        "playerauctions": ("7879", "Xbox"),
    }),
    ("android", "Android", 3, "", {
        "eldorado": ("3", ""),
        "playerauctions": ("8173", "Android"),
    }),
    ("ios", "iOS", 4, "", {
        "eldorado": ("4", ""),
        "playerauctions": ("8172", "IOS"),
    }),
    ("switch", "Switch", 5, "", {
        "eldorado": ("5", ""),
        "playerauctions": ("8321", "Switch"),
    }),
]

GTAV_PLATFORMS = [
    ("pc-legacy", "PC - Legacy", 0, "PC - Legacy", {
        "eldorado": ("0", ""),
        "playerauctions": ("5920", "PC-Steam-Legacy"),
        "gameboost": ("PC \u00b7 Legacy", ""),
    }),
    ("pc-enhanced", "PC - Enhanced", 1, "PC - Enhanced", {
        "eldorado": ("5", ""),
        "playerauctions": ("14270", "PC-Steam-Enhanced"),
        "gameboost": ("PC \u00b7 Enhanced", ""),
    }),
    ("ps4", "PlayStation 4", 2, "PlayStation 4", {
        "eldorado": ("1", ""),
        "playerauctions": ("5921", "PS4"),
    }),
    ("ps5", "PlayStation 5", 3, "PlayStation 5", {
        "eldorado": ("3", ""),
        "playerauctions": ("9874", "PS5"),
    }),
    ("xbox-one", "Xbox One", 4, "Xbox One", {
        "eldorado": ("2", ""),
        "playerauctions": ("5922", "XBOX ONE"),
    }),
    ("xbox-series", "Xbox Series X/S", 5, "Xbox Series X/S", {
        "eldorado": ("4", ""),
        "playerauctions": ("9889", "Xbox Series"),
    }),
]

R6_PLATFORMS = [
    ("pc", "PC", 0, "", {
        "eldorado": ("0", ""),
        "playerauctions": ("7774", "PC"),
        # GameBoost: uses account.primary_linkable_platform directly
    }),
    ("psn", "PlayStation", 1, "", {
        "eldorado": ("1", ""),
        "playerauctions": ("7775", "PlayStation"),
    }),
    ("xbox", "Xbox", 2, "", {
        "eldorado": ("2", ""),
        "playerauctions": ("7776", "Xbox"),
    }),
]

VALORANT_REGIONS = [
    ("na", "North America", 0, "NA", {
        "eldorado": ("0", ""),
        "playerauctions": ("9089", "NA"),
        "gameboost": ("North America", ""),
    }),
    ("eu", "Europe", 1, "EU", {
        "eldorado": ("1", ""),
        "playerauctions": ("9128", "EU"),
        "gameboost": ("Europe", ""),
    }),
    ("la", "Latin America", 2, "LA", {
        "eldorado": ("2", ""),
        "playerauctions": ("9207", "LATAM"),
        "gameboost": ("Latin America", ""),
    }),
    ("br", "Brazil", 3, "BR", {
        "eldorado": ("3", ""),
        "playerauctions": ("9208", "BR"),
        "gameboost": ("Brazil", ""),
    }),
    ("ap", "Asia Pacific", 4, "AP", {
        "eldorado": ("5", ""),
        "playerauctions": ("9309", "APAC"),
        "gameboost": ("Asia Pacific", ""),
    }),
    ("kr", "Korea", 5, "KR", {
        "eldorado": ("6", ""),
        "playerauctions": ("9206", "KR"),
        "gameboost": ("Asia Pacific", ""),  # KR maps to Asia Pacific on GB
    }),
    ("tr", "Turkey", 6, "TR", {
        # No Eldorado mapping for TR
        "playerauctions": ("14995", "TR"),
    }),
]

# Valorant platform — Eldorado-only (composite trade_env_id: region-platform)
VALORANT_PLATFORMS = [
    ("pc", "PC", 0, "", {"eldorado": ("0", "")}),
    ("psn", "PlayStation", 1, "", {"eldorado": ("1", "")}),
    ("xbox", "Xbox", 2, "", {"eldorado": ("2", "")}),
]

LOL_REGIONS = [
    ("brazil", "Brazil", 0, "Brazil", {
        "eldorado": ("0", ""),
        "playerauctions": ("6001", "Brazil"),
        "gameboost": ("Brazil", ""),
    }),
    ("eune", "Europe Nordic & East", 1, "Europe Nordic & East", {
        "eldorado": ("1", ""),
        "playerauctions": ("4144", "EU Nordic and East"),
        "gameboost": ("Europe Nordic & East", ""),
    }),
    ("euw", "Europe West", 2, "Europe West", {
        "eldorado": ("2", ""),
        "playerauctions": ("4143", "EU West"),
        "gameboost": ("Europe West", ""),
    }),
    ("lan", "Latin America North", 3, "Latin America North", {
        "eldorado": ("3", ""),
        "playerauctions": ("5772", "Latin America North"),
        "gameboost": ("Latin America North", ""),
    }),
    ("las", "Latin America South", 4, "Latin America South", {
        "eldorado": ("4", ""),
        "playerauctions": ("5773", "Latin America South"),
        "gameboost": ("Latin America South", ""),
    }),
    ("oce", "Oceania", 5, "Oceania", {
        "eldorado": ("5", ""),
        "playerauctions": ("5769", "Oceania"),
        "gameboost": ("Oceania", ""),
    }),
    ("ru", "Russia", 6, "Russia", {
        "eldorado": ("6", ""),
        "playerauctions": ("5771", "Russia"),
        "gameboost": ("Russia", ""),
    }),
    ("tr", "Turkey", 7, "Turkey", {
        "eldorado": ("7", ""),
        "playerauctions": ("5770", "Turkey"),
        "gameboost": ("Turkey", ""),
    }),
    ("jp", "Japan", 8, "Japan", {
        "eldorado": ("8", ""),
        "playerauctions": ("8928", "Japan"),
        "gameboost": ("Japan", ""),
    }),
    ("na", "North America", 9, "North America", {
        "eldorado": ("9", ""),
        "playerauctions": ("3638", "North America"),
        "gameboost": ("North America", ""),
    }),
    ("ph", "Philippines", 10, "Philippines", {
        "eldorado": ("13", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Philippines", ""),
    }),
    ("sg", "Singapore, Malaysia & Indonesia", 11, "Singapore, Malaysia & Indonesia", {
        "eldorado": ("12", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Singapore", ""),
    }),
    ("th", "Thailand", 12, "Thailand", {
        "eldorado": ("15", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Thailand", ""),
    }),
    ("vn", "Vietnam", 13, "Vietnam", {
        "eldorado": ("14", ""),
        "playerauctions": ("9496", "Southeast Asia"),
        "gameboost": ("Vietnam", ""),
    }),
    ("me", "Middle East", 14, "Middle East", {
        # No Eldorado mapping
        "playerauctions": ("13870", "Middle East"),
    }),
    ("pbe", "PBE", 15, "PBE", {
        # No Eldorado mapping
        "playerauctions": ("8605", "PBE"),
    }),
]

GENSHIN_REGIONS = [
    ("na", "America", 0, "", {
        "eldorado": ("0", ""),
        "playerauctions": ("9335", "America"),
        "gameboost": ("America", ""),
    }),
    ("eu", "Europe", 1, "", {
        "eldorado": ("1", ""),
        "playerauctions": ("9336", "Europe"),
        "gameboost": ("Europe", ""),
    }),
    ("asia", "Asia", 2, "", {
        "eldorado": ("2", ""),
        "playerauctions": ("9337", "Asia"),
        "gameboost": ("Asia", ""),
    }),
    ("tw", "TW/HK/MO", 3, "", {
        "eldorado": ("3", ""),
        "playerauctions": ("10104", "TW/HK/MO"),
        "gameboost": ("TW/HK/MO", ""),
    }),
]

# Map of game_slug → [(variant_type, variants_list)]
GAME_VARIANTS = {
    "fortnite": [("platform", FORTNITE_PLATFORMS)],
    "grand-theft-auto-5": [("platform", GTAV_PLATFORMS)],
    "rainbow-six-siege": [("platform", R6_PLATFORMS)],
    "valorant": [("region", VALORANT_REGIONS), ("platform", VALORANT_PLATFORMS)],
    "league-of-legends": [("region", LOL_REGIONS)],
    "genshin-impact": [("region", GENSHIN_REGIONS)],
}

# SubplatformLimit → GameVariantLimit slug mapping
# Keys: old sub_platform strings used in SubplatformLimit
# Values: (game_slug, variant_type, variant_slug)
SUBPLATFORM_SLUG_MAP = {
    ("fortnite", "PC"): "pc",
    ("fortnite", "PlayStation"): "psn",
    ("fortnite", "Xbox"): "xbox",
    ("fortnite", "Android"): "android",
    ("fortnite", "iOS"): "ios",
    ("fortnite", "Switch"): "switch",
    ("valorant", "PC"): "pc",
    ("valorant", "PlayStation"): "psn",
    ("valorant", "Xbox"): "xbox",
    ("rainbow-six-siege", "PC"): "pc",
    ("rainbow-six-siege", "PlayStation"): "psn",
    ("rainbow-six-siege", "PSN"): "psn",
    ("rainbow-six-siege", "Xbox"): "xbox",
}


def seed_variants(apps, schema_editor):
    Game = apps.get_model("inventory", "Game")
    GameVariant = apps.get_model("posting", "GameVariant")
    GameVariantMapping = apps.get_model("posting", "GameVariantMapping")

    for game_slug, variant_groups in GAME_VARIANTS.items():
        try:
            game = Game.objects.get(slug=game_slug)
        except Game.DoesNotExist:
            continue

        for variant_type, variants in variant_groups:
            for slug, label, sort_order, source_key, mappings in variants:
                variant = GameVariant.objects.create(
                    game=game,
                    type=variant_type,
                    slug=slug,
                    label=label,
                    sort_order=sort_order,
                    source_key=source_key,
                )
                for marketplace, (ext_id, ext_name) in mappings.items():
                    GameVariantMapping.objects.create(
                        variant=variant,
                        marketplace=marketplace,
                        external_id=ext_id,
                        external_name=ext_name,
                    )


def migrate_subplatform_limits(apps, schema_editor):
    """Migrate existing SubplatformLimit rows to GameVariantLimit."""
    SubplatformLimit = apps.get_model("posting", "SubplatformLimit")
    GameVariant = apps.get_model("posting", "GameVariant")
    GameVariantLimit = apps.get_model("posting", "GameVariantLimit")

    for old in SubplatformLimit.objects.select_related("game").all():
        game_slug = old.game.slug
        key = (game_slug, old.sub_platform)
        variant_slug = SUBPLATFORM_SLUG_MAP.get(key)
        if not variant_slug:
            continue

        try:
            variant = GameVariant.objects.get(
                game=old.game, type="platform", slug=variant_slug,
            )
        except GameVariant.DoesNotExist:
            continue

        GameVariantLimit.objects.get_or_create(
            store=old.store,
            variant=variant,
            defaults={
                "max_offers": old.max_offers,
                "stock_reserve": old.stock_reserve,
            },
        )


def forward(apps, schema_editor):
    seed_variants(apps, schema_editor)
    migrate_subplatform_limits(apps, schema_editor)


def reverse(apps, schema_editor):
    apps.get_model("posting", "GameVariantLimit").objects.all().delete()
    apps.get_model("posting", "GameVariantMapping").objects.all().delete()
    apps.get_model("posting", "GameVariant").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("posting", "0009_alter_cosmeticlist_id_alter_cosmeticlist_is_active_and_more"),
        ("inventory", "0001_initial"),
        ("integrations", "0001_initial"),
    ]

    operations = [
        # 1. Create GameVariant
        migrations.CreateModel(
            name="GameVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("platform", "Platform"), ("region", "Region")], max_length=20)),
                ("slug", models.CharField(help_text="Internal key: pc, psn, na, euw, etc.", max_length=30)),
                ("label", models.CharField(help_text="Display name: PC, PlayStation, North America", max_length=60)),
                ("source_key", models.CharField(blank=True, help_text="Account field value for lookup. Empty = use slug.", max_length=60)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="variants", to="inventory.game")),
            ],
            options={
                "db_table": "game_variants",
                "ordering": ["game", "type", "sort_order"],
                "unique_together": {("game", "type", "slug")},
            },
        ),
        # 2. Create GameVariantMapping
        migrations.CreateModel(
            name="GameVariantMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("marketplace", models.CharField(choices=[("eldorado", "Eldorado"), ("gameboost", "GameBoost"), ("playerauctions", "PlayerAuctions")], max_length=20)),
                ("external_id", models.CharField(help_text='Marketplace-specific ID: "0", "9874", "1-0"', max_length=30)),
                ("external_name", models.CharField(blank=True, help_text="Optional display name on the marketplace", max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("variant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mappings", to="posting.gamevariant")),
            ],
            options={
                "db_table": "game_variant_mappings",
                "unique_together": {("variant", "marketplace")},
            },
        ),
        # 3. Create GameVariantLimit
        migrations.CreateModel(
            name="GameVariantLimit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("max_offers", models.PositiveIntegerField(help_text="Maximum offers allowed for this variant")),
                ("stock_reserve", models.PositiveIntegerField(default=0, help_text="Slots reserved for stock (dropship cannot use these)")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="variant_limits", to="integrations.integrationaccount")),
                ("variant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="limits", to="posting.gamevariant")),
            ],
            options={
                "db_table": "game_variant_limits",
                "unique_together": {("store", "variant")},
            },
        ),
        # 4. CheckConstraint: stock_reserve <= max_offers
        migrations.AddConstraint(
            model_name="GameVariantLimit",
            constraint=models.CheckConstraint(
                condition=models.Q(stock_reserve__lte=models.F("max_offers")),
                name="stock_reserve_lte_max_offers",
            ),
        ),
        # 5. Seed data + migrate SubplatformLimit → GameVariantLimit
        migrations.RunPython(forward, reverse),
    ]

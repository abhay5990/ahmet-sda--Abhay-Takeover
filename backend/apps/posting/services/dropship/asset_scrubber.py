"""Dropship asset scrubber — reduces source item data by 5-10% to prevent fingerprinting.

Modifies a deep copy of the ``sources`` dict before it enters the payload pipeline.
Only called from the dropship poster; never used for stock posting.

Enable / disable:
    Set SCRUB_ENABLED = False to turn off the feature entirely.
    When disabled, ``scrub_sources`` returns the original dict unchanged.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import random
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature flag — flip to False to disable globally
# ---------------------------------------------------------------------------

SCRUB_ENABLED = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrub_sources(sources: dict, game_slug: str) -> dict:
    """Return a scrubbed deep-copy of *sources* for *game_slug*.

    * Always operates on a deep copy — the original ``sources`` dict is never mutated.
    * No-op (returns original) when SCRUB_ENABLED is False or game_slug is not handled.
    * On unexpected errors the original is returned and a warning is logged.
    """
    if not SCRUB_ENABLED:
        return sources

    handler = _HANDLERS.get(game_slug)
    if handler is None:
        return sources

    try:
        sources_copy = copy.deepcopy(sources)
        rate = _scrub_rate()
        handler(sources_copy, rate)
        return sources_copy
    except Exception:
        logger.warning(
            "Asset scrubber failed for game '%s', returning original sources",
            game_slug,
            exc_info=True,
        )
        return sources


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _scrub_rate() -> float:
    """Random scrub rate: 5–10 %."""
    return random.uniform(0.05, 0.10)


def _reduce_int(value: Any, rate: float) -> int:
    """Floor-reduce an integer field by *rate*. Returns 0 on bad input."""
    try:
        v = int(value)
        return max(0, math.floor(v * (1.0 - rate)))
    except (TypeError, ValueError):
        return 0


def _reduce_float(value: Any, rate: float) -> float:
    """Reduce a float field by *rate*, rounded to 2 decimal places."""
    try:
        v = float(value)
        return max(0.0, round(v * (1.0 - rate), 2))
    except (TypeError, ValueError):
        return 0.0


def _trim_list(lst: list, rate: float) -> list:
    """Remove the last ⌊len×rate⌋ items. At least one item is kept."""
    if not lst:
        return lst
    remove = math.floor(len(lst) * rate)
    keep = max(1, len(lst) - remove)
    return lst[:keep]


def _trim_dict(d: dict, rate: float) -> dict:
    """Remove the last ⌊len×rate⌋ entries. At least one entry is kept."""
    if not d:
        return d
    items = list(d.items())
    remove = math.floor(len(items) * rate)
    keep = max(1, len(items) - remove)
    return dict(items[:keep])


# ---------------------------------------------------------------------------
# Valorant
# ---------------------------------------------------------------------------

def _scrub_valorant(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Lists  : valorantInventory.WeaponSkins → riot_valorant_skin_count (sync)
               valorantInventory.Agent       → riot_valorant_agent_count (sync)
               valorantInventory.Buddy       → no count field, trim only
      Numeric: riot_valorant_level, riot_valorant_wallet_vp, riot_valorant_wallet_rp,
               riot_valorant_inventory_value, riot_valorant_knife_count
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    inventory = lzt.get('valorantInventory')
    if isinstance(inventory, dict):
        # WeaponSkins
        weapon_skins = inventory.get('WeaponSkins')
        if isinstance(weapon_skins, list):
            trimmed = _trim_list(weapon_skins, rate)
            inventory['WeaponSkins'] = trimmed
            lzt['riot_valorant_skin_count'] = len(trimmed)
        elif isinstance(weapon_skins, dict):
            trimmed = _trim_dict(weapon_skins, rate)
            inventory['WeaponSkins'] = trimmed
            lzt['riot_valorant_skin_count'] = len(trimmed)

        # Agent
        agents = inventory.get('Agent')
        if isinstance(agents, list):
            trimmed = _trim_list(agents, rate)
            inventory['Agent'] = trimmed
            lzt['riot_valorant_agent_count'] = len(trimmed)
        elif isinstance(agents, dict):
            trimmed = _trim_dict(agents, rate)
            inventory['Agent'] = trimmed
            lzt['riot_valorant_agent_count'] = len(trimmed)

        # Buddy (no listing count field — trim for consistency)
        buddies = inventory.get('Buddy')
        if isinstance(buddies, list):
            inventory['Buddy'] = _trim_list(buddies, rate)
        elif isinstance(buddies, dict):
            inventory['Buddy'] = _trim_dict(buddies, rate)

    for field in (
        'riot_valorant_level',
        'riot_valorant_wallet_vp',
        'riot_valorant_wallet_rp',
        'riot_valorant_inventory_value',
        'riot_valorant_knife_count',
    ):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Fortnite
# ---------------------------------------------------------------------------

# Rarity rank: higher = more valuable. Sort desc → most valuable first → trim tail.
_FN_RARITY_RANK: dict[str, int] = {
    'common': 0, 'uncommon': 1, 'rare': 2,
    'epic': 3, 'legendary': 4, 'superrare': 5, 'exclusive': 6,
}

# list_key → (generic_count_field, shop_count_field, shop_cost_field)
_FN_COSMETIC_MAP: dict[str, tuple[str | None, str | None, str | None]] = {
    'fortniteSkins':   ('fortnite_skin_count',    'fortnite_shop_skins_count',    'fortnite_shop_skins_cost'),
    'fortnitePickaxe': (None,                     'fortnite_shop_pickaxes_count', 'fortnite_shop_pickaxes_cost'),
    'fortniteDance':   (None,                     'fortnite_shop_dances_count',   'fortnite_shop_dances_cost'),
    'fortniteGliders': (None,                     'fortnite_shop_gliders_count',  'fortnite_shop_gliders_cost'),
}


def _scrub_fortnite(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Lists  : fortniteSkins   — sorted by rarity desc before trimming tail
                                 → fortnite_skin_count, fortnite_shop_skins_count,
                                   fortnite_shop_skins_cost (all synced)
               fortnitePickaxe → fortnite_shop_pickaxes_count, fortnite_shop_pickaxes_cost
               fortniteDance   → fortnite_shop_dances_count, fortnite_shop_dances_cost
               fortniteGliders → fortnite_shop_gliders_count, fortnite_shop_gliders_cost
      Numeric: fortnite_level, fortnite_balance
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    for list_key, (count_field, shop_count_field, shop_cost_field) in _FN_COSMETIC_MAP.items():
        items = lzt.get(list_key)
        if not isinstance(items, list) or not items:
            continue

        # For outfit skins: sort most-valuable-first so trimming the tail removes cheapest
        if list_key == 'fortniteSkins':
            sorted_items = sorted(
                items,
                key=lambda x: _FN_RARITY_RANK.get(
                    str(x.get('rarity', 'common')).lower(), 0
                ) if isinstance(x, dict) else 0,
                reverse=True,
            )
        else:
            sorted_items = items

        trimmed = _trim_list(sorted_items, rate)
        lzt[list_key] = trimmed

        if count_field is not None:
            lzt[count_field] = len(trimmed)

        if shop_count_field is not None:
            shop_items = [x for x in trimmed if isinstance(x, dict) and x.get('from_shop')]
            lzt[shop_count_field] = len(shop_items)

        if shop_cost_field is not None:
            lzt[shop_cost_field] = sum(
                int(x.get('shop_price') or 0)
                for x in trimmed
                if isinstance(x, dict) and x.get('from_shop')
            )

    # Flat numeric
    for field in ('fortnite_level', 'fortnite_balance'):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Rainbow Six Siege
# ---------------------------------------------------------------------------

def _scrub_r6(sources: dict, rate: float) -> None:
    _scrub_r6_lzt(sources.get('lzt'), rate)
    _scrub_r6_tracker(sources.get('tracker'), rate)


def _scrub_r6_lzt(lzt: Any, rate: float) -> None:
    """
    LZT fields:
      Lists  : uplay_r6_skins     (list or JSON string) → uplay_r6_skins_count (sync)
               uplay_r6_operators (list or JSON string) → uplay_r6_operators_count (sync)
      Numeric: uplay_r6_level
    """
    if not isinstance(lzt, dict):
        return

    # uplay_r6_skins — list or JSON-encoded list
    skins = lzt.get('uplay_r6_skins')
    if isinstance(skins, list) and skins:
        trimmed = _trim_list(skins, rate)
        lzt['uplay_r6_skins'] = trimmed
        lzt['uplay_r6_skins_count'] = len(trimmed)
    elif isinstance(skins, str) and skins.strip():
        try:
            parsed = json.loads(skins)
            if isinstance(parsed, list) and parsed:
                trimmed = _trim_list(parsed, rate)
                lzt['uplay_r6_skins'] = json.dumps(trimmed)
                lzt['uplay_r6_skins_count'] = len(trimmed)
        except (json.JSONDecodeError, ValueError):
            pass

    # uplay_r6_operators — list or JSON-encoded list
    operators = lzt.get('uplay_r6_operators')
    if isinstance(operators, list) and operators:
        trimmed = _trim_list(operators, rate)
        lzt['uplay_r6_operators'] = trimmed
        lzt['uplay_r6_operators_count'] = len(trimmed)
    elif isinstance(operators, str) and operators.strip():
        try:
            parsed = json.loads(operators)
            if isinstance(parsed, list) and parsed:
                trimmed = _trim_list(parsed, rate)
                lzt['uplay_r6_operators'] = json.dumps(trimmed)
                lzt['uplay_r6_operators_count'] = len(trimmed)
        except (json.JSONDecodeError, ValueError):
            pass

    if lzt.get('uplay_r6_level') is not None:
        lzt['uplay_r6_level'] = _reduce_int(lzt['uplay_r6_level'], rate)


def _scrub_r6_tracker(tracker: Any, rate: float) -> None:
    """
    Tracker fields:
      Dict-of-lists: inventory.{category} — each category list trimmed from tail
      Numeric      : level, marketplaceValue / marketplace_value
      Currency dict: currency.renown, currency.credits
    """
    if not isinstance(tracker, dict):
        return

    inventory = tracker.get('inventory')
    if isinstance(inventory, dict):
        for category, items in inventory.items():
            if isinstance(items, list) and items:
                inventory[category] = _trim_list(items, rate)

    for field in ('level', 'marketplaceValue', 'marketplace_value'):
        if tracker.get(field) is not None:
            tracker[field] = _reduce_int(tracker[field], rate)

    currency = tracker.get('currency')
    if isinstance(currency, dict):
        for field in ('renown', 'credits'):
            if currency.get(field) is not None:
                currency[field] = _reduce_int(currency[field], rate)


# ---------------------------------------------------------------------------
# League of Legends
# ---------------------------------------------------------------------------

def _scrub_lol(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Lists  : lolInventory.Champion / Champions → riot_lol_champion_count (sync)
               lolInventory.Skin / Skins         → riot_lol_skin_count (sync)
      Numeric: riot_lol_level, riot_lol_wallet_blue, riot_lol_wallet_orange,
               riot_lol_wallet_mythic, riot_lol_wallet_riot
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    inventory = lzt.get('lolInventory')
    if isinstance(inventory, dict):
        for champ_key in ('Champion', 'Champions'):
            champs = inventory.get(champ_key)
            if isinstance(champs, list) and champs:
                trimmed = _trim_list(champs, rate)
                inventory[champ_key] = trimmed
                lzt['riot_lol_champion_count'] = len(trimmed)
                break

        for skin_key in ('Skin', 'Skins'):
            skins = inventory.get(skin_key)
            if isinstance(skins, list) and skins:
                trimmed = _trim_list(skins, rate)
                inventory[skin_key] = trimmed
                lzt['riot_lol_skin_count'] = len(trimmed)
                break

    for field in (
        'riot_lol_level',
        'riot_lol_wallet_blue',
        'riot_lol_wallet_orange',
        'riot_lol_wallet_mythic',
        'riot_lol_wallet_riot',
    ):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Brawl Stars
# ---------------------------------------------------------------------------

def _scrub_brawl_stars(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Dict   : supercellBrawlers → supercell_brawler_count,
                                   supercell_legendary_brawler_count (synced)
      Numeric: supercell_laser_level, supercell_laser_trophies
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    brawlers = lzt.get('supercellBrawlers')
    if isinstance(brawlers, dict) and brawlers:
        trimmed = _trim_dict(brawlers, rate)
        lzt['supercellBrawlers'] = trimmed
        lzt['supercell_brawler_count'] = len(trimmed)
        lzt['supercell_legendary_brawler_count'] = sum(
            1 for b in trimmed.values()
            if isinstance(b, dict) and str(b.get('class', '')).lower() == 'legendary'
        )

    for field in ('supercell_laser_level', 'supercell_laser_trophies'):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Clash of Clans
# ---------------------------------------------------------------------------

def _scrub_coc(sources: dict, rate: float) -> None:
    """
    LZT fields (all numeric):
      supercell_magic_level, supercell_magic_trophies,
      supercell_king_level, supercell_total_heroes_level,
      supercell_total_troops_level, supercell_total_spells_level,
      supercell_town_hall_level, supercell_builder_hall_level,
      supercell_total_builder_heroes_level, supercell_total_builder_troops_level
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    for field in (
        'supercell_magic_level',
        'supercell_magic_trophies',
        'supercell_king_level',
        'supercell_total_heroes_level',
        'supercell_total_troops_level',
        'supercell_total_spells_level',
        'supercell_town_hall_level',
        'supercell_builder_hall_level',
        'supercell_total_builder_heroes_level',
        'supercell_total_builder_troops_level',
    ):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Clash Royale
# ---------------------------------------------------------------------------

def _scrub_cr(sources: dict, rate: float) -> None:
    """
    LZT fields (numeric):
      supercell_scroll_level, supercell_scroll_trophies, supercell_scroll_victories

    Tracker fields:
      Dict   : profile.cardStats → profile.cardsFound (synced)
      Numeric: profile.bestSeasonTrophies, profile.bestSeasonHighestTrophies,
               profile.arena, profile.games, profile.losses
    """
    lzt = sources.get('lzt')
    if isinstance(lzt, dict):
        for field in (
            'supercell_scroll_level',
            'supercell_scroll_trophies',
            'supercell_scroll_victories',
        ):
            if lzt.get(field) is not None:
                lzt[field] = _reduce_int(lzt[field], rate)

    tracker = sources.get('tracker')
    if not isinstance(tracker, dict):
        return

    # profile can be nested or flat
    profile = tracker.get('profile') if isinstance(tracker.get('profile'), dict) else tracker

    card_stats = profile.get('cardStats')
    if isinstance(card_stats, dict) and card_stats:
        trimmed = _trim_dict(card_stats, rate)
        profile['cardStats'] = trimmed
        profile['cardsFound'] = len(trimmed)

    for field in ('bestSeasonTrophies', 'bestSeasonHighestTrophies', 'arena', 'games', 'losses'):
        if profile.get(field) is not None:
            profile[field] = _reduce_int(profile[field], rate)


# ---------------------------------------------------------------------------
# Genshin Impact / miHoYo
# (one pipeline slice handles Genshin, Honkai Star Rail, and Zenless Zone Zero)
# ---------------------------------------------------------------------------

def _scrub_genshin(sources: dict, rate: float) -> None:
    """
    LZT fields (all numeric — no list fields in any miHoYo slice):
      Genshin       : mihoyo_genshin_level, mihoyo_genshin_character_count,
                      mihoyo_genshin_legendary_characters_count, mihoyo_genshin_constellations_count,
                      mihoyo_genshin_legendary_weapons_count, mihoyo_genshin_achievement_count,
                      mihoyo_genshin_activity_days, mihoyo_genshin_currency
      Honkai SR     : mihoyo_honkai_level, mihoyo_honkai_character_count,
                      mihoyo_honkai_legendary_characters_count, mihoyo_honkai_eidolons_count,
                      mihoyo_honkai_legendary_weapons_count, mihoyo_honkai_achievement_count,
                      mihoyo_honkai_activity_days, mihoyo_honkai_currency
      Zenless ZZ    : mihoyo_zenless_level, mihoyo_zenless_character_count,
                      mihoyo_zenless_legendary_characters_count, mihoyo_zenless_cinemas_count,
                      mihoyo_zenless_achievement_count
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    for field in (
        'mihoyo_genshin_level',
        'mihoyo_genshin_character_count',
        'mihoyo_genshin_legendary_characters_count',
        'mihoyo_genshin_constellations_count',
        'mihoyo_genshin_legendary_weapons_count',
        'mihoyo_genshin_achievement_count',
        'mihoyo_genshin_activity_days',
        'mihoyo_genshin_currency',
        'mihoyo_honkai_level',
        'mihoyo_honkai_character_count',
        'mihoyo_honkai_legendary_characters_count',
        'mihoyo_honkai_eidolons_count',
        'mihoyo_honkai_legendary_weapons_count',
        'mihoyo_honkai_achievement_count',
        'mihoyo_honkai_activity_days',
        'mihoyo_honkai_currency',
        'mihoyo_zenless_level',
        'mihoyo_zenless_character_count',
        'mihoyo_zenless_legendary_characters_count',
        'mihoyo_zenless_cinemas_count',
        'mihoyo_zenless_achievement_count',
    ):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)


# ---------------------------------------------------------------------------
# Grand Theft Auto V
# ---------------------------------------------------------------------------

def _scrub_gtav(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Numeric (flat and inside offer_details): level, cash_amount, cars_count
      cash_amount is handled as float (may be fractional millions).
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    offer_details = lzt.get('offer_details')
    if isinstance(offer_details, dict):
        if offer_details.get('level') is not None:
            offer_details['level'] = _reduce_int(offer_details['level'], rate)
        if offer_details.get('cash_amount') is not None:
            offer_details['cash_amount'] = _reduce_float(offer_details['cash_amount'], rate)
        if offer_details.get('cars_count') is not None:
            offer_details['cars_count'] = _reduce_int(offer_details['cars_count'], rate)

    if lzt.get('level') is not None:
        lzt['level'] = _reduce_int(lzt['level'], rate)
    if lzt.get('cash_amount') is not None:
        lzt['cash_amount'] = _reduce_float(lzt['cash_amount'], rate)
    if lzt.get('cars_count') is not None:
        lzt['cars_count'] = _reduce_int(lzt['cars_count'], rate)


# ---------------------------------------------------------------------------
# Steam
# ---------------------------------------------------------------------------

def _scrub_steam(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Dict/List: steam_full_games.list — trim entries (no explicit count field;
                 SteamLztSourceAdapter derives total_games = len(games) dynamically)
      Numeric  : steam_level
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    full_games = lzt.get('steam_full_games')
    if isinstance(full_games, dict):
        games_list = full_games.get('list')
        if isinstance(games_list, dict) and games_list:
            full_games['list'] = _trim_dict(games_list, rate)
        elif isinstance(games_list, list) and games_list:
            full_games['list'] = _trim_list(games_list, rate)

    if lzt.get('steam_level') is not None:
        lzt['steam_level'] = _reduce_int(lzt['steam_level'], rate)


# ---------------------------------------------------------------------------
# Counter-Strike 2
# ---------------------------------------------------------------------------

def _scrub_cs2(sources: dict, rate: float) -> None:
    """
    LZT fields:
      List : medals            — trim tail (no count field to sync)
      Dict : steam_full_games.list — trim entries
      Numeric: hours_played
      NOTE: rank and premier_elo are intentionally NOT scrubbed —
            they are the primary value signals buyers rely on.
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    medals = lzt.get('medals')
    if isinstance(medals, list) and medals:
        lzt['medals'] = _trim_list(medals, rate)

    full_games = lzt.get('steam_full_games')
    if isinstance(full_games, dict):
        games_list = full_games.get('list')
        if isinstance(games_list, dict) and games_list:
            full_games['list'] = _trim_dict(games_list, rate)
        elif isinstance(games_list, list) and games_list:
            full_games['list'] = _trim_list(games_list, rate)

    if lzt.get('hours_played') is not None:
        lzt['hours_played'] = _reduce_int(lzt['hours_played'], rate)


# ---------------------------------------------------------------------------
# Roblox
# ---------------------------------------------------------------------------

def _scrub_roblox(sources: dict, rate: float) -> None:
    """
    LZT fields (all numeric — no list fields in Roblox slice):
      Integer: roblox_robux, roblox_offsale_count, roblox_followers,
               roblox_incoming_robux_total, roblox_game_pass_total_robux
      Float  : roblox_inventory_price, roblox_ugc_limited_price, roblox_limited_price
      NOTE: roblox_friends intentionally excluded (social metric, less relevant).
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    for field in (
        'roblox_robux',
        'roblox_offsale_count',
        'roblox_followers',
        'roblox_incoming_robux_total',
        'roblox_game_pass_total_robux',
    ):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_int(lzt[field], rate)

    for field in ('roblox_inventory_price', 'roblox_ugc_limited_price', 'roblox_limited_price'):
        if lzt.get(field) is not None:
            lzt[field] = _reduce_float(lzt[field], rate)


# ---------------------------------------------------------------------------
# Ubisoft Connect
# ---------------------------------------------------------------------------

def _scrub_ubisoft(sources: dict, rate: float) -> None:
    """
    LZT fields:
      Dict   : uplay_games → uplay_game_count (synced)
      Numeric: uplay_r6_level
      Float  : uplay_converted_balance
    """
    lzt = sources.get('lzt')
    if not isinstance(lzt, dict):
        return

    games = lzt.get('uplay_games')
    if isinstance(games, dict) and games:
        trimmed = _trim_dict(games, rate)
        lzt['uplay_games'] = trimmed
        lzt['uplay_game_count'] = len(trimmed)

    if lzt.get('uplay_r6_level') is not None:
        lzt['uplay_r6_level'] = _reduce_int(lzt['uplay_r6_level'], rate)

    if lzt.get('uplay_converted_balance') is not None:
        lzt['uplay_converted_balance'] = _reduce_float(lzt['uplay_converted_balance'], rate)


# ---------------------------------------------------------------------------
# Dispatch table — maps game_slug → handler
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    'valorant':           _scrub_valorant,
    'fortnite':           _scrub_fortnite,
    'rainbow-six-siege':  _scrub_r6,
    'league-of-legends':  _scrub_lol,
    'brawl-stars':        _scrub_brawl_stars,
    'clash-of-clans':     _scrub_coc,
    'clash-royale':       _scrub_cr,
    'genshin-impact':     _scrub_genshin,
    'grand-theft-auto-5': _scrub_gtav,
    'steam':              _scrub_steam,
    'counter-strike-2':   _scrub_cs2,
    'roblox':             _scrub_roblox,
    'ubisoft-connect':    _scrub_ubisoft,
}

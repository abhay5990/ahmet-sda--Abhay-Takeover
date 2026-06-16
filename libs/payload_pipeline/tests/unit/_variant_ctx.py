"""Variant context fixtures for pipeline tests.

Mirrors the seed data from migration 0010_game_variant_system.py.
Each function returns a marketplace-specific ``variant_context`` dict
ready to inject into ``BuildContext``.

Variant context shape::

    {
        "<variant_type>": {
            "<source_key_or_slug>": {
                "slug": "...",
                "external_id": "...",
                "external_name": "...",
            },
        },
    }
"""

from __future__ import annotations

from typing import Any


def _entry(slug: str, ext_id: str, ext_name: str = "") -> dict[str, str]:
    return {"slug": slug, "external_id": ext_id, "external_name": ext_name}


# ── Valorant ──────────────────────────────────────────────────────

def valorant_eldorado() -> dict[str, Any]:
    return {
        "region": {
            "NA": _entry("na", "0"),
            "EU": _entry("eu", "1"),
            "LA": _entry("la", "2"),
            "BR": _entry("br", "3"),
            "AP": _entry("ap", "5"),
            "KR": _entry("kr", "6"),
        },
        "platform": {
            "pc": _entry("pc", "0"),
            "psn": _entry("psn", "1"),
            "xbox": _entry("xbox", "2"),
        },
    }


def valorant_playerauctions() -> dict[str, Any]:
    return {
        "region": {
            "NA": _entry("na", "9089", "NA"),
            "EU": _entry("eu", "9128", "EU"),
            "LA": _entry("la", "9207", "LATAM"),
            "BR": _entry("br", "9208", "BR"),
            "AP": _entry("ap", "9309", "APAC"),
            "KR": _entry("kr", "9206", "KR"),
            "TR": _entry("tr", "14995", "TR"),
        },
    }


def valorant_gameboost() -> dict[str, Any]:
    return {
        "region": {
            "NA": _entry("na", "North America", ""),
            "EU": _entry("eu", "Europe", ""),
            "LA": _entry("la", "Latin America", ""),
            "BR": _entry("br", "Brazil", ""),
            "AP": _entry("ap", "Asia Pacific", ""),
            "KR": _entry("kr", "Asia Pacific", ""),  # KR maps to Asia Pacific on GB
        },
    }


# ── Genshin Impact ────────────────────────────────────────────────

def genshin_eldorado() -> dict[str, Any]:
    return {
        "region": {
            "na": _entry("na", "0"),
            "eu": _entry("eu", "1"),
            "asia": _entry("asia", "2"),
            "tw": _entry("tw", "3"),
        },
    }


def genshin_playerauctions() -> dict[str, Any]:
    return {
        "region": {
            "na": _entry("na", "9335", "America"),
            "eu": _entry("eu", "9336", "Europe"),
            "asia": _entry("asia", "9337", "Asia"),
            "tw": _entry("tw", "10104", "TW/HK/MO"),
        },
    }


def genshin_gameboost() -> dict[str, Any]:
    return {
        "region": {
            "na": _entry("na", "America", ""),
            "eu": _entry("eu", "Europe", ""),
            "asia": _entry("asia", "Asia", ""),
            "tw": _entry("tw", "TW/HK/MO", ""),
        },
    }


# ── League of Legends ─────────────────────────────────────────────

def lol_eldorado() -> dict[str, Any]:
    return {
        "region": {
            "Brazil": _entry("brazil", "0"),
            "Europe Nordic & East": _entry("eune", "1"),
            "Europe West": _entry("euw", "2"),
            "Latin America North": _entry("lan", "3"),
            "Latin America South": _entry("las", "4"),
            "Oceania": _entry("oce", "5"),
            "Russia": _entry("ru", "6"),
            "Turkey": _entry("tr", "7"),
            "Japan": _entry("jp", "8"),
            "North America": _entry("na", "9"),
            "Philippines": _entry("ph", "13"),
            "Singapore, Malaysia & Indonesia": _entry("sg", "12"),
            "Thailand": _entry("th", "15"),
            "Vietnam": _entry("vn", "14"),
        },
    }


def lol_playerauctions() -> dict[str, Any]:
    return {
        "region": {
            "Brazil": _entry("brazil", "6001", "Brazil"),
            "Europe Nordic & East": _entry("eune", "4144", "EU Nordic and East"),
            "Europe West": _entry("euw", "4143", "EU West"),
            "Latin America North": _entry("lan", "5772", "Latin America North"),
            "Latin America South": _entry("las", "5773", "Latin America South"),
            "Oceania": _entry("oce", "5769", "Oceania"),
            "Russia": _entry("ru", "5771", "Russia"),
            "Turkey": _entry("tr", "5770", "Turkey"),
            "Japan": _entry("jp", "8928", "Japan"),
            "North America": _entry("na", "3638", "North America"),
            "Philippines": _entry("ph", "9496", "Southeast Asia"),
            "Singapore, Malaysia & Indonesia": _entry("sg", "9496", "Southeast Asia"),
            "Thailand": _entry("th", "9496", "Southeast Asia"),
            "Vietnam": _entry("vn", "9496", "Southeast Asia"),
            "Middle East": _entry("me", "13870", "Middle East"),
            "PBE": _entry("pbe", "8605", "PBE"),
        },
    }


def lol_gameboost() -> dict[str, Any]:
    return {
        "region": {
            "Brazil": _entry("brazil", "Brazil", ""),
            "Europe Nordic & East": _entry("eune", "Europe Nordic & East", ""),
            "Europe West": _entry("euw", "Europe West", ""),
            "Latin America North": _entry("lan", "Latin America North", ""),
            "Latin America South": _entry("las", "Latin America South", ""),
            "Oceania": _entry("oce", "Oceania", ""),
            "Russia": _entry("ru", "Russia", ""),
            "Turkey": _entry("tr", "Turkey", ""),
            "Japan": _entry("jp", "Japan", ""),
            "North America": _entry("na", "North America", ""),
            "Philippines": _entry("ph", "Philippines", ""),
            "Singapore, Malaysia & Indonesia": _entry("sg", "Singapore", ""),
            "Thailand": _entry("th", "Thailand", ""),
            "Vietnam": _entry("vn", "Vietnam", ""),
        },
    }


# ── GTA V ─────────────────────────────────────────────────────────

def gtav_eldorado() -> dict[str, Any]:
    return {
        "platform": {
            "PC - Legacy": _entry("pc-legacy", "0"),
            "PC - Enhanced": _entry("pc-enhanced", "5"),
            "PlayStation 4": _entry("ps4", "1"),
            "PlayStation 5": _entry("ps5", "3"),
            "Xbox One": _entry("xbox-one", "2"),
            "Xbox Series X/S": _entry("xbox-series", "4"),
        },
    }


def gtav_playerauctions() -> dict[str, Any]:
    return {
        "platform": {
            "PC - Legacy": _entry("pc-legacy", "5920", "PC-Steam-Legacy"),
            "PC - Enhanced": _entry("pc-enhanced", "14270", "PC-Steam-Enhanced"),
            "PlayStation 4": _entry("ps4", "5921", "PS4"),
            "PlayStation 5": _entry("ps5", "9874", "PS5"),
            "Xbox One": _entry("xbox-one", "5922", "XBOX ONE"),
            "Xbox Series X/S": _entry("xbox-series", "9889", "Xbox Series"),
        },
    }


def gtav_gameboost() -> dict[str, Any]:
    return {
        "platform": {
            "PC - Legacy": _entry("pc-legacy", "PC \u00b7 Legacy", ""),
            "PC - Enhanced": _entry("pc-enhanced", "PC \u00b7 Enhanced", ""),
        },
    }


# ── Fortnite ──────────────────────────────────────────────────────

def fortnite_eldorado() -> dict[str, Any]:
    return {
        "platform": {
            "pc": _entry("pc", "0"),
            "psn": _entry("psn", "1"),
            "xbox": _entry("xbox", "2"),
            "android": _entry("android", "3"),
            "ios": _entry("ios", "4"),
            "switch": _entry("switch", "5"),
        },
    }


def fortnite_playerauctions() -> dict[str, Any]:
    return {
        "platform": {
            "pc": _entry("pc", "7877", "PC"),
            "psn": _entry("psn", "7878", "PlayStation"),
            "xbox": _entry("xbox", "7879", "Xbox"),
            "android": _entry("android", "8173", "Android"),
            "ios": _entry("ios", "8172", "IOS"),
            "switch": _entry("switch", "8321", "Switch"),
        },
    }


# ── Rainbow Six Siege ─────────────────────────────────────────────

def r6_eldorado() -> dict[str, Any]:
    return {
        "platform": {
            "pc": _entry("pc", "0"),
            "psn": _entry("psn", "1"),
            "xbox": _entry("xbox", "2"),
        },
    }


def r6_playerauctions() -> dict[str, Any]:
    return {
        "platform": {
            "pc": _entry("pc", "7774", "PC"),
            "psn": _entry("psn", "7775", "PlayStation"),
            "xbox": _entry("xbox", "7776", "Xbox"),
        },
    }


# ── Forza Horizon 5 ───────────────────────────────────────────────

def fh5_eldorado() -> dict[str, Any]:
    """Platform → tradeEnvironmentId (0=PC, 1=Xbox, 2=PS5)."""
    return {
        "platform": {
            "PC": _entry("pc", "0"),
            "Xbox": _entry("xbox", "1"),
            "PS5": _entry("ps5", "2"),
        },
    }


def fh5_playerauctions() -> dict[str, Any]:
    """Platform → PA server ID (10636=PC, 10637=Xbox, 14295=PS)."""
    return {
        "platform": {
            "PC": _entry("pc", "10636", "PC"),
            "Xbox": _entry("xbox", "10637", "Xbox"),
            "PS5": _entry("ps5", "14295", "PS"),
        },
    }


def fh5_gameboost() -> dict[str, Any]:
    """Platform → GB platform string."""
    return {
        "platform": {
            "PC": _entry("pc", "PC", ""),
            "Xbox": _entry("xbox", "Xbox", ""),
            "PS5": _entry("ps5", "PS5", ""),
        },
    }


# ── New World ─────────────────────────────────────────────────────

def nw_eldorado() -> dict[str, Any]:
    """Region → tradeEnvironmentId (0=US-East … 4=EU-Central)."""
    return {
        "region": {
            "US-East": _entry("us-east", "0"),
            "US-West": _entry("us-west", "1"),
            "AP Southeast": _entry("ap-southeast", "2"),
            "SA East": _entry("sa-east", "3"),
            "EU-Central": _entry("eu-central", "4"),
        },
    }


def nw_playerauctions() -> dict[str, Any]:
    """Region → PA server ID."""
    return {
        "region": {
            "US-East": _entry("us-east", "9920", "US East"),
            "US-West": _entry("us-west", "9916", "US West"),
            "AP Southeast": _entry("ap-southeast", "9917", "AP Southeast"),
            "SA East": _entry("sa-east", "9918", "SA East"),
            "EU-Central": _entry("eu-central", "9919", "EU Central"),
        },
    }


# ── Rust ──────────────────────────────────────────────────────────

def rust_eldorado() -> dict[str, Any]:
    """Platform → tradeEnvironmentId (0=PC, 1=PlayStation, 2=Xbox)."""
    return {
        "platform": {
            "PC": _entry("pc", "0"),
            "PlayStation": _entry("playstation", "1"),
            "Xbox": _entry("xbox", "2"),
        },
    }


def rust_gameboost() -> dict[str, Any]:
    """Platform → GB platform string."""
    return {
        "platform": {
            "PC": _entry("pc", "PC", ""),
            "PlayStation": _entry("playstation", "PlayStation", ""),
            "Xbox": _entry("xbox", "Xbox", ""),
        },
    }

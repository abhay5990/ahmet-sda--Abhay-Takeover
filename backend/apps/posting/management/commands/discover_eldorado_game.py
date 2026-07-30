"""Discover / verify an Eldorado game's account schema (read-only by default).

Eldorado exposes account offers on the PUBLIC, unauthenticated endpoint
``GET /api/flexibleOffers?gameId=<id>&category=Account`` (never touches our
seller account). This command samples N pages and reports, with frequency
counts across the sample:

- ``gameSeoAlias`` (the authoritative game+family identifier),
- ``tradeEnvironmentValues`` (dimension / option / id),
- per-game Select ``attributes`` (id / label / observed values).

Frequency counts are what distinguish "this game genuinely has no attributes"
from "my small sample happened to miss them".

It groups everything by each offer's OWN returned ``category`` (never the
request param — Eldorado validates the game+category combo but does not
reliably filter results).

Reverse lookup: ``--resolve-alias <seo-alias>`` fetches the public listing page
for a known alias (e.g. ``red-dead-redemption-2-accounts``) and extracts the
embedded ``gameId`` — the correct way to resolve an unknown id (e.g. RDR2)
instead of sweeping/guessing.

``--commit`` upserts the ``GamePlatformMapping`` for a game, but ONLY after the
discovered ``gameSeoAlias`` matches the expected alias (guards against writing
a wrong id). The alias is stored in ``external_name``.

Examples::

    # Read-only discovery of Rust (gameId 37), 5 pages
    python manage.py discover_eldorado_game --game-id 37 --pages 5

    # Resolve an unknown gameId from its seo alias (e.g. RDR2)
    python manage.py discover_eldorado_game --resolve-alias red-dead-redemption-2-accounts

    # Verify + persist the mapping for Rust
    python manage.py discover_eldorado_game --game-id 37 --commit \
        --game-slug rust --expected-alias rust-accounts
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from typing import Any

from django.core.management.base import BaseCommand, CommandError

_API_URL = "https://www.eldorado.gg/api/flexibleOffers"
_PAGE_URL = "https://www.eldorado.gg/{alias}"
_DEFAULT_DELAY = 3.5  # Eldorado rate-limits ~290 rapid calls -> HTTP 429.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ── HTTP layer (isolated + patchable for tests) ──────────────────────────────


def _http_get(url: str, params: dict | None = None, *, timeout: int = 30):
    """GET with a browser impersonation to survive Cloudflare. Unauthenticated."""
    from curl_cffi import requests as cffi_requests

    return cffi_requests.get(
        url, params=params, timeout=timeout,
        impersonate="chrome", headers={"User-Agent": _UA},
    )


def fetch_offers_page(game_id: int, page: int, page_size: int) -> tuple[int, list[dict]]:
    """Fetch one page of account offers. Returns (http_status, offers)."""
    resp = _http_get(
        _API_URL,
        params={
            "gameId": game_id,
            "category": "Account",
            "page": page,
            "pageSize": page_size,
        },
    )
    status = getattr(resp, "status_code", 0)
    if status != 200:
        return status, []
    try:
        data = resp.json()
    except Exception:
        return status, []
    return status, _extract_offers(data)


def fetch_listing_page_html(alias: str) -> str:
    """Fetch the public listing page HTML for a seo alias (reverse lookup)."""
    resp = _http_get(_PAGE_URL.format(alias=alias))
    if getattr(resp, "status_code", 0) != 200:
        return ""
    return getattr(resp, "text", "") or ""


# ── Parsing helpers ──────────────────────────────────────────────────────────


def _extract_offers(data: Any) -> list[dict]:
    """Pull the offers array out of the (loosely-typed) API envelope."""
    if isinstance(data, list):
        return [o for o in data if isinstance(o, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "offers", "items", "content"):
            value = data.get(key)
            if isinstance(value, list):
                return [o for o in value if isinstance(o, dict)]
    return []


def _resolve_game_id_from_html(html: str, alias: str) -> int | None:
    """Extract an embedded gameId from a listing page's HTML.

    Prefers a gameId that co-occurs near the alias; falls back to the most
    common gameId on the page.
    """
    if not html:
        return None
    # Prefer a gameId appearing close to the alias string in the embedded JSON.
    alias_idx = html.find(alias)
    if alias_idx != -1:
        window = html[max(0, alias_idx - 400): alias_idx + 400]
        near = re.findall(r'"gameId"\s*:\s*"?(\d+)"?', window)
        if near:
            return int(Counter(near).most_common(1)[0][0])
    all_ids = re.findall(r'"gameId"\s*:\s*"?(\d+)"?', html)
    if all_ids:
        return int(Counter(all_ids).most_common(1)[0][0])
    return None


class _Aggregate:
    """Frequency accumulator across sampled offers, grouped by returned category."""

    def __init__(self) -> None:
        self.offers = 0
        self.alias_by_category: dict[str, Counter] = defaultdict(Counter)
        self.trade_env_by_category: dict[str, Counter] = defaultdict(Counter)
        # category -> attr_id -> {"label": str, "values": Counter}
        self.attrs_by_category: dict[str, dict[str, dict]] = defaultdict(dict)

    def add(self, offer: dict) -> None:
        self.offers += 1
        category = str(offer.get("category") or "Unknown")
        alias = str(offer.get("gameSeoAlias") or "")
        if alias:
            self.alias_by_category[category][alias] += 1

        for te in offer.get("tradeEnvironmentValues") or []:
            if not isinstance(te, dict):
                continue
            key = (
                str(te.get("name") or ""),
                str(te.get("value") or ""),
                str(te.get("id") or ""),
            )
            self.trade_env_by_category[category][key] += 1

        for attr in offer.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            attr_id = str(attr.get("id") or "")
            if not attr_id:
                continue
            slot = self.attrs_by_category[category].setdefault(
                attr_id, {"label": str(attr.get("name") or ""), "values": Counter()},
            )
            value_obj = attr.get("value") or {}
            if isinstance(value_obj, dict):
                v = (str(value_obj.get("id") or ""), str(value_obj.get("name") or ""))
            else:
                v = (str(value_obj), "")
            slot["values"][v] += 1

    def dominant_alias(self) -> str:
        combined: Counter = Counter()
        for counter in self.alias_by_category.values():
            combined.update(counter)
        return combined.most_common(1)[0][0] if combined else ""

    def to_dict(self) -> dict:
        return {
            "offers_sampled": self.offers,
            "dominant_alias": self.dominant_alias(),
            "categories": {
                category: {
                    "aliases": dict(self.alias_by_category.get(category, {})),
                    "trade_environments": {
                        "|".join(k): n
                        for k, n in self.trade_env_by_category.get(category, {}).items()
                    },
                    "attributes": {
                        attr_id: {
                            "label": slot["label"],
                            "values": {
                                (vid or vname): n
                                for (vid, vname), n in slot["values"].items()
                            },
                        }
                        for attr_id, slot in self.attrs_by_category.get(category, {}).items()
                    },
                }
                for category in sorted(
                    set(self.alias_by_category)
                    | set(self.trade_env_by_category)
                    | set(self.attrs_by_category)
                )
            },
        }


class Command(BaseCommand):
    help = "Discover/verify an Eldorado game's account schema (read-only by default)."

    def add_arguments(self, parser):
        parser.add_argument("--game-id", type=int, default=None)
        parser.add_argument(
            "--resolve-alias", default=None,
            help="Reverse lookup: extract the gameId for this gameSeoAlias.",
        )
        parser.add_argument("--pages", type=int, default=5)
        parser.add_argument("--page-size", type=int, default=50)
        parser.add_argument(
            "--delay", type=float, default=_DEFAULT_DELAY,
            help="Seconds between page requests (>=3 recommended; Eldorado 429s).",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Upsert GamePlatformMapping (requires --game-slug and --expected-alias).",
        )
        parser.add_argument("--game-slug", default=None)
        parser.add_argument("--expected-alias", default=None)
        parser.add_argument(
            "--json", action="store_true", dest="as_json",
            help="Emit the machine-readable JSON summary only.",
        )

    def handle(self, *args, **options):
        if options["resolve_alias"]:
            self._handle_resolve(options["resolve_alias"], as_json=options["as_json"])
            return

        game_id = options["game_id"]
        if game_id is None:
            raise CommandError("Provide --game-id (discovery) or --resolve-alias (reverse lookup).")

        if options["commit"] and not (options["game_slug"] and options["expected_alias"]):
            raise CommandError("--commit requires both --game-slug and --expected-alias.")

        agg = self._discover(
            game_id,
            pages=max(1, options["pages"]),
            page_size=options["page_size"],
            delay=max(0.0, options["delay"]),
        )
        summary = agg.to_dict()

        if options["as_json"]:
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))
        else:
            self._print_summary(game_id, summary)

        if options["commit"]:
            self._commit(
                game_id=game_id,
                summary=summary,
                game_slug=options["game_slug"],
                expected_alias=options["expected_alias"],
            )

    # ── modes ────────────────────────────────────────────────────────────────

    def _discover(self, game_id: int, *, pages: int, page_size: int, delay: float) -> _Aggregate:
        agg = _Aggregate()
        for page in range(1, pages + 1):
            if page > 1 and delay:
                time.sleep(delay)
            status, offers = fetch_offers_page(game_id, page, page_size)
            if status == 429:
                self.stderr.write(self.style.WARNING(
                    f"Rate limited (429) on page {page}; stopping. Increase --delay.",
                ))
                break
            if status != 200:
                self.stderr.write(self.style.WARNING(
                    f"page {page}: HTTP {status}; stopping.",
                ))
                break
            if not offers:
                break
            for offer in offers:
                agg.add(offer)
        return agg

    def _handle_resolve(self, alias: str, *, as_json: bool) -> None:
        html = fetch_listing_page_html(alias)
        game_id = _resolve_game_id_from_html(html, alias)
        if as_json:
            self.stdout.write(json.dumps({"alias": alias, "game_id": game_id}))
            return
        if game_id is None:
            self.stdout.write(self.style.WARNING(
                f"Could not extract a gameId for alias '{alias}'. "
                f"The page layout may have changed or the alias is wrong.",
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"alias '{alias}' -> gameId {game_id}",
        ))
        self.stdout.write(
            "Verify it: python manage.py discover_eldorado_game "
            f"--game-id {game_id}",
        )

    def _commit(self, *, game_id: int, summary: dict, game_slug: str, expected_alias: str) -> None:
        from apps.inventory.models import Game, GamePlatformMapping

        discovered = summary.get("dominant_alias") or ""
        if discovered != expected_alias:
            raise CommandError(
                f"Refusing to commit: discovered alias '{discovered}' != "
                f"expected '{expected_alias}' for gameId {game_id}.",
            )
        try:
            game = Game.objects.get(slug=game_slug)
        except Game.DoesNotExist as exc:
            raise CommandError(f"No Game with slug '{game_slug}'.") from exc

        mapping, created = GamePlatformMapping.objects.update_or_create(
            platform="eldorado",
            external_id=str(game_id),
            defaults={"game": game, "external_name": expected_alias},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} GamePlatformMapping: {game.slug} -> eldorado:{game_id} "
            f"({expected_alias})",
        ))

    # ── output ────────────────────────────────────────────────────────────────

    def _print_summary(self, game_id: int, summary: dict) -> None:
        self.stdout.write(f"gameId {game_id}: sampled {summary['offers_sampled']} offer(s)")
        self.stdout.write(f"dominant gameSeoAlias: {summary['dominant_alias'] or '(none)'}")
        for category, block in summary["categories"].items():
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(f"category={category}"))
            aliases = block["aliases"]
            if aliases:
                self.stdout.write("  aliases: " + ", ".join(
                    f"{a} x{n}" for a, n in sorted(aliases.items(), key=lambda kv: -kv[1])
                ))
            trade = block["trade_environments"]
            if trade:
                self.stdout.write("  tradeEnvironment (name|value|id x count):")
                for k, n in sorted(trade.items(), key=lambda kv: -kv[1]):
                    self.stdout.write(f"    {k} x{n}")
            else:
                self.stdout.write("  tradeEnvironment: none observed")
            attrs = block["attributes"]
            if attrs:
                self.stdout.write("  attributes (id / label -> values x count):")
                for attr_id, info in attrs.items():
                    vals = ", ".join(
                        f"{v} x{n}" for v, n in sorted(info["values"].items(), key=lambda kv: -kv[1])
                    )
                    self.stdout.write(f"    {attr_id} ({info['label']}): {vals}")
            else:
                self.stdout.write("  attributes: none observed")

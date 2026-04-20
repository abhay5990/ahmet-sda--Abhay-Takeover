# R6 Source Example Notes

Reference payloads:

- [_example_data_for_payload_builder/lzt_rainbow.json](/c:/Users/hasre/Documents/S4G/Listing-adder-server/_example_data_for_payload_builder/lzt_rainbow.json)
- [_example_data_for_payload_builder/tracker_rainbow.json](/c:/Users/hasre/Documents/S4G/Listing-adder-server/_example_data_for_payload_builder/tracker_rainbow.json)

## LZT signals carried into `R6LztSource`

- `title_en`: listing title text; used as a rank hint source.
- `uplayR6Rank` / `uplay_r6_rank`: direct rank values; can be weak or inconsistent.
- `uplayLinkedAccounts`: fallback platform linkage signal.
- `uplay_r6_operators_count`: explicit operator count.
- `uplay_r6_skins_count`: explicit skin count.
- `uplay_games`: ownership signal (`has_game`, `external_not_purchased`, `steam_not_purchased`).
- `canChangePassword` / `canChangeEmailPassword`: delivery/changeability hints.
- `email_provider` / `email_type`: email metadata.

## Tracker signals carried into `R6TrackerSource`

- `rank`: optional direct rank field; may be absent.
- `inventory["Ranked Charms"]`: fallback source for extracted rank.
- `currency.renown` / `currency.credits`: account currency summary.
- `socials.psn` / `socials.xbl`: linked platform profiles.
- inventory category counts:
  - `Black Ices`
  - `Glaciers`
  - `Gold Dusts`
  - `Dust Lines`
  - `Universals`
  - `Seasonals`
  - `Pro Leagues (Old)`
  - `Pro Leagues (New)` / `Pro Leagues`
  - `Elites`
  - yearly pilot program buckets

## Parsing decisions

- Source adapters stay source-local; they normalize and enrich one payload at a time.
- Both sources now expose the same core primitives:
  - `weapon_skins`: normalized weapon-skin records
  - `rank_signals`: normalized current/peak rank hints
- Rank semantics are split before resolver merge:
  - LZT current rank comes from direct rank fields
  - LZT peak-rank hint and peak-count hint come from rank-like `title_en` segments only
  - listing tokens like `Gold Dust` and `Black Ice` are intentionally excluded from LZT rank history parsing
  - tracker current rank comes from the last `Ranked Charms` entry when direct rank is absent
  - tracker peak rank and peak count come from the full `Ranked Charms` history
- Tracker `weapon_skins` excludes operator cosmetics, charms, flags, and attachment skins by classifier rules instead of counting raw inventory buckets blindly.
- Credentials remain optional on tracker payloads; resolver still decides whether missing credentials are valid for the current mode.
- Inventory remains fully typed, but frequently used aggregate counts are also parsed into `R6TrackerInventorySummary` so later stages do not need to recalculate them repeatedly.

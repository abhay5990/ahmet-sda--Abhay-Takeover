# Required Source Fields

Bu belge `_example_data_for_payload_builder/` altindaki mevcut source ornekleri ve bugunku kullanim noktalarina gore sadece `required` alanlari listeler.

Amac:
- tek yerde onaylanabilir required-field matrisi toplamak
- gereksiz extraction'i baslangicta engellemek
- source-model backlog'unu netlestirmek

Bu belge bilerek sadece `required` alanlari icerir.
`Optional`, `nice to have`, `pre-filter`, `UI metadata`, `seller noise`, `debug metadata` burada yer almaz.

## Global Rules

- `required` = en az bir yerde zorunlu olarak tuketilen alan:
  - credentials / access
  - resolver merge / derive
  - title / description
  - media generation
  - marketplace payload / attribute / trade environment
  - pricing / value sinyali
- Tracker source'larda credentials required degildir.
- LZT icin ortak envelope alanlari tum oyunlarda kabul edilir:
  - `item_id`
  - `category_id`
  - `price`
  - `loginData` / `emailLoginData` / `tempEmailData` uzerinden normalize `CredentialBundle`
- Buyuk nested objeler raw haliyle tasinmamali.
  Sadece listing flow'un ihtiyac duydugu minimal normalize form tasinmali.
- Ucuz ve guvenilir sekilde derive edilebilen alanlar yeni raw dependency olarak acilmamali.

## Coverage

Bu belge su an sadece ornek dosyasi olan source'lari kapsar:
- `bs` -> LZT
- `coc` -> LZT + Tracker
- `cr` -> LZT + Tracker
- `cs2` -> Steam LZT payload'i icinden
- `fortnite` -> LZT
- `genshin` -> LZT
- `lol` -> LZT
- `r6` -> LZT + Tracker
- `roblox` -> LZT
- `steam` -> LZT
- `ubisoft` -> LZT
- `valorant` -> LZT

Not:
- `lzt_gi.json.json` icindeki `HSR` ve `ZZZ` alanlari bu backlog'a dahil degil. Repo icinde aktif account flow'u yok.
- `lzt_steam.json` icindeki `steam_cs2_*` alanlari Steam genel modeli yerine `CS2` section'inda ele alinir.
- `lzt_ubisoft_connect.json` icindeki R6 detaylari `R6` section'inda ele alinir; `Ubisoft` section'i platform-account seviyesidir.

## CS2

Source:
- `LZT` via `_example_data_for_payload_builder/lzt_steam.json`

Required fields:
- `steam_cs2_rank_id` -> `rank_id`
- `steam_cs2_premier_elo` -> `premier_elo`
- `steamCs2Medals[]` -> `medals`
- `steam_full_games.list` -> CS2 oyun entry'si

Minimal normalized nested form:
- `cs2_game_entry`
  - `appid`
  - `title`
  - `playtime_forever`

Derive in source/resolver:
- `rank` display text <- `rank_id`
- `hours_played` <- CS2 game entry `playtime_forever`
- `is_prime` <- CS2/prime marker from `steam_full_games.list`

## R6

### LZT

Source:
- `_example_data_for_payload_builder/lzt_r6.json`
- `_example_data_for_payload_builder/lzt_ubisoft_connect.json`

Required fields:
- `title_en` or `title` -> title text / rank hint
- `uplay_r6_level` -> `level`
- `uplayR6Rank` or `uplay_r6_rank` -> current rank signal
- `uplay_r6_operators` -> operator list
- `uplay_r6_operators_count` -> operator count
- `uplay_r6_skins` -> skin id list
- `uplay_r6_skins_count` -> skin count
- `uplay_psn_connected`
- `uplay_xbox_connected`
- `uplayLinkedAccounts` -> platform fallback
- `uplay_id` -> tracker URL fallback / media product id
- `uplay_games` -> ownership state

Minimal normalized nested form:
- `uplay_games` sadece ownership kararina yetecek kadar tasinmali
  - `key`
  - `abbr`

Derive in source/resolver:
- `rank_signals` <- direct rank + title rank mentions
- `skin_names` / `weapon_skins` <- `uplay_r6_skins` lookup
- `has_game` / `ownership_state` <- `uplay_games`

### Tracker

Source:
- `_example_data_for_payload_builder/tracker_r6.json`

Required fields:
- `level`
- `rank` if present
- `marketplace_value`
- `currency.renown`
- `currency.credits`
- `inventory`
- `socials.psn`
- `socials.xbl`
- `userId`
- `maskedId` if present
- `username`

Minimal normalized nested form:
- `inventory_item`
  - `name`
  - `assetId`
- `inventory`
  - category -> `inventory_item[]`

Derive in source/resolver:
- `ranked_charms_lite` <- `inventory["Ranked Charms"]`
- `weapon_skins` <- inventory categories
- `black_ice_count` <- inventory buckets / skin buckets
- `platform flags` <- `socials`

## Valorant

Source:
- `_example_data_for_payload_builder/lzt_val.json`

Required fields:
- `riot_valorant_region`
- `riot_valorant_level`
- `riot_valorant_wallet_vp`
- `riot_valorant_wallet_rp`
- `riot_valorant_rank_type`
- `valorantRankTitle`
- `valorantPreviousRankTitle`
- `valorantLastRankTitle`
- `valorantInventory.WeaponSkins`
- `valorantInventory.Agent`
- `valorantInventory.Buddy`
- `riot_valorant_skin_count`
- `riot_valorant_agent_count`
- `riot_valorant_knife_count`
- `riot_valorant_inventory_value`
- `imagePreviewLinks.direct`
- `tracker_link` or tracker link inside `accountLinks`

Minimal normalized nested form:
- `valorantInventory`
  - `WeaponSkins: list[id]`
  - `Agent: list[id]`
  - `Buddy: list[id]`
- `imagePreviewLinks.direct`
  - `weapons`
  - `agents`
  - `buddies`

Derive in source/resolver:
- `skin_names` / `agent_names` / `buddy_names` <- catalog lookup
- `buddy_count` <- resolved buddy list length

## Brawl Stars

Source:
- `_example_data_for_payload_builder/lzt_bs.json`

Required fields:
- `supercell_laser_level` -> `level`
- `supercell_brawler_count` -> `brawler_count`
- `supercell_laser_trophies` -> `trophies`
- `supercell_legendary_brawler_count` -> `legendary_brawler_count`
- `supercellBrawlers`

Minimal normalized nested form:
- `brawler`
  - `name`
  - `class`
  - `power`
  - `rank`
  - `path`

Derive in source/resolver:
- `max_level_brawlers_count` <- brawlers with `power >= 11`
- `brawlers_rank_30_plus_count` <- brawlers with `rank >= 30`
- `brawler_names` <- brawler list

## Clash of Clans

### LZT

Source:
- `_example_data_for_payload_builder/lzt_coc.json`

Required fields:
- `supercell_town_hall_level`
- `supercell_builder_hall_level`
- `supercell_magic_level` -> account level fallback
- `supercell_magic_trophies`
- `supercell_total_heroes_level`
- `supercell_total_troops_level`
- `supercell_total_spells_level`

### Tracker

Source:
- `_example_data_for_payload_builder/tracker_coc.json`

Required fields:
- `tag`
- `townHallLevel`
- `builderHallLevel`
- `expLevel`
- `trophies`
- `warStars`
- `heroes`
- `heroEquipment`
- `troops`
- `spells`
- `superTroops`
- `achievements`

Minimal normalized nested form:
- `hero`
  - `id`
  - `order`
  - `level`
  - `maxLevel`
  - `maxLevelForPlayer`
  - `village`
- `hero_equipment`
  - `id`
  - `hero`
  - `order`
  - `level`
  - `maxLevel`
  - `maxLevelForPlayer`
  - `isUnlocked`
  - `isActive`
- `troop`
  - `id`
  - `order`
  - `level`
  - `maxLevel`
  - `maxLevelForPlayer`
  - `village`
  - `isDark`
- `spell`
  - `id`
  - `order`
  - `level`
  - `maxLevel`
  - `maxLevelForPlayer`
  - `village`
  - `isDark`
- `super_troop`
  - `id`
  - `order`
  - `level`
  - `maxLevelForPlayer`
  - `isUnlocked`
  - `isActive`
- `achievement`
  - `value`
  - `target`

Derive in source/resolver:
- hero level string / hero totals
- troop and spell totals
- achievement completion percentage

## Clash Royale

### LZT

Source:
- `_example_data_for_payload_builder/lzt_cr.json`

Required fields:
- `supercell_king_level`
- `supercell_scroll_level`
- `supercell_scroll_trophies`
- `supercell_arena`
- `supercell_scroll_victories`
- `supercell_scroll_battle_pass`

### Tracker

Source:
- `_example_data_for_payload_builder/tracker_cr.json`

Required fields:
- `profile.hashtag`
- `profile.kingLevel`
- `profile.trophies`
- `profile.maxscore`
- `profile.cardsFound`
- `profile.wins`
- `profile.losses`
- `profile.threeCrownWins`
- `profile.cards`

Minimal normalized nested form:
- `card`
  - `id`
  - `name`
  - `rarity`
  - `normalizedLevel`
  - `count`
  - `maxLevel`

Derive in source/resolver:
- elite / max / legendary / champion counts
- tracker link

## Fortnite

Source:
- `_example_data_for_payload_builder/lzt_fn.json`

Required fields:
- `fortnite_platform`
- `fortnite_balance`
- `fortnite_level`
- `fortnite_psn_linkable`
- `fortnite_xbox_linkable`
- `fortniteSkins`
- `fortnitePickaxe`
- `fortniteDance`
- `fortniteGliders`

Minimal normalized nested form:
- `fortnite_item`
  - `title`

Derive in source/resolver:
- outfit / pickaxe / emote / glider counts <- list lengths
- valuable item detection <- item titles
- `v_bucks` display <- `fortnite_platform` + `fortnite_balance`

## Genshin Impact

Source:
- `_example_data_for_payload_builder/lzt_gi.json.json`

Required fields:
- `mihoyoRegionPhrase` or `mihoyo_region`
- `mihoyo_genshin_level`
- `mihoyo_genshin_character_count`
- `mihoyo_genshin_legendary_characters_count`
- `mihoyo_genshin_legendary_weapons_count`
- `genshinCharacters`

Minimal normalized nested form:
- `genshin_character`
  - `name`
  - `level`
  - `rarity`
  - `actived_constellation_num`
  - `weapon.name`
  - `weapon.rarity`

Derive in source/resolver:
- `constellations_count` <- characters if raw field is unreliable/missing
- region code <- `mihoyoRegionPhrase`

## League of Legends

Source:
- `_example_data_for_payload_builder/lzt_lol.json`

Required fields:
- `riot_lol_region`
- `riot_lol_rank`
- `riot_lol_level`
- `riot_lol_skin_count`
- `riot_lol_champion_count`
- `riot_lol_wallet_blue`
- `riot_lol_wallet_riot`
- `riot_lol_wallet_orange`
- `lolInventory.Skin`
- `lolInventory.Champion`

Minimal normalized nested form:
- `lolInventory`
  - `Skin: list[id]`
  - `Champion: list[id]`

Derive in source/resolver:
- `skin_titles` <- skin id catalog lookup
- `champion_titles` <- champion id catalog lookup

## Roblox

Source:
- `_example_data_for_payload_builder/lzt_roblox.json`

Required fields:
- `roblox_username`
- `roblox_register_date`
- `roblox_robux`
- `roblox_incoming_robux_total`
- `roblox_inventory_price`
- `roblox_ugc_limited_price`
- `roblox_offsale_count`
- `roblox_age_verified`

Derive in source/resolver:
- short username signal <- `roblox_username`
- register year / account age <- `roblox_register_date`

## Steam

Source:
- `_example_data_for_payload_builder/lzt_steam.json`

Required fields:
- `steam_game_count`
- `steam_full_games.list`
- `steam_level`
- `steam_register_date`
- `steam_country`

Minimal normalized nested form:
- `steam_game`
  - `appid`
  - `title`
  - `playtime_forever`
  - `img`

Derive in source/resolver:
- `steam_age` <- `steam_register_date`
- important games / top played games <- `steam_full_games.list`

## Ubisoft Connect

Source:
- `_example_data_for_payload_builder/lzt_ubisoft_connect.json`

Required fields:
- `uplay_game_count`
- `uplay_games`
- `uplay_r6`
- `uplay_r6_level`
- `uplayR6Rank` or `uplay_r6_rank`
- `uplay_psn_connected`
- `uplay_xbox_connected`

Minimal normalized nested form:
- `uplay_game`
  - `gameId`
  - `title`
  - `img`

Derive in source/resolver:
- important game list <- `uplay_games`

## Approval Notes

Bu belge onaylandiginda sonraki adim:
- oyun/source bazli minimal source model backlog'u cikarmak
- implementasyonu once mevcut `payload_pipeline` slice pattern'lerine gore yaptirmak
- required listede olmayan alanlari yeni blocker gibi davranmadan disarida birakmak

# Eldorado account contract (late Oct 2026) — live proof, 2 Nov 2026

Store: `eldorado-ezsmurfshop`, SDA server 35.196.63.190, direct connection (no proxy).
Every test listing: title "TEST LISTING - DO NOT BUY", price $999, fake credentials. Each was deleted right after creation, and all 12 were re-checked with the public `GET /api/flexibleOffers/{id}` → 404.

## Before (current SDA code)
- GTA 5 (old `accountSecretDetails`): **400 "Quantity of 0 is too low. Increase it to at least 1…"**
- Fortnite (dropdowns only): **400 "Required attribute 'Emotes' is not set."**

## After (this branch)
| Game | Create | Delete | Re-check |
|---|---|---|---|
| GTA 5 | 201 | 204 | 404 |
| Fortnite | 201 | 204 | 404 |
| Valorant | 201 | 204 | 404 |
| League of Legends | 201 (after one 429 cowboy wait) | 204 | 404 |
| Rainbow Six Siege | 201 | 204 | 404 |
| Clash of Clans | 201 | 204 | 404 |
| Brawl Stars | 201 | 204 | 404 |
| Roblox | first try 400 "Select attribute 'Game' value 'Other' is not allowed." → fixed → 201 | 204 | 404 |
| CS2 | 201 | 204 | 404 |
| Rust | 201 | 204 | 404 |
| Genshin Impact | 201 | 204 | 404 |
| Forza Horizon 5 | 201 | 204 | 404 |

## Raw log
```
=== BEFORE (live SDA code) Mon Nov  2 11:06:39 UTC 2026
PROBE BEFORE gta5 (current SDA shape: accountSecretDetails): CREATE_REJECTED status=400 eldorado={'code': 400, 'messages': ['Quantity of 0 is too low. Increase it to at least 1 to meet the minimum order value.']}
PROBE BEFORE fortnite (current SDA shape: Select only + accountSecretDetails): CREATE_REJECTED status=400 eldorado={'code': 400, 'messages': ["Required attribute 'Emotes' is not set."]}
=== AFTER (branch eldorado-oct-contract) Mon Nov  2 11:07:44 UTC 2026
PROBE AFTER gta5: CREATED status=201 id=051a8898-1e5e-4c40-40c0-08df37eb0bcf
PROBE AFTER gta5: DELETE status=204 ok=True
PROBE AFTER fortnite: CREATED status=201 id=961c5ff2-4814-4c50-41a7-08df37eb0bcf
PROBE AFTER fortnite: DELETE status=204 ok=True
PROBE AFTER valorant: CREATED status=201 id=a0ff0641-7821-4875-3c07-08df37fd70e0
PROBE AFTER valorant: DELETE status=204 ok=True
PROBE AFTER lol: CREATE_REJECTED status=429 eldorado={'code': 429, 'messages': ['Whoa! Calm down, cowboy! Quota exceeded. Please try again later.']}
PROOF cowboy on AFTER lol, waiting 60s
PROBE AFTER lol: CREATED status=201 id=223fb09d-f207-4f83-bacb-08df37aebec6
PROBE AFTER lol: DELETE status=204 ok=True
PROBE AFTER r6: CREATED status=201 id=059eee7d-1525-47a6-8cf3-08df37f5725b
PROBE AFTER r6: DELETE status=204 ok=True
PROBE AFTER coc: CREATED status=201 id=0e92d653-f693-420a-0db3-08df37d60fdb
PROBE AFTER coc: DELETE status=204 ok=True
PROBE AFTER brawl-stars: CREATED status=201 id=10e3308a-0b8e-48ff-4164-08df37fd70e0
PROBE AFTER brawl-stars: DELETE status=204 ok=True
PROBE AFTER roblox: CREATE_REJECTED status=400 eldorado={'code': 400, 'messages': ["Select attribute 'Game' value 'Other' is not allowed."]}
PROBE AFTER cs2: CREATED status=201 id=db7d25a6-2200-45d1-4a47-08df37eb0bcf
PROBE AFTER cs2: DELETE status=204 ok=True
PROBE AFTER rust: CREATED status=201 id=8f925b00-59e0-4d1f-e531-08df371db2e6
PROBE AFTER rust: DELETE status=204 ok=True
PROBE AFTER genshin: CREATED status=201 id=8853cfa9-54bd-43f6-44b0-08df37fd70e0
PROBE AFTER genshin: DELETE status=204 ok=True
PROBE AFTER forza-horizon-5: CREATED status=201 id=ba0edf67-56b9-444a-9388-08df37f5725b
PROBE AFTER forza-horizon-5: DELETE status=204 ok=True
(after Roblox fix) PROBE AFTER roblox (no Game attribute): CREATED status=201 id=3fcd7c7d-e56a-43c8-98d4-08df37f5725b
(after Roblox fix) PROBE AFTER roblox (no Game attribute): DELETE status=204 ok=True
VERIFY all 12 ids above → GET /api/flexibleOffers/{id} = 404
```

## Tests (SDA server venv, branch vs live code)
- payload_pipeline unit: **516 passed / 44 failed** (live code: 502 / 44 — the same 44 old failures: images not available in tests, uploader not configured). **0 new failures.**
- apis_sdk: **81 passed** (live: 75), the same 21 old fixture errors.
- New tests: `libs/payload_pipeline/tests/unit/test_eldorado_oct_2026_contract.py`, `libs/apis_sdk/tests/test_eldorado_delivery_details.py`.

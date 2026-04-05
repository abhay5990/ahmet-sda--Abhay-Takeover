"""
LZT item verilerini Gameboost offer payload'ına dönüştürür.
Kullanım: python scripts/lzt_to_gameboost.py
"""
import json

PLATFORM_MAP = {
    "EpicPC": "PC",
    "PSN": "PlayStation",
    "XBL": "Xbox",
    "Android": "Android",
    "iOS": "iOS",
    "Switch": "Switch",
}

IMAGES = [
    "https://www.dropbox.com/scl/fi/vb92s4djz1okblszgooya/robloximage.jpg?rlkey=6a0ljr9aampa5ej3x5mokmwsm&st=mqtcpph6&dl=1"
]

# Her oyun icin: template_field -> (lzt_field, transform)
# transform: None=direkt al, "len"=array uzunlugu, "platform"=platform map
FIELD_MAPS = {
    "fortnite": {
        "platform": ("fortnite_platform", "platform"),
        "linkable_platforms": (None, "linkable_platforms"),
        "account_tags": (None, "empty_array"),
        "outfits_count": ("fortnite_skin_count", None),
        "emotes_count": ("fortniteDance", "len"),
        "pickaxes_count": ("fortnitePickaxe", "len"),
        "backblings_count": (None, "zero"),
        "gliders_count": (None, "zero"),
        "wraps_count": (None, "zero"),
        "loadings_count": (None, "zero"),
        "sprays_count": (None, "zero"),
        "account_level": ("fortnite_level", None),
        "v_bucks_count": ("fortnite_balance", None),
    },
}


def resolve_field(item, source, transform, game):
    if transform == "zero":
        return 0
    if transform == "empty_array":
        return []
    if transform == "platform":
        return PLATFORM_MAP.get(item.get(source, ""), "PC")
    if transform == "linkable_platforms":
        platforms = []
        if item.get(f"{game}_xbox_linkable"):
            platforms.append("Xbox")
        if item.get(f"{game}_psn_linkable"):
            platforms.append("PlayStation")
        return platforms
    if transform == "len":
        return len(item.get(source, []))

    # None transform = direkt deger al
    return item.get(source, 0)


def build_account_data(item, game):
    field_map = FIELD_MAPS.get(game, {})
    result = {}
    for key, (source, transform) in field_map.items():
        result[key] = resolve_field(item, source, transform, game)
    return result


def build_credentials(item):
    parts = []
    login_data = item.get("loginData", {})
    if login_data.get("login") and login_data.get("password"):
        parts.append(f"Login: {login_data['login']} Password: {login_data['password']}")

    email_data = item.get("emailLoginData", {})
    if email_data.get("login") and email_data.get("password"):
        parts.append(f"Email: {email_data['login']} Password: {email_data['password']}")

    return "\n".join(parts)


def lzt_to_gameboost(item, game="fortnite"):
    return {
        "game": game,
        "title": item.get("title", ""),
        "price": item.get("price", 0),
        "credentials": build_credentials(item),
        "image_urls": IMAGES,
        "description": item.get("description", "") or item.get("title", ""),
        "is_manual": False,
        "account_data": build_account_data(item, game),
    }


if __name__ == "__main__":
    with open("_data_samples/lzt/fortnite_item.json", "r", encoding="utf-8") as f:
        item = json.load(f)

    payload = lzt_to_gameboost(item)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

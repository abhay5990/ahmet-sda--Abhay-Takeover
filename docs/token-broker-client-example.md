# Token Broker — Client Integration Guide

## Endpoint

```
GET /integrations/api/token/?marketplace=eldorado&store=<store-slug>
```

## Authentication

Every request must include an API key in the `Authorization` header:

```
Authorization: Bearer <your-api-key>
```

API keys are created in the Django admin panel under **Token API Clients**.
The plain key is shown **once** at creation time — copy and save it securely.

## IP Whitelist

Each API client has an IP whitelist. Requests from unlisted IPs get `403 Forbidden`.

- **`allowed_ips`**: List of IPs or CIDR ranges (e.g. `["85.1.2.3", "10.0.0.0/24"]`)
- **`allow_any_ip`**: Set to `True` to skip IP checks (use with caution)
- Empty `allowed_ips` + `allow_any_ip=False` = **no IP accepted** (secure default)

## Response

```json
{
    "token": "eyJraWQiOiJ...",
    "expires_in": 3247,
    "marketplace": "eldorado",
    "store": "eldorado-store4gamers"
}
```

- `token`: The marketplace auth token (e.g. Cognito ID token for Eldorado)
- `expires_in`: Seconds until the token expires
- `Cache-Control: no-store` header is always set

## Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Missing `marketplace`/`store` params, or unsupported marketplace |
| 401 | Missing/invalid API key |
| 403 | IP not in whitelist |
| 404 | Store not found or inactive |
| 502 | Token refresh failed (Cognito error) |

## Python Client Example

```python
import requests

TOKEN_BROKER_URL = "https://your-server.com/integrations/api/token/"
API_KEY = "your-api-key-here"

def get_eldorado_token(store_slug: str) -> str:
    """Fetch a valid Eldorado token from the central broker."""
    response = requests.get(
        TOKEN_BROKER_URL,
        params={"marketplace": "eldorado", "store": store_slug},
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data["token"]


# Usage
token = get_eldorado_token("eldorado-store4gamers")
```

### With caching (recommended)

```python
import time
import requests

TOKEN_BROKER_URL = "https://your-server.com/integrations/api/token/"
API_KEY = "your-api-key-here"

_token_cache: dict[str, tuple[str, float]] = {}

def get_eldorado_token(store_slug: str) -> str:
    """Fetch token with local cache to minimize broker calls."""
    cached = _token_cache.get(store_slug)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - 60:  # 60s safety buffer
            return token

    response = requests.get(
        TOKEN_BROKER_URL,
        params={"marketplace": "eldorado", "store": store_slug},
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    _token_cache[store_slug] = (
        data["token"],
        time.time() + data["expires_in"],
    )
    return data["token"]
```

## Supported Marketplaces

| Marketplace | Status |
|-------------|--------|
| `eldorado` | Supported |
| Others | Not yet — will be added as needed |

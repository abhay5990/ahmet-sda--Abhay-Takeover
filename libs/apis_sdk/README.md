# apis-sdk

Reusable integration SDK for external provider APIs. Designed as a portable, self-contained module with clean architecture boundaries.

## Architecture

```
apis_sdk/
├── core/              # Shared abstractions, protocols, result types, exceptions
├── infrastructure/    # Technical runtime: HTTP transport, proxy engine, retry, rate limiting, auth
│   ├── auth/          # ApiKey, Bearer, Cookie auth providers
│   ├── http/          # Requests + curl_cffi transports, session factory
│   ├── proxy/         # Pool, rotation, health tracking
│   ├── retry/         # Policy, strategy, decision, runtime
│   ├── rate_limit/    # In-memory sliding window
│   └── logging/       # SDK logger abstraction
├── clients/           # External provider integrations
│   ├── marketplaces/  # Eldorado, GameBoost, PlayerAuctions, G2G, LZT
│   ├── proxy/         # Proxyline
│   ├── media/         # Imgur, ImageShack
│   ├── services/      # RBXCrate
│   └── trackers/      # ClashOfStats, R6Locker, StatsRoyale
├── factories/         # Object construction and dependency wiring
└── application/       # Higher-level DTOs, use cases
```

## Design Principles

- **No app-specific coupling** — does not import from the host application
- **Constructor injection** — explicit dependencies, no hidden globals
- **Protocol-based abstractions** — consumers depend on interfaces, not implementations
- **Layered architecture** — core → infrastructure → clients → application
- **Provider-agnostic infrastructure** — HTTP transport, proxy pool, retry policies are reusable

## Dependency Flow

```
core (no deps)
  ↑
infrastructure (depends on core)
  ↑
clients (depends on core + infrastructure)
  ↑
factories (depends on all layers, wires them together)
  ↑
application (depends on core + clients via protocols)
```

## Usage

```python
from apis_sdk.factories import ProxyClientFactory, TransportFactory

transport = TransportFactory.create_requests_transport(timeout=30.0)
proxy_client = ProxyClientFactory.create_proxyline(api_key="...", transport=transport)

result = proxy_client.list_proxies()
if result.ok:
    for proxy in result.data:
        print(proxy)
```

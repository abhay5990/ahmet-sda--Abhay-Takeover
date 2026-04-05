# Multi-Marketplace Inventory Manager

Internal tool for managing game-account inventory, marketplace accounts, local
listings, and local orders from a single Django codebase.

## Current state

The repository currently contains these active Django apps:

- `accounts`
- `inventory`
- `integrations`
- `listings`
- `orders`
- `dashboard`

The next planned boundary is `apps.sync`, which will own checkpointed sync and
backfill workflows.

## Stack

- Backend: Django
- Database: SQLite in local development, MySQL in production
- Frontend: Django templates + Alpine.js + Tailwind CSS
- External provider runtime: `libs/apis_sdk`

## Setup

### 1. Prerequisites

- Python 3.11+
- Git
- Docker and Docker Compose if you want local MySQL

### 2. Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements/dev.txt
pip install -e ./libs/apis_sdk
```

On Windows PowerShell, activate with:

```powershell
venv\Scripts\Activate.ps1
```

### 3. Environment

```bash
cp .env.example .env
```

`.env` is for Django settings, database access, and the credential encryption
key. Provider credentials are stored in the database through
`IntegrationCredential`.

### 4. Database

SQLite works out of the box.

For MySQL:

```bash
docker-compose up -d
cd backend
python manage.py migrate
python manage.py createsuperuser
```

### 5. Run

```bash
cd backend
python manage.py runserver
```

Admin panel:

- `http://localhost:8000/admin/`

## Documentation

The living documentation is under `docs/`.

- [`docs/README.md`](docs/README.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/IMPLEMENTATION_PHASES.md`](docs/IMPLEMENTATION_PHASES.md)
- [`docs/PROJECT_AUDIT_AND_ROADMAP.md`](docs/PROJECT_AUDIT_AND_ROADMAP.md)

Project-management and ADR files remain under `_ai/`.

- [`_ai/spec.md`](_ai/spec.md)
- [`_ai/decisions.md`](_ai/decisions.md)
- [`_ai/todo.md`](_ai/todo.md)

## Current structure

```text
backend/
  config/
  apps/
    accounts/
    inventory/
    integrations/
      providers/
    listings/
    orders/
    dashboard/
  core/
  manage.py

frontend/
  templates/
  static/

docs/
  README.md
  ARCHITECTURE.md
  IMPLEMENTATION_PHASES.md
  PROJECT_AUDIT_AND_ROADMAP.md

libs/
  apis_sdk/

_data_samples/
_helpers_folders/
_ai/
```

## Provider development workflow

When adding a new provider:

1. collect or sanitize sample payloads in `_data_samples/{provider}/`
2. add the provider client to `libs/apis_sdk`
3. add a factory if needed under `libs/apis_sdk/apis_sdk/factories/`
4. add the Django provider wrapper under `backend/apps/integrations/providers/`
5. register it through `backend/apps/integrations/apps.py`
6. create an `IntegrationAccount` and `IntegrationCredential` in admin

## Testing

The repo already has test directories:

- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`

They are currently placeholders and should be populated as sync work starts.

## Notes

- Internal canonical term is `listing`
- External provider naming may still use `offer`
- Long-lived sync workflows should move into `apps.sync`, not `scripts/`

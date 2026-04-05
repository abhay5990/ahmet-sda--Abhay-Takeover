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

If you plan to use MySQL (not SQLite), install the required system libraries first:

```bash
sudo apt install pkg-config libmysqlclient-dev -y
```

### 2. Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements/base.txt
pip install -r requirements/dev.txt
pip install -r requirements/mysql.txt
pip install -r requirements/prod.txt
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

## Server Deployment (Scheduler Only)

Production sunucusunda sadece scheduler çalıştırmak için:

### 1. Clone & Environment

```bash
git clone https://github.com/Ahmetcetin3448/e-commerce-management-system.git
cd e-commerce-management-system
sudo apt install pkg-config libmysqlclient-dev -y
python3 -m venv venv
source venv/bin/activate
pip install -r requirements/prod.txt
pip install -e ./libs/apis_sdk
```

### 2. Configure

```bash
cp .env.example .env
```

`.env` dosyasını düzenle:

```env
DJANGO_SECRET_KEY=<güçlü-rastgele-key>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

DB_ENGINE=django.db.backends.mysql
DB_USER=root
DB_PASSWORD=<güçlü-şifre>
DB_HOST=localhost
DB_PORT=3307

CREDENTIAL_ENCRYPTION_KEY=<fernet-key>
```

Fernet key oluşturmak için:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Database

```bash
docker-compose up -d    # MySQL + phpMyAdmin
cd backend
python manage.py migrate
python manage.py createsuperuser
```

### 4. Seed Data

```bash
python manage.py seed_games
```

### 5. Admin'den Credential Tanımla

`http://localhost:8000/admin/` → IntegrationAccount + IntegrationCredential oluştur.

### 6. LZT Backfill (İlk Import)

```bash
# API'den (dosya taşımaya gerek yok)
python manage.py import_lzt_orders lzt-main --source api

# Veya JSON dosyasından (hızlı)
python manage.py import_lzt_orders lzt-main data.json
```

### 7. Scheduler'ı Başlat

```bash
python manage.py runapscheduler
```

Arka planda sürekli çalışması için systemd servisi:

```ini
# /etc/systemd/system/ecom-scheduler.service
[Unit]
Description=E-Commerce Sync Scheduler
After=docker.service

[Service]
Type=simple
User=<kullanıcı>
WorkingDirectory=/path/to/e-commerce-management-system/backend
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
ExecStart=/path/to/venv/bin/python manage.py runapscheduler
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable ecom-scheduler
sudo systemctl start ecom-scheduler
sudo journalctl -u ecom-scheduler -f   # logları izle
```

### 8. phpMyAdmin'e Local'den Erişim (SSH Tunnel)

```bash
ssh -L 8080:127.0.0.1:8080 kullanici@sunucu-ip
```

Tarayıcıda `http://localhost:8080` → phpMyAdmin açılır.

---

## Documentation

The living documentation is under `docs/`.

- [`docs/README.md`](docs/README.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/IMPLEMENTATION_PHASES.md`](docs/IMPLEMENTATION_PHASES.md)
- [`docs/PROJECT_AUDIT_AND_ROADMAP.md`](docs/PROJECT_AUDIT_AND_ROADMAP.md)

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

# E-Commerce Management System

Internal tool for managing game-account inventory, marketplace listings, and orders from a single Django admin panel.

## Stack

| Layer | Technology |
|---|---|
| Backend | Django 5, Python 3.10 |
| Database | SQLite (dev) / MySQL 8 (prod) |
| Frontend | Django templates, Alpine.js, Tailwind CSS |
| Web server | Nginx → Gunicorn (prod) |
| Scheduler | APScheduler via systemd services |
| Provider SDK | `libs/apis_sdk` |

---

## Local Development

### Prerequisites

- Python 3.10+
- Docker + Docker Compose (optional — only for MySQL, SQLite works out of the box)

MySQL system libs (if you want MySQL locally):
```bash
sudo apt install pkg-config libmysqlclient-dev -y
```

### Setup

```bash
# 1. Virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Dependencies
pip install -r requirements/base.txt
pip install -r requirements/dev.txt
pip install -r requirements/mysql.txt   # only if using MySQL
pip install -e libs/apis_sdk
pip install -e libs/payload_pipeline

# 3. Environment
cp .env.example .env
# Edit .env: DJANGO_DEBUG=True, DB_ENGINE=sqlite3 (default)

# 4. Database
python backend/manage.py migrate
python backend/manage.py createsuperuser

# 5. Run
python backend/manage.py runserver
```

App: `http://localhost:8000` — Admin: `http://localhost:8000/admin/`

### Local MySQL (optional)

```bash
docker-compose up -d        # starts MySQL + phpMyAdmin
# docker-compose.override.yml is auto-loaded, phpMyAdmin at http://localhost:8082
```

---

## Production Deployment

### Architecture

```
Internet
  │
  ▼
Nginx (80 → 443 redirect, SSL via Certbot)
  ├── /static/  → staticfiles/ on disk  (no Django involved)
  ├── /media/   → media/ on disk
  └── /*        → Gunicorn on 127.0.0.1:8000
                      │
                      ▼
                   Django (config.settings.prod)
                      │
                      ▼
                  MySQL (Docker, 127.0.0.1:3307)

phpMyAdmin: 127.0.0.1:8082 — NOT exposed to internet.
Access only via SSH tunnel (see below).
```

### Services (systemd)

| Service | Description |
|---|---|
| `ecom-gunicorn` | Django web server (Gunicorn) |
| `ecom-scheduler` | APScheduler — sync chain, review monitor, pool sweep, order status refresh |
| `ecom-dropship` | Dropship scheduler — poster + cleaner threads |

All service files are templates with `${PROJECT_DIR}` — resolved by `deploy.sh` via `envsubst`.

---

### First-time server setup

#### 1. System packages

```bash
apt update
apt install nginx python3-venv python3-pip pkg-config libmysqlclient-dev gettext-base -y
```

#### 2. Clone & virtualenv

```bash
cd ~
git clone <repo-url> e-commerce-management-system
cd e-commerce-management-system

python3 -m venv venv
venv/bin/pip install -r requirements/prod.txt
venv/bin/pip install -e libs/apis_sdk
venv/bin/pip install -e libs/payload_pipeline
```

#### 3. Environment

```bash
cp .env.example .env
nano .env
```

Minimum prod values:

```env
# PROJECT_DIR is auto-detected by deploy.sh from repo root.
# Override only if needed:
# PROJECT_DIR=/home/ubuntu/e-commerce-management-system

DOMAIN=ubuntu.anap4smurfkings.com
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=<50+ char random string>
DJANGO_DEBUG=False

DB_ENGINE=django.db.backends.mysql
DB_PASSWORD=<strong password>
DB_HOST=127.0.0.1
DB_PORT=3307

CREDENTIAL_ENCRYPTION_KEY=<fernet key>
```

Generate keys:
```bash
# Django secret key
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

# Fernet encryption key
venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### 4. Database (Docker)

```bash
# Start MySQL + phpMyAdmin
docker-compose -f docker-compose.yml up -d

# Wait for MySQL to be ready (~10s), then run migrations
cd backend
../venv/bin/python manage.py migrate
../venv/bin/python manage.py createsuperuser
cd ..
```

#### 5. SSL (Certbot)

```bash
apt install certbot python3-certbot-nginx -y
certbot certonly --standalone -d ubuntu.anap4smurfkings.com
```

#### 6. Deploy

```bash
mkdir -p backend/logs
bash deploy/deploy.sh
```

This script handles everything on every deploy:
- `git pull`
- `pip install`
- `migrate` + `collectstatic`
- Generates nginx config from template (`${DOMAIN}` + `${PROJECT_DIR}` substituted)
- Installs/updates systemd services (templates rendered via `envsubst`)
- Restarts `ecom-gunicorn`, `ecom-dropship`, `ecom-scheduler`
- Reloads nginx

---

### Data Migration (from existing server)

If migrating from an existing server, follow these steps **after** completing steps 1-4 above (skip `migrate` and `createsuperuser`).

#### On the old server:

```bash
mysqldump -u root -p inventory_manager \
  --ignore-table=inventory_manager.sync_rawpayload \
  --ignore-table=inventory_manager.sync_syncrun \
  --ignore-table=inventory_manager.sync_synclog \
  --ignore-table=inventory_manager.django_apscheduler_djangojobexecution \
  > dump.sql

scp dump.sql root@<new-server-ip>:~/
```

**Excluded tables** (regenerated automatically by the sync system):
- `sync_rawpayload` — raw marketplace API responses (large, re-fetched on next sync)
- `sync_syncrun` — sync execution audit log
- `sync_synclog` — operational debug logs
- `django_apscheduler_djangojobexecution` — scheduler execution history

#### On the new server:

```bash
# Import the dump (MySQL must be running)
mysql -u root -p -h 127.0.0.1 -P 3307 inventory_manager < ~/dump.sql
```

> **Important:** Copy `CREDENTIAL_ENCRYPTION_KEY` from the old server's `.env` — without it, encrypted credentials become unreadable.

Then continue with steps 5-6 (SSL + deploy).

---

### Subsequent deploys

```bash
bash deploy/deploy.sh
```

---

### DNS Setup (subdomain)

To set up a subdomain (e.g. `ubuntu.anap4smurfkings.com`):

1. Add an **A record** at your DNS provider:

   | Type | Name | Value |
   |------|------|-------|
   | A | `ubuntu` | `<server IP>` |

2. Set `DOMAIN=ubuntu.anap4smurfkings.com` in `.env`
3. Get SSL certificate: `certbot certonly --standalone -d ubuntu.anap4smurfkings.com`
4. Run `bash deploy/deploy.sh`

---

### phpMyAdmin — SSH tunnel access

phpMyAdmin is **not** accessible via the web. Connect via SSH tunnel:

```bash
ssh -L 8082:127.0.0.1:8082 root@<your-domain>
```

Then open `http://localhost:8082` in your browser.

---

### Useful commands

```bash
# Service logs
journalctl -u ecom-gunicorn  -n 100 -f
journalctl -u ecom-dropship  -n 100 -f
journalctl -u ecom-scheduler -n 100 -f

# Service status
systemctl status ecom-gunicorn ecom-dropship ecom-scheduler

# Nginx logs (replace with your domain)
tail -f /var/log/nginx/<your-domain>.access.log
tail -f /var/log/nginx/<your-domain>.error.log

# Django shell
cd backend && ../venv/bin/python manage.py shell
```

---

## File Structure

```
e-commerce-management-system/
│
├── backend/                      Django project
│   ├── apps/                     Feature apps
│   ├── config/
│   │   └── settings/
│   │       ├── base.py
│   │       ├── dev.py
│   │       └── prod.py
│   ├── logs/                     gitignored
│   └── manage.py
│
├── deploy/                       All deployment config
│   ├── nginx/
│   │   └── site.conf.template    Nginx template (${DOMAIN} + ${PROJECT_DIR} substituted)
│   ├── systemd/
│   │   ├── ecom-gunicorn.service   Template — rendered by deploy.sh
│   │   ├── ecom-dropship.service   Template — rendered by deploy.sh
│   │   └── ecom-scheduler.service  Template — rendered by deploy.sh
│   └── deploy.sh                 Single-command deploy script
│
├── frontend/
│   ├── static/
│   └── templates/
│
├── libs/
│   ├── apis_sdk/
│   └── payload_pipeline/
│
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   ├── mysql.txt
│   └── prod.txt
│
├── docker-compose.yml            Base — prod-safe (MySQL + phpMyAdmin localhost-only)
├── docker-compose.override.yml   Dev overrides (auto-loaded by `docker compose up`)
│
├── .env                          gitignored — actual secrets
└── .env.example                  Committed — template with all variables documented
```

---

## Apps

| App | Responsibility |
|---|---|
| `accounts` | Custom user model, auth |
| `inventory` | Product / stock management |
| `integrations` | External marketplace credentials and providers |
| `listings` | Active listings per marketplace |
| `orders` | Order tracking and status |
| `dashboard` | Overview and stats |
| `posting` | Dropship scheduler and posting logic |
| `sync` | Checkpointed sync workflows |
| `settings` | App-level configuration UI |

## Provider development

When adding a new marketplace provider:

1. Add the API client to `libs/apis_sdk`
2. Add the Django provider wrapper under `backend/apps/integrations/providers/`
3. Register it in `backend/apps/integrations/apps.py`
4. Create an `IntegrationAccount` + `IntegrationCredential` in the admin panel

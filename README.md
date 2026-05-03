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

### First-time server setup

#### 1. System packages

```bash
apt update
apt install nginx python3-venv python3-pip pkg-config libmysqlclient-dev gettext-base -y
```

#### 2. Clone & virtualenv

```bash
cd /home/ahmet
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
DOMAIN=admin4gamers.com
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

#### 4. Log directory

```bash
mkdir -p backend/logs
```

#### 5. Database (Docker)

```bash
# Start MySQL + phpMyAdmin (phpMyAdmin is localhost-only, safe to start)
docker-compose -f docker-compose.yml up -d

# Run migrations
cd backend
../venv/bin/python manage.py migrate
../venv/bin/python manage.py createsuperuser
cd ..
```

#### 6. Static files

```bash
cd backend
../venv/bin/python manage.py collectstatic --noinput
cd ..
```

#### 7. SSL (Certbot)

```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d admin4gamers.com -d www.admin4gamers.com
```

#### 8. Disable old nginx site (listing-adder)

```bash
rm /etc/nginx/sites-enabled/listing-adder
```

#### 9. Deploy

```bash
bash deploy/deploy.sh
```

This script (on every deploy):
- `git pull`
- `pip install`
- `migrate`
- `collectstatic`
- Generates `/etc/nginx/sites-available/admin4gamers.com` from `deploy/nginx/site.conf.template`
- Installs/updates systemd services
- Restarts `ecom-gunicorn`, `ecom-dropship`, `ecom-scheduler`
- Reloads nginx

---

### Subsequent deploys

```bash
bash deploy/deploy.sh
```

---

### phpMyAdmin — SSH tunnel access

phpMyAdmin is **not** accessible via the web. Connect via SSH tunnel:

```bash
ssh -L 8082:127.0.0.1:8082 root@admin4gamers.com
```

Then open `http://localhost:8082` in your browser.

To apply the localhost-only port binding to the running container (one-time):
```bash
# On the server — does NOT touch the database or its data
docker-compose -f docker-compose.yml up -d phpmyadmin
```

---

### Useful commands

```bash
# Service logs
journalctl -u ecom-gunicorn  -n 100 -f
journalctl -u ecom-dropship  -n 100 -f
journalctl -u ecom-scheduler -n 100 -f

# Service status
systemctl status ecom-gunicorn ecom-dropship ecom-scheduler

# Nginx logs
tail -f /var/log/nginx/admin4gamers.com.access.log
tail -f /var/log/nginx/admin4gamers.com.error.log

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
│   │   └── site.conf.template    Nginx template (${DOMAIN} substituted at deploy)
│   ├── systemd/
│   │   ├── ecom-gunicorn.service
│   │   ├── ecom-dropship.service
│   │   └── ecom-scheduler.service
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

# AGENTS.md

## Cursor Cloud specific instructions

Django e-commerce / game-account inventory management system. Server-rendered
(Django templates + Alpine.js + Tailwind); no separate JS build. Standard
setup/run commands live in `README.md`; only non-obvious caveats are below.

### Database: use MySQL in dev, not SQLite
Despite the README calling SQLite the dev default, migrations are **not**
SQLite-compatible: `backend/apps/posting/migrations/0025_image_preset_shared_per_game.py`
uses MySQL-only `UPDATE ... JOIN` raw SQL, so `manage.py migrate` fails on
SQLite with `near "t1": syntax error`. Develop against MySQL.

MySQL 8 is installed as a system package (persists in the VM snapshot) and must
be started each session (not done by the update script):
```
sudo service mysql start
```
Local DB config: root / `devpassword`, database `inventory_manager`, on
`127.0.0.1:3306`. If the socket dir is missing after boot:
`sudo mkdir -p /var/run/mysqld && sudo chown mysql:mysql /var/run/mysqld`.

### Environment file
`.env` is gitignored — copy `.env.example` to `.env`, set
`DB_ENGINE=django.db.backends.mysql` and `DB_PORT=3306`, and generate
`CREDENTIAL_ENCRYPTION_KEY` (Fernet) and `DJANGO_SECRET_KEY`. `python-decouple`
reads `.env` from the current working directory, so **run all `manage.py` and
`pytest` commands from the repo root**.

### Running
Activate the venv (`source venv/bin/activate`), then from the repo root:
`python backend/manage.py runserver`. App at `:8000`, admin at `/admin/`.
A dev superuser is `admin` / `Admin12345` (recreate with `createsuperuser` if the
DB is reset).

### Tests / lint
Run `python -m pytest tests/unit` from the repo root; lib suites are
`libs/payload_pipeline/tests` and `libs/apis_sdk/tests`. Lint tools: `flake8`,
`black`, `isort` (dev requirements). DB-backed tests create a `test_inventory_manager`
MySQL database automatically; if it gets into a bad state, drop it and re-run
with `--create-db`.

### Known pre-existing failures (not environment issues)
- There is a **missing migration**: `DropshipTargetURL.seller_username` exists on
  the model but no migration adds the column (`manage.py makemigrations --check`
  reports it). This makes `tests/unit/test_scheduler_models.py` error at setup
  (`Unknown column 'dropship_target_urls.seller_username'`).
- `tests/unit/test_credentials_parser.py` and several
  `libs/payload_pipeline/tests` (valorant/ubisoft) have pre-existing assertion
  failures unrelated to setup.

### Optional / heavy, safe to skip for most work
The R6Locker tracker feature needs Xvfb + a real Chrome binary (`nodriver`); the
`ecom-scheduler` / `ecom-dropship` APScheduler processes and external
marketplace APIs are only needed for live integration flows. None are required
to run or test the web app.

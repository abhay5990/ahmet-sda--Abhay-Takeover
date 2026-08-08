# AGENTS.md

## Cursor Cloud specific instructions

- Use the repo setup script (also the Cloud Agent `install` command): `bash scripts/setup_dev_env.sh`
- Activate the venv before Django/pytest commands: `source venv/bin/activate`
- Default local DB is SQLite (`DB_ENGINE=django.db.backends.sqlite3`). MySQL via `docker compose up -d` is optional.
- App: `python backend/manage.py runserver` → http://localhost:8000 (admin at `/admin/`)
- Unit tests: `python -m pytest tests/unit -q` (some scheduler DB tests may fail on partial schemas; prefer targeted tests for the area you change)
- Do not commit `.env`, `venv/`, or SQLite DB files
- Secrets for marketplace APIs belong in Cursor Secrets / local `.env`, never in git

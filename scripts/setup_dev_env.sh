#!/usr/bin/env bash
# Idempotent local / Cursor Cloud Agent environment setup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! python3 -c "import venv" 2>/dev/null; then
  echo "python3-venv is required (e.g. apt install python3.12-venv)" >&2
  exit 1
fi

if [[ ! -d venv ]]; then
  python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

python -m pip install -q --upgrade pip
pip install -q -r requirements/dev.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  # Prefer a clear SQLite filename in local/dev when using the sqlite engine.
  if grep -q '^DB_ENGINE=django.db.backends.sqlite3' .env; then
    sed -i 's/^DB_NAME=inventory_manager$/DB_NAME=db.sqlite3/' .env
  fi
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  FERNET="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${SECRET}|" .env
  sed -i "s|^CREDENTIAL_ENCRYPTION_KEY=.*|CREDENTIAL_ENCRYPTION_KEY=${FERNET}|" .env
  echo "Created .env with generated DJANGO_SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY"
fi

mkdir -p backend/logs
python backend/manage.py migrate --noinput
python backend/manage.py check

echo "Environment ready. Activate with: source venv/bin/activate"
echo "Run server: python backend/manage.py runserver"

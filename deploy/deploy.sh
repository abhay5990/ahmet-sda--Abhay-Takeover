#!/usr/bin/env bash
# Usage: bash deploy/deploy.sh
# Run from the repo root or any subdirectory — script finds the root itself.
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

VENV="$REPO_DIR/venv/bin"
MANAGE="$VENV/python $REPO_DIR/backend/manage.py"

# ── Guards ────────────────────────────────────────────────────────────────────
[ -f .env ]             || error ".env not found. Copy .env.example and fill in values."
[ -x "$VENV/python" ]   || error "venv not found at $VENV. Run: python3 -m venv venv && venv/bin/pip install -r requirements/prod.txt"
[ -x "$VENV/gunicorn" ] || error "gunicorn not in venv. Run: venv/bin/pip install -r requirements/prod.txt"
command -v envsubst >/dev/null || error "envsubst not found. Run: apt install gettext-base"

# ── Load env ──────────────────────────────────────────────────────────────────
set -a; source .env; set +a
DOMAIN="${DOMAIN:?DOMAIN is not set in .env}"

# PROJECT_DIR: auto-detected from repo root, overridable via .env
export PROJECT_DIR="${PROJECT_DIR:-$REPO_DIR}"
info "PROJECT_DIR = $PROJECT_DIR"

# ── 0. Ensure log directory exists ───────────────────────────────────────────
mkdir -p "$REPO_DIR/backend/logs"

# ── 1. Git pull ───────────────────────────────────────────────────────────────
info "Pulling latest code..."
git pull origin "$(git rev-parse --abbrev-ref HEAD)"

# ── 2. System packages (Xvfb for Cloudflare bypass) ──────────────────────────
if ! command -v Xvfb >/dev/null 2>&1; then
    info "Installing Xvfb (required for Cloudflare cookie resolution)..."
    apt-get install -y -qq xvfb >/dev/null 2>&1 || warn "Could not install xvfb — install manually: apt-get install -y xvfb"
fi

# ── 3. Dependencies ───────────────────────────────────────────────────────────
info "Installing Python dependencies..."
"$VENV/pip" install -q -r requirements/prod.txt

# ── 4. Django: migrate + collectstatic ───────────────────────────────────────
info "Running migrations..."
cd backend
$MANAGE migrate --noinput

info "Collecting static files..."
$MANAGE collectstatic --noinput --clear
cd "$REPO_DIR"

# ── 5. Nginx config ───────────────────────────────────────────────────────────
info "Generating nginx config for ${DOMAIN}..."

NGINX_AVAILABLE="/etc/nginx/sites-available/${DOMAIN}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${DOMAIN}"
NGINX_OLD_LISTING="/etc/nginx/sites-enabled/listing-adder"

# Warn if the old listing-adder config is still active (domain conflict)
if [ -L "$NGINX_OLD_LISTING" ] || [ -f "$NGINX_OLD_LISTING" ]; then
    warn "listing-adder is still enabled and owns ${DOMAIN}."
    warn "Run this first, then re-run deploy.sh:"
    warn "  rm /etc/nginx/sites-enabled/listing-adder"
    error "Aborting to prevent nginx conflict."
fi

# envsubst only replaces ${DOMAIN} and ${PROJECT_DIR} — all nginx $variables are preserved
envsubst '${DOMAIN} ${PROJECT_DIR}' < deploy/nginx/site.conf.template \
    | tee "$NGINX_AVAILABLE" > /dev/null

if [ ! -L "$NGINX_ENABLED" ]; then
    ln -s "$NGINX_AVAILABLE" "$NGINX_ENABLED"
    info "Nginx site enabled: ${DOMAIN}"
fi

info "Testing nginx config..."
nginx -t || error "Nginx config test failed. Fix the error above and re-run."

# ── 6. Systemd services ───────────────────────────────────────────────────────
SYSTEMD_DIR="/etc/systemd/system"
SERVICES=(ecom-gunicorn ecom-dropship ecom-scheduler)
CHANGED=0

for svc in "${SERVICES[@]}"; do
    SRC="$REPO_DIR/deploy/systemd/${svc}.service"
    DST="$SYSTEMD_DIR/${svc}.service"
    # Substitute ${PROJECT_DIR} and ${GUNICORN_WORKERS} in service templates
    RENDERED=$(envsubst '${PROJECT_DIR} ${GUNICORN_WORKERS}' < "$SRC")
    if [ ! -f "$DST" ] || [ "$RENDERED" != "$(cat "$DST")" ]; then
        echo "$RENDERED" > "$DST"
        CHANGED=1
        info "Installed ${svc}.service"
    fi
done

[ $CHANGED -eq 1 ] && systemctl daemon-reload

for svc in "${SERVICES[@]}"; do
    systemctl enable "$svc" --quiet 2>/dev/null || true
done

# ── 7. Restart app services ───────────────────────────────────────────────────
info "Restarting application services..."
for svc in "${SERVICES[@]}"; do
    systemctl restart "$svc"
done

# ── 8. Start or reload nginx ─────────────────────────────────────────────────
if systemctl is-active --quiet nginx; then
    info "Reloading nginx..."
    systemctl reload nginx
else
    info "Starting nginx..."
    systemctl enable nginx --quiet
    systemctl start nginx
fi

# ── 9. Status ─────────────────────────────────────────────────────────────────
echo ""
info "═══ Service Status ═════════════════════════════"
ALL_OK=true
for svc in "${SERVICES[@]}" nginx; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    if [ "$STATUS" = "active" ]; then
        echo -e "  ${GREEN}✓${NC} $svc"
    else
        echo -e "  ${RED}✗${NC} $svc  ($STATUS)"
        ALL_OK=false
    fi
done
echo ""

if $ALL_OK; then
    info "Deploy complete → https://${DOMAIN}"
else
    warn "Some services are not running. Check with: journalctl -u <service> -n 50"
fi

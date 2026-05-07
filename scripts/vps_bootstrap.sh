#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="amsterdam-house-bot"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_USER="amsterdambot"
SERVICE_HOME="/home/${SERVICE_USER}"
APP_DIR="/opt/${APP_NAME}"
ENV_DIR="/etc/${APP_NAME}"
ENV_FILE="${ENV_DIR}/bot.env"
DATA_DIR="/var/lib/${APP_NAME}"
DB_PATH="${DATA_DIR}/listings.db"
UV_BIN="/usr/local/bin/uv"
SERVICE_ENV=("HOME=${SERVICE_HOME}" "XDG_CACHE_HOME=${SERVICE_HOME}/.cache")

ARCHIVE_PATH="${1:-}"
UPLOADED_ENV="${2:-}"
STAGING_DIR="/tmp/${APP_NAME}-release"

log() {
    printf '\n[%s] %s\n' "$APP_NAME" "$*"
}

if [[ "$(id -u)" -ne 0 ]]; then
    echo "This bootstrap script must be run as root." >&2
    exit 1
fi

if [[ -z "${ARCHIVE_PATH}" || ! -f "${ARCHIVE_PATH}" ]]; then
    echo "Deployment archive not found: ${ARCHIVE_PATH}" >&2
    exit 1
fi

if [[ -z "${UPLOADED_ENV}" || ! -f "${UPLOADED_ENV}" ]]; then
    echo "Uploaded environment file not found: ${UPLOADED_ENV}" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

log "Installing base system packages"
apt-get update
apt-get install -y ca-certificates curl unzip rsync xz-utils build-essential

if ! command -v "${UV_BIN}" >/dev/null 2>&1; then
    log "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
    env UV_INSTALL_DIR=/usr/local/bin sh /tmp/uv-install.sh
    rm -f /tmp/uv-install.sh
else
    log "uv is already installed"
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    log "Creating service user ${SERVICE_USER}"
    useradd \
        --system \
        --create-home \
        --home-dir "${SERVICE_HOME}" \
        --shell /usr/sbin/nologin \
        "${SERVICE_USER}"
fi

log "Extracting release archive"
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"
unzip -q "${ARCHIVE_PATH}" -d "${STAGING_DIR}"

log "Installing application files"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0755 "${APP_DIR}"
if systemctl list-unit-files "${SERVICE_NAME}" >/dev/null 2>&1; then
    systemctl stop "${SERVICE_NAME}" || true
fi
rsync -a --delete --exclude ".venv/" "${STAGING_DIR}/" "${APP_DIR}/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

log "Installing environment and data directories"
install -d -o root -g "${SERVICE_USER}" -m 0750 "${ENV_DIR}"
install -m 0640 -o root -g "${SERVICE_USER}" "${UPLOADED_ENV}" "${ENV_FILE}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 "${DATA_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 "${SERVICE_HOME}/.cache"

cd "${APP_DIR}"

log "Installing Python 3.13 with uv"
runuser -u "${SERVICE_USER}" -- env "${SERVICE_ENV[@]}" "${UV_BIN}" python install 3.13

log "Installing Python dependencies"
runuser -u "${SERVICE_USER}" -- env "${SERVICE_ENV[@]}" UV_LINK_MODE=copy "${UV_BIN}" sync --locked --python 3.13

log "Installing Playwright system dependencies"
"${APP_DIR}/.venv/bin/python" -m playwright install-deps chromium

log "Installing browser assets"
runuser -u "${SERVICE_USER}" -- env "${SERVICE_ENV[@]}" "${APP_DIR}/.venv/bin/python" -m playwright install chromium
runuser -u "${SERVICE_USER}" -- env "${SERVICE_ENV[@]}" "${APP_DIR}/.venv/bin/python" -m camoufox fetch

log "Installing systemd service"
install -m 0644 "${APP_DIR}/deploy/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 3
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log "Service is running. SQLite database path: ${DB_PATH}"
else
    log "Service failed to start. Recent logs:"
    journalctl -u "${SERVICE_NAME}" -n 100 --no-pager
    exit 1
fi

rm -rf "${STAGING_DIR}" "${ARCHIVE_PATH}" "${UPLOADED_ENV}"
log "Bootstrap complete"

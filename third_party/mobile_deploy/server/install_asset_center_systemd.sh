#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_DIR="${ROOT_DIR}/third_party/mobile_asset_center"
INSTALL_DIR="${INSTALL_DIR:-/opt/mobile_asset_center}"
ENV_FILE="${INSTALL_DIR}/asset-center.env"
VENV_DIR="${INSTALL_DIR}/.venv"
SERVICE_FILE="/etc/systemd/system/mobile-asset-center.service"
NGINX_FILE="/etc/nginx/conf.d/mobile-asset-center.conf"
HOST_NAME="${HOST_NAME:-_}"

mkdir -p "${INSTALL_DIR}/logs" "${INSTALL_DIR}/data"
rsync -a --delete \
  --exclude ".env*" \
  --exclude "asset-center.env" \
  --exclude "data/" \
  --exclude "logs/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  "${APP_DIR}/" "${INSTALL_DIR}/"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT_DIR}/third_party/mobile_deploy/server/asset-center.env.example" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Fill in PG/OSS credentials, then rerun."
  exit 1
fi

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -e "${INSTALL_DIR}[cloud]"

cat > "${SERVICE_FILE}" <<SERVICE
[Unit]
Description=Mobile Asset Center
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python -m mobile_asset_center serve --env-file ${ENV_FILE} --host 127.0.0.1 --port 8876 --data-root ${INSTALL_DIR}/data --static-root ${INSTALL_DIR}/frontend
Restart=always
RestartSec=3
StandardOutput=append:${INSTALL_DIR}/logs/asset-center.out.log
StandardError=append:${INSTALL_DIR}/logs/asset-center.err.log

[Install]
WantedBy=multi-user.target
SERVICE

if command -v nginx >/dev/null 2>&1; then
  cat > "${NGINX_FILE}" <<NGINX
server {
    listen 80;
    server_name ${HOST_NAME};

    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:8876;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
  nginx -t
  systemctl reload nginx || systemctl restart nginx
else
  echo "nginx not found; install nginx to expose the asset center on port 80."
fi

systemctl daemon-reload
systemctl enable --now mobile-asset-center
systemctl restart mobile-asset-center

echo "Asset center service started."
echo "Check status: systemctl status mobile-asset-center"

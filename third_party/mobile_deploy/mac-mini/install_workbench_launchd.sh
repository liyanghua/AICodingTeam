#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_DIR="${ROOT_DIR}/third_party/mobile_image_workbench"
XHS_DIR="${ROOT_DIR}/third_party/xhs_collector"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${APP_DIR}/.env"
LABEL="com.ontology.mobile-image-workbench"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${APP_DIR}/logs"

mkdir -p "${LOG_DIR}" "${APP_DIR}/runs" "${HOME}/Library/LaunchAgents"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT_DIR}/third_party/mobile_deploy/mac-mini/workbench.env.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Fill in MWB_CLOUD_* and DASHSCOPE_API_KEY, then rerun."
  exit 1
fi

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -e "${XHS_DIR}" -e "${APP_DIR}" uiautomator2 pillow opencv-python

cd "${APP_DIR}"
npm install
npm run build

launchctl bootout "gui/$(id -u)" "${PLIST}" >/dev/null 2>&1 || true

cat > "${PLIST}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${APP_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>${APP_DIR}:${XHS_DIR}</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_DIR}/bin/python</string>
    <string>-m</string>
    <string>mobile_image_workbench</string>
    <string>serve</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8765</string>
    <string>--runs-root</string>
    <string>${APP_DIR}/runs</string>
    <string>--static-root</string>
    <string>${APP_DIR}/frontend/dist</string>
  </array>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/workbench.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/workbench.err.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
PLIST

set -a
source "${ENV_FILE}"
set +a

launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Workbench started at http://$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1):8765"
echo "Check status: launchctl print gui/$(id -u)/${LABEL}"

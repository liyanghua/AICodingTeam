#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_DIR="${ROOT_DIR}/third_party/mobile_image_workbench"
XHS_DIR="${ROOT_DIR}/third_party/xhs_collector"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${MWB_ENV_FILE:-${APP_DIR}/.env}"
if [[ "${ENV_FILE}" != /* ]]; then
  ENV_FILE="${ROOT_DIR}/${ENV_FILE}"
fi
LABEL="com.ontology.mobile-image-workbench"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${APP_DIR}/logs"

mkdir -p "${LOG_DIR}" "${APP_DIR}/runs" "${HOME}/Library/LaunchAgents"

if [[ ! -f "${ENV_FILE}" ]]; then
  mkdir -p "$(dirname "${ENV_FILE}")"
  cp "${ROOT_DIR}/third_party/mobile_deploy/mac-mini/workbench.mac-mini.env.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Fill in MWB_CLOUD_* and DASHSCOPE_API_KEY, then rerun."
  exit 1
fi

load_dotenv() {
  local env_file="$1"
  ROOT_DIR="${ROOT_DIR}" ENV_FILE="${env_file}" python3 - <<'PY'
import os
from pathlib import Path
import shlex
import sys

root = Path(os.environ["ROOT_DIR"])
env_file = Path(os.environ["ENV_FILE"])
sys.path.insert(0, str(root / "third_party/mobile_image_workbench/backend"))
from mobile_image_workbench.env import load_env_file

load_env_file(env_file)
for name in (
    "MWB_PYTHON_BIN",
    "MWB_PIP_INDEX_URL",
    "MWB_PIP_EXTRA_INDEX_URL",
    "MWB_PIP_TRUSTED_HOST",
    "ANDROID_HOME",
):
    if name in os.environ:
        print(f"export {name}={shlex.quote(os.environ[name])}")
PY
}

eval "$(load_dotenv "${ENV_FILE}")"

ANDROID_HOME_DIR="${ANDROID_HOME:-${HOME}/Library/Android/sdk}"
PLATFORM_TOOLS_DIR="${ANDROID_HOME_DIR}/platform-tools"
SERVICE_PATH="${PLATFORM_TOOLS_DIR}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

choose_python() {
  if [[ -n "${MWB_PYTHON_BIN:-}" ]]; then
    echo "${MWB_PYTHON_BIN}"
    return
  fi
  for candidate in \
    python3.12 \
    python3.11 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      echo "${candidate}"
      return
    fi
  done
  echo ""
}

python_version_ok() {
  "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

pip_tooling_ready() {
  "$1" - <<'PY'
from importlib import metadata


def version_tuple(name):
    try:
        raw = metadata.version(name)
    except metadata.PackageNotFoundError:
        return ()
    parts = []
    for chunk in raw.split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


pip_ok = bool(version_tuple("pip"))
setuptools_ok = version_tuple("setuptools") >= (69,)
wheel_ok = bool(version_tuple("wheel"))
raise SystemExit(0 if pip_ok and setuptools_ok and wheel_ok else 1)
PY
}

python_certificates_ready() {
  "$1" - <<'PY'
from pathlib import Path
import ssl

try:
    import certifi
except Exception:
    raise SystemExit(1)

certifi_path = Path(certifi.where())
openssl_cafile = ssl.get_default_verify_paths().openssl_cafile
if certifi_path.exists() and openssl_cafile and Path(openssl_cafile).exists():
    raise SystemExit(0)
raise SystemExit(1)
PY
}

PYTHON_BIN="$(choose_python)"
if [[ -z "${PYTHON_BIN}" ]] || ! python_version_ok "${PYTHON_BIN}"; then
  echo "Python 3.11+ is required. Set MWB_PYTHON_BIN in ${ENV_FILE} or install Python 3.12."
  exit 1
fi

install_python_certificates() {
  local python_bin="$1"
  if python_certificates_ready "${python_bin}"; then
    echo "Python SSL certificates already available; skipping certificate installer."
    return
  fi
  local python_prefix
  local python_version
  python_prefix="$("${python_bin}" - <<'PY'
import sys
from pathlib import Path
print(Path(sys.prefix).resolve())
PY
)"
  python_version="$("${python_bin}" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  local candidates=(
    "${python_prefix}/Install Certificates.command"
    "/Applications/Python ${python_version}/Install Certificates.command"
    "/Applications/Python 3.12/Install Certificates.command"
    "/Applications/Python 3.11/Install Certificates.command"
  )
  local cert_script
  for cert_script in "${candidates[@]}"; do
    if [[ ! -f "${cert_script}" ]]; then
      continue
    fi
    echo "Ensuring Python SSL certificates via ${cert_script}"
    if /bin/bash "${cert_script}"; then
      return
    fi
    echo "Python certificate installer failed; continuing with configured pip network options."
    return
  done
  echo "No Python certificate installer found; continuing with existing trust store."
}

configure_pip_env() {
  if [[ -n "${MWB_PIP_INDEX_URL:-}" ]]; then
    export PIP_INDEX_URL="${MWB_PIP_INDEX_URL}"
  fi
  if [[ -n "${MWB_PIP_EXTRA_INDEX_URL:-}" ]]; then
    export PIP_EXTRA_INDEX_URL="${MWB_PIP_EXTRA_INDEX_URL}"
  fi
  if [[ -n "${MWB_PIP_TRUSTED_HOST:-}" ]]; then
    export PIP_TRUSTED_HOST="${MWB_PIP_TRUSTED_HOST//,/ }"
  fi
}

if [[ -x "${VENV_DIR}/bin/python" ]] && ! python_version_ok "${VENV_DIR}/bin/python"; then
  echo "Removing incompatible venv at ${VENV_DIR}; Python 3.11+ is required."
  rm -rf "${VENV_DIR}"
fi

echo "Using Python: $(${PYTHON_BIN} -V 2>&1)"
install_python_certificates "${PYTHON_BIN}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
configure_pip_env
if pip_tooling_ready "${VENV_DIR}/bin/python"; then
  echo "pip tooling already available; skipping upgrade."
else
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
fi
"${VENV_DIR}/bin/python" -m pip install uiautomator2 pillow opencv-python
"${VENV_DIR}/bin/python" -m pip install --no-build-isolation -e "${XHS_DIR}" -e "${APP_DIR}"

cd "${APP_DIR}"
if command -v npm >/dev/null 2>&1; then
  npm install
  npm run build
elif [[ -f "${APP_DIR}/frontend/dist/index.html" ]]; then
  echo "npm not found; using existing frontend/dist."
else
  echo "npm is required because frontend/dist/index.html is missing. Install Node.js/npm or build frontend/dist before deployment."
  exit 1
fi

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
    <key>PATH</key>
    <string>${SERVICE_PATH}</string>
    <key>ANDROID_HOME</key>
    <string>${ANDROID_HOME_DIR}</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_DIR}/bin/python</string>
    <string>-m</string>
    <string>mobile_image_workbench</string>
    <string>serve</string>
    <string>--env-file</string>
    <string>${ENV_FILE}</string>
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

launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Workbench started at http://$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1):8765"
echo "Check status: launchctl print gui/$(id -u)/${LABEL}"

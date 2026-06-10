#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PRIMARY_VENV_DIR="${BACKEND_DIR}/.venv-jp46"
FALLBACK_VENV_DIR="${BACKEND_DIR}/.venv-jp46-native"
VENV_DIR="${PRIMARY_VENV_DIR}"

if [[ ! -d "${VENV_DIR}" && -d "${FALLBACK_VENV_DIR}" ]]; then
  echo "⚠️  ${PRIMARY_VENV_DIR} not found. Falling back to ${FALLBACK_VENV_DIR}."
  VENV_DIR="${FALLBACK_VENV_DIR}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "❌ JetPack 4.6 venv not found. Expected one of:"
  echo "   - ${PRIMARY_VENV_DIR}"
  echo "   - ${FALLBACK_VENV_DIR}"
  echo "Run setup_jetpack46_native.sh first."
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

if ! python - <<'PY' >/dev/null 2>&1
import cv2  # noqa: F401
PY
then
  echo "❌ Active venv does not provide cv2/OpenCV (required for camera capture)."
  echo "Re-run setup_jetpack46_native.sh to recreate ${PRIMARY_VENV_DIR} with system-site-packages."
  exit 1
fi

# Optional source selection:
#   export CAMERA_SOURCE=usb
#   export CAMERA_SOURCE=csi
# Optional full custom pipeline:
#   export GST_PIPELINE_OVERRIDE='v4l2src device=/dev/video0 ! ... ! appsink'

export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"
# JP4.6 safe defaults: prefer compatibility path and avoid startup probe delays.
export CAMERA_SOURCE="${CAMERA_SOURCE:-usb}"
export CAMERA_ACCELERATION="${CAMERA_ACCELERATION:-compat}"
export CAMERA_USB_STARTUP_PROBE="${CAMERA_USB_STARTUP_PROBE:-false}"

cleanup_video0_locks() {
  local camera_dev="${CAMERA_DEVICE:-/dev/video0}"
  if [[ ! -e "${camera_dev}" ]]; then
    return 0
  fi

  echo "Checking for existing camera lock holders on ${camera_dev} ..."

  # fuser may print all PIDs on one line; normalize and kill gracefully.
  if command -v fuser >/dev/null 2>&1; then
    mapfile -t lock_pids < <(
      fuser "${camera_dev}" 2>/dev/null \
        | tr ' ' '\n' \
        | grep -E '^[0-9]+$' \
        | sort -u || true
    )

    if [[ ${#lock_pids[@]} -gt 0 ]]; then
      echo "Found lock holders: ${lock_pids[*]}"
      for pid in "${lock_pids[@]}"; do
        if [[ "${pid}" != "$$" ]]; then
          kill -TERM "${pid}" 2>/dev/null || true
        fi
      done
      sleep 1
      for pid in "${lock_pids[@]}"; do
        if [[ "${pid}" != "$$" ]]; then
          kill -KILL "${pid}" 2>/dev/null || true
        fi
      done
    fi
  fi

  # Extra cleanup for stale uvicorn workers started from this project by same user.
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
}

cleanup_video0_locks

echo "Starting backend on ${API_HOST}:${API_PORT} (CAMERA_SOURCE=${CAMERA_SOURCE})"
exec python -m uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${BACKEND_DIR}/.venv-jp46"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "❌ Venv not found at ${VENV_DIR}. Run setup_jetpack46_native.sh first."
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Optional source selection:
#   export CAMERA_SOURCE=usb
#   export CAMERA_SOURCE=csi
# Optional full custom pipeline:
#   export GST_PIPELINE_OVERRIDE='v4l2src device=/dev/video0 ! ... ! appsink'

export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"

echo "Starting backend on ${API_HOST}:${API_PORT} (CAMERA_SOURCE=${CAMERA_SOURCE:-usb})"
exec python -m uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}"

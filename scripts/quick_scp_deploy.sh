#!/usr/bin/env bash
set -euo pipefail

# Fast field deployment helper:
# - Pushes backend app code from local repo to remote project path
# - Pushes prebuilt frontend dist and hot-swaps it into running nginx container
# - Restarts backend/frontend containers (no image rebuild)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_USER="saurabh"
REMOTE_HOST=""
REMOTE_PORT="22"
REMOTE_PROJECT_DIR="/home/saurabh/POC_Project_1"
REMOTE_TMP_DIR="/tmp/poc_field_deploy"
AUTO_DETECT_RUNTIME_DIR="true"

usage() {
  cat <<'EOF'
Usage: ./scripts/quick_scp_deploy.sh --host <jetson_ip> [options]

Options:
  --host <ip_or_dns>         Jetson hostname/IP (required)
  --user <ssh_user>          SSH user (default: saurabh)
  --port <ssh_port>          SSH port (default: 22)
  --remote-dir <path>        Remote project path (default: /home/saurabh/POC_Project_1)
  --no-auto-detect           Disable runtime mount auto-detection
  --help                     Show this help

Notes:
  - This script expects frontend build output at frontend/dist.
  - Build frontend once before running:
      cd frontend && npm run build
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      REMOTE_HOST="${2:-}"
      shift 2
      ;;
    --user)
      REMOTE_USER="${2:-}"
      shift 2
      ;;
    --port)
      REMOTE_PORT="${2:-}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --no-auto-detect)
      AUTO_DETECT_RUNTIME_DIR="false"
      shift 1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[quick-deploy] Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${REMOTE_HOST}" ]]; then
  echo "[quick-deploy] ERROR: --host is required"
  usage
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}/frontend/dist" ]]; then
  echo "[quick-deploy] ERROR: frontend/dist not found."
  echo "[quick-deploy] Run: cd frontend && npm run build"
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}/backend/app" ]]; then
  echo "[quick-deploy] ERROR: backend/app not found at ${PROJECT_DIR}"
  exit 1
fi

LOCAL_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/poc_quick_deploy.XXXXXX")"
cleanup() {
  rm -rf "${LOCAL_TMP_DIR}"
}
trap cleanup EXIT

echo "[quick-deploy] Packaging backend and frontend artifacts..."
COPYFILE_DISABLE=1 tar -czf "${LOCAL_TMP_DIR}/backend_app.tgz" -C "${PROJECT_DIR}" backend/app
COPYFILE_DISABLE=1 tar -czf "${LOCAL_TMP_DIR}/frontend_dist.tgz" -C "${PROJECT_DIR}/frontend" dist

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SSH_OPTS=(-p "${REMOTE_PORT}")
SCP_OPTS=(-P "${REMOTE_PORT}")

if [[ "${AUTO_DETECT_RUNTIME_DIR}" == "true" ]]; then
  DETECTED_DIR="$(ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "python3 - <<'PY'
import json
import subprocess

try:
    out = subprocess.check_output(
        ['docker', 'inspect', 'jetson-nano-backend', '--format', '{{json .Mounts}}'],
        stderr=subprocess.DEVNULL,
    ).decode().strip()
    mounts = json.loads(out) if out else []
    for mount in mounts:
        if mount.get('Destination') == '/app' and mount.get('Type') == 'bind':
            source = str(mount.get('Source') or '')
            if source.endswith('/backend'):
                print(source[:-len('/backend')])
            else:
                print(source)
            raise SystemExit(0)
except Exception:
    pass
PY" 2>/dev/null || true)"
  DETECTED_DIR="$(echo "${DETECTED_DIR}" | tr -d '\r' | awk 'NF{print; exit}')"
  if [[ -n "${DETECTED_DIR}" ]]; then
    if [[ "${DETECTED_DIR}" != "${REMOTE_PROJECT_DIR}" ]]; then
      echo "[quick-deploy] INFO: runtime mount path detected: ${DETECTED_DIR}"
      echo "[quick-deploy] INFO: overriding remote project path for this deployment."
    fi
    REMOTE_PROJECT_DIR="${DETECTED_DIR}"
  fi
fi

echo "[quick-deploy] Creating remote temp dir: ${REMOTE_TMP_DIR}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_TMP_DIR}'"

echo "[quick-deploy] Uploading artifacts to ${SSH_TARGET}..."
scp "${SCP_OPTS[@]}" "${LOCAL_TMP_DIR}/backend_app.tgz" "${SSH_TARGET}:${REMOTE_TMP_DIR}/backend_app.tgz"
scp "${SCP_OPTS[@]}" "${LOCAL_TMP_DIR}/frontend_dist.tgz" "${SSH_TARGET}:${REMOTE_TMP_DIR}/frontend_dist.tgz"

echo "[quick-deploy] Applying update on remote host..."
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "REMOTE_PROJECT_DIR='${REMOTE_PROJECT_DIR}' REMOTE_TMP_DIR='${REMOTE_TMP_DIR}' bash -s" <<'EOF'
set -euo pipefail

if [[ ! -d "${REMOTE_PROJECT_DIR}" ]]; then
  echo "[quick-deploy][remote] ERROR: project directory not found: ${REMOTE_PROJECT_DIR}"
  exit 1
fi

if [[ ! -f "${REMOTE_TMP_DIR}/backend_app.tgz" || ! -f "${REMOTE_TMP_DIR}/frontend_dist.tgz" ]]; then
  echo "[quick-deploy][remote] ERROR: missing uploaded artifacts in ${REMOTE_TMP_DIR}"
  exit 1
fi

echo "[quick-deploy][remote] Updating backend app files..."
tar -xzf "${REMOTE_TMP_DIR}/backend_app.tgz" -C "${REMOTE_PROJECT_DIR}"

echo "[quick-deploy][remote] Preparing frontend dist files..."
rm -rf "${REMOTE_TMP_DIR}/frontend_dist_unpack"
mkdir -p "${REMOTE_TMP_DIR}/frontend_dist_unpack"
tar -xzf "${REMOTE_TMP_DIR}/frontend_dist.tgz" -C "${REMOTE_TMP_DIR}/frontend_dist_unpack"

if docker ps --format '{{.Names}}' | awk '$0=="jetson-nano-backend"{found=1} END{exit found?0:1}'; then
  echo "[quick-deploy][remote] Restarting backend container..."
  docker restart jetson-nano-backend >/dev/null
else
  echo "[quick-deploy][remote] WARN: backend container jetson-nano-backend is not running"
fi

if docker ps --format '{{.Names}}' | awk '$0=="jetson-nano-frontend"{found=1} END{exit found?0:1}'; then
  echo "[quick-deploy][remote] Hot-swapping frontend dist into container..."
  docker cp "${REMOTE_TMP_DIR}/frontend_dist_unpack/dist/." jetson-nano-frontend:/usr/share/nginx/html/
  echo "[quick-deploy][remote] Restarting frontend container..."
  docker restart jetson-nano-frontend >/dev/null
else
  echo "[quick-deploy][remote] WARN: frontend container jetson-nano-frontend is not running"
fi

echo "[quick-deploy][remote] Cleaning temp artifacts..."
rm -rf "${REMOTE_TMP_DIR}"
echo "[quick-deploy][remote] Update complete."
EOF

echo "[quick-deploy] SUCCESS: quick deploy completed for ${SSH_TARGET}"

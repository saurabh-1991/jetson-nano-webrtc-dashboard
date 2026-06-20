#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_SCRIPT="${ROOT_DIR}/backend/scripts/run_jetpack46_native.sh"
FRONTEND_DIR="${ROOT_DIR}/frontend"
STATE_DIR="${ROOT_DIR}/.run"
LOG_DIR="${ROOT_DIR}/logs"

BACKEND_PID_FILE="${STATE_DIR}/native_backend.pid"
FRONTEND_PID_FILE="${STATE_DIR}/native_frontend.pid"
BACKEND_LOG="${LOG_DIR}/backend-native.log"
FRONTEND_LOG="${LOG_DIR}/frontend-native.log"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
TARGET_NODE_MAJOR="${TARGET_NODE_MAJOR:-20}"
FRONTEND_DOCKER_CONTAINER="${FRONTEND_DOCKER_CONTAINER:-jetson-native-frontend-dev}"
NODE_BIN=""
NPM_BIN=""

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

if [[ -f "${BACKEND_SCRIPT}" && ! -x "${BACKEND_SCRIPT}" ]]; then
  chmod +x "${BACKEND_SCRIPT}" 2>/dev/null || true
fi

if [[ ! -x "${BACKEND_SCRIPT}" ]]; then
  echo "❌ Backend launcher not found or not executable: ${BACKEND_SCRIPT}"
  echo "Run: chmod +x ${BACKEND_SCRIPT}"
  exit 1
fi

ensure_node_runtime() {
  local node_version_raw node_semver node_major node_from_nvm node_bin_dir

  resolve_from_system_path() {
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
      node_version_raw="$(node -v 2>/dev/null || echo v0.0.0)"
      node_semver="${node_version_raw#v}"
      node_major="${node_semver%%.*}"
      if [[ "${node_major}" -ge "${TARGET_NODE_MAJOR}" ]]; then
        NODE_BIN="$(command -v node)"
        NPM_BIN="$(command -v npm)"
        return 0
      fi
    fi
    return 1
  }

  resolve_from_nvm_versions() {
    node_bin_dir="$(ls -d "${NVM_DIR}"/versions/node/v${TARGET_NODE_MAJOR}*/bin 2>/dev/null | sort -V | tail -n 1 || true)"
    if [[ -n "${node_bin_dir}" && -x "${node_bin_dir}/node" && -x "${node_bin_dir}/npm" ]]; then
      node_version_raw="$("${node_bin_dir}/node" -v 2>/dev/null || echo v0.0.0)"
      node_semver="${node_version_raw#v}"
      node_major="${node_semver%%.*}"
      if [[ "${node_major}" -ge "${TARGET_NODE_MAJOR}" ]]; then
        NODE_BIN="${node_bin_dir}/node"
        NPM_BIN="${node_bin_dir}/npm"
        return 0
      fi
    fi
    return 1
  }

  if resolve_from_system_path; then
    echo "✅ Using Node.js $("${NODE_BIN}" -v) and npm $("${NPM_BIN}" -v)"
    return 0
  fi

  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if resolve_from_nvm_versions; then
    echo "✅ Using Node.js $("${NODE_BIN}" -v) and npm $("${NPM_BIN}" -v)"
    return 0
  fi

  echo "ℹ️  Node.js ${TARGET_NODE_MAJOR}+ is required for frontend (Vite 7)."
  echo "Attempting automatic setup with nvm ..."

  if [[ ! -s "${NVM_DIR}/nvm.sh" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "❌ curl is required to install nvm automatically."
      return 1
    fi

    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
  fi

  # shellcheck disable=SC1090
  . "${NVM_DIR}/nvm.sh"

  nvm install "${TARGET_NODE_MAJOR}" >/dev/null
  nvm use "${TARGET_NODE_MAJOR}" >/dev/null

  node_from_nvm="$(nvm which "${TARGET_NODE_MAJOR}" 2>/dev/null || true)"
  if [[ -n "${node_from_nvm}" && "${node_from_nvm}" != "N/A" ]]; then
    node_bin_dir="$(dirname "${node_from_nvm}")"
    if [[ -d "${node_bin_dir}" ]]; then
      export PATH="${node_bin_dir}:${PATH}"
      hash -r
    fi
  fi

  if resolve_from_nvm_versions; then
    echo "✅ Using Node.js $("${NODE_BIN}" -v) and npm $("${NPM_BIN}" -v)"
    return 0
  fi

  echo "⚠️  Prebuilt Node ${TARGET_NODE_MAJOR} appears incompatible on this system (likely glibc mismatch)."
  echo "⚠️  Skipping source compile and using Docker frontend fallback."
  return 1

  if resolve_from_system_path; then
    echo "✅ Using Node.js $("${NODE_BIN}" -v) and npm $("${NPM_BIN}" -v)"
    return 0
  fi

  node_version_raw="$(command -v node >/dev/null 2>&1 && node -v 2>/dev/null || echo v0.0.0)"
  if [[ "${node_version_raw#v}" == "0.0.0" ]]; then
    echo "❌ Failed to initialize node/npm via nvm."
  else
    echo "❌ Node.js ${node_version_raw} is still below required major ${TARGET_NODE_MAJOR}."
  fi
  return 1
}

FRONTEND_MODE="native"
if ! ensure_node_runtime; then
  FRONTEND_MODE="docker"
  echo "⚠️  Falling back to Docker-based frontend dev server (${FRONTEND_DOCKER_CONTAINER})."
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "❌ curl is required for health checks."
  exit 1
fi

# Resolve Jetson LAN IP for frontend API base.
JETSON_IP="${JETSON_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if [[ -z "${JETSON_IP}" ]]; then
  JETSON_IP="127.0.0.1"
fi

API_BASE_URL_DEFAULT="http://${JETSON_IP}:${BACKEND_PORT}"
API_BASE_URL="${FRONTEND_API_BASE_URL:-${API_BASE_URL_DEFAULT}}"

cleanup_stale_uvicorn() {
  local pids
  pids="$(ps -eo pid,args | grep 'uvicorn app.main:app' | grep -v grep | awk '{print $1}' || true)"
  if [[ -n "${pids}" ]]; then
    echo "ℹ️  Stopping stale uvicorn processes: ${pids}"
    for pid in ${pids}; do
      if [[ "${pid}" != "$$" && "${pid}" != "${PPID:-0}" ]]; then
        kill -9 "${pid}" 2>/dev/null || true
      fi
    done
  fi
}

# Ensure old processes are not holding ports/camera.
if command -v docker-compose >/dev/null 2>&1; then
  (cd "${ROOT_DIR}" && docker-compose stop jetson-backend jetson-frontend >/dev/null 2>&1) || true
fi
if command -v docker >/dev/null 2>&1; then
  docker rm -f jetson-nano-backend jetson-nano-frontend >/dev/null 2>&1 || true
fi

cleanup_stale_uvicorn
pkill -f "vite.*--port ${FRONTEND_PORT}" 2>/dev/null || true
fuser -k /dev/video0 2>/dev/null || true

# Start backend
nohup "${BACKEND_SCRIPT}" >"${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!
echo "${BACKEND_PID}" >"${BACKEND_PID_FILE}"

# Wait for backend health.
backend_ready=false
for _ in {1..45}; do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    backend_ready=true
    break
  fi
  sleep 1
done

if [[ "${backend_ready}" != "true" ]]; then
  echo "❌ Backend failed to become healthy on port ${BACKEND_PORT}."
  echo "Check logs: ${BACKEND_LOG}"
  exit 1
fi

# Configure frontend API target for this native run.
cat >"${FRONTEND_DIR}/.env.local" <<EOF
VITE_API_BASE_URL=${API_BASE_URL}
EOF

if [[ "${FRONTEND_MODE}" == "native" ]]; then
  # Install deps if needed.
  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "📦 Installing frontend dependencies..."
    (cd "${FRONTEND_DIR}" && "${NPM_BIN}" install)
  fi

  # Start frontend dev server.
  (
    cd "${FRONTEND_DIR}"
    nohup "${NPM_BIN}" run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" >"${FRONTEND_LOG}" 2>&1 &
    echo $! > "${FRONTEND_PID_FILE}"
  )
  FRONTEND_PID="$(cat "${FRONTEND_PID_FILE}")"
else
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker is required for frontend fallback mode but is not installed."
    exit 1
  fi

  docker rm -f "${FRONTEND_DOCKER_CONTAINER}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${FRONTEND_DOCKER_CONTAINER}" \
    -v "${FRONTEND_DIR}:/app" \
    -w /app \
    -p "${FRONTEND_PORT}:5173" \
    node:20-bullseye \
    bash -lc "npm install && npm run dev -- --host 0.0.0.0 --port ${FRONTEND_PORT}" \
    >"${FRONTEND_PID_FILE}"

  FRONTEND_PID="$(cat "${FRONTEND_PID_FILE}")"
  echo "Frontend container: ${FRONTEND_DOCKER_CONTAINER} (${FRONTEND_PID})"
fi

# Wait for frontend port.
frontend_ready=false
for _ in {1..45}; do
  if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
    frontend_ready=true
    break
  fi
  sleep 1
done

if [[ "${frontend_ready}" != "true" ]]; then
  echo "❌ Frontend failed to start on port ${FRONTEND_PORT}."
  echo "Check logs: ${FRONTEND_LOG}"
  exit 1
fi

echo "✅ Native dashboard started"
echo ""
echo "Backend health:  http://127.0.0.1:${BACKEND_PORT}/health"
echo "Frontend local:  http://127.0.0.1:${FRONTEND_PORT}"
echo "Frontend LAN:    http://${JETSON_IP}:${FRONTEND_PORT}"
echo ""
echo "Logs:"
echo "  - ${BACKEND_LOG}"
echo "  - ${FRONTEND_LOG}"
echo ""
echo "To stop: ${ROOT_DIR}/scripts/stop_native_dashboard.sh"
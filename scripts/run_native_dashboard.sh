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

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

if [[ ! -x "${BACKEND_SCRIPT}" ]]; then
  echo "❌ Backend launcher not found or not executable: ${BACKEND_SCRIPT}"
  echo "Run: chmod +x ${BACKEND_SCRIPT}"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm is not installed. Install Node.js/npm first on Jetson."
  exit 1
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

# Ensure old processes are not holding ports/camera.
pkill -f "uvicorn app.main:app" 2>/dev/null || true
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

# Install deps if needed.
if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "📦 Installing frontend dependencies..."
  (cd "${FRONTEND_DIR}" && npm install)
fi

# Start frontend dev server.
nohup bash -lc "cd '${FRONTEND_DIR}' && npm run dev -- --host 0.0.0.0 --port ${FRONTEND_PORT}" >"${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID=$!
echo "${FRONTEND_PID}" >"${FRONTEND_PID_FILE}"

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
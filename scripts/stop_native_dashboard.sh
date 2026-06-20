#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/.run"
FRONTEND_DOCKER_CONTAINER="${FRONTEND_DOCKER_CONTAINER:-jetson-native-frontend-dev}"

BACKEND_PID_FILE="${STATE_DIR}/native_backend.pid"
FRONTEND_PID_FILE="${STATE_DIR}/native_frontend.pid"

kill_from_pidfile() {
  local pid_file="$1"
  local name="$2"

  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      echo "Stopped ${name} (pid ${pid})"
    fi
    rm -f "${pid_file}"
  fi
}

kill_from_pidfile "${FRONTEND_PID_FILE}" "frontend"
kill_from_pidfile "${BACKEND_PID_FILE}" "backend"

# Fallback kill patterns
stale_uvicorn_pids="$(ps -eo pid,args | grep 'uvicorn app.main:app' | grep -v grep | awk '{print $1}' || true)"
if [[ -n "${stale_uvicorn_pids}" ]]; then
  for pid in ${stale_uvicorn_pids}; do
    kill -9 "${pid}" 2>/dev/null || true
  done
fi
pkill -f "vite.*--port 5173" 2>/dev/null || true

if command -v docker >/dev/null 2>&1; then
  docker rm -f "${FRONTEND_DOCKER_CONTAINER}" >/dev/null 2>&1 || true
fi

echo "✅ Native dashboard processes stopped (if running)."
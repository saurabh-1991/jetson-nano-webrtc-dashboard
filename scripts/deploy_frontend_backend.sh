#!/usr/bin/env bash
set -euo pipefail

# Unified deploy helper for field use.
# Deploys frontend and backend together in one command.
# Default path uses NVIDIA runtime backend replacement (recommended on Jetson branch).

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBUILD="false"
USE_NVIDIA_BACKEND="true"
SKIP_VERIFY="false"

print_help() {
  cat <<'EOF'
Usage: ./scripts/deploy_frontend_backend.sh [options]

Options:
  --project-dir <path>   Project root containing docker-compose.yml
  --rebuild              Rebuild images before starting services
  --no-nvidia-backend    Keep backend on compose runtime (no runtime=nvidia replace)
  --skip-verify          Skip post-deploy HTTP and container checks
  --help                 Show this help

Examples:
  ./scripts/deploy_frontend_backend.sh
  ./scripts/deploy_frontend_backend.sh --rebuild
  ./scripts/deploy_frontend_backend.sh --rebuild --no-nvidia-backend

Expected default behavior:
  1) Starts compose services (frontend + aux)
  2) Replaces backend with runtime=nvidia container
  3) Verifies backend/docs and frontend root return HTTP 200
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --rebuild)
      REBUILD="true"
      shift 1
      ;;
    --no-nvidia-backend)
      USE_NVIDIA_BACKEND="false"
      shift 1
      ;;
    --skip-verify)
      SKIP_VERIFY="true"
      shift 1
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "[deploy-all] ERROR: Unknown argument: $1"
      print_help
      exit 1
      ;;
  esac
done

if [[ ! -f "${PROJECT_DIR}/docker-compose.yml" ]]; then
  echo "[deploy-all] ERROR: docker-compose.yml not found in PROJECT_DIR='${PROJECT_DIR}'"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[deploy-all] ERROR: docker is not installed"
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "[deploy-all] ERROR: docker-compose is not installed"
  exit 1
fi

if [[ "${SKIP_VERIFY}" != "true" ]] && ! command -v curl >/dev/null 2>&1; then
  echo "[deploy-all] ERROR: curl is required for verification checks"
  exit 1
fi

cd "${PROJECT_DIR}"

echo "[deploy-all] Project dir: ${PROJECT_DIR}"
echo "[deploy-all] Rebuild: ${REBUILD}"
echo "[deploy-all] NVIDIA backend mode: ${USE_NVIDIA_BACKEND}"

if [[ "${USE_NVIDIA_BACKEND}" == "true" ]]; then
  if [[ ! -x "./scripts/run_backend_with_nvidia_runtime.sh" ]]; then
    chmod +x ./scripts/run_backend_with_nvidia_runtime.sh 2>/dev/null || true
  fi

  if [[ ! -x "./scripts/run_backend_with_nvidia_runtime.sh" ]]; then
    echo "[deploy-all] ERROR: scripts/run_backend_with_nvidia_runtime.sh not executable"
    exit 1
  fi

  echo "[deploy-all] Running unified compose + runtime=nvidia backend deployment..."
  COMPOSE_REBUILD="${REBUILD}" ./scripts/run_backend_with_nvidia_runtime.sh
else
  echo "[deploy-all] Running compose-only deployment for frontend + backend..."
  if [[ "${REBUILD}" == "true" ]]; then
    docker-compose up -d --build
  else
    if ! docker-compose up -d --no-build --no-recreate; then
      echo "[deploy-all] WARN: '--no-recreate' not supported; retrying with --no-build"
      if ! docker-compose up -d --no-build; then
        echo "[deploy-all] WARN: '--no-build' not supported; retrying with plain up -d"
        docker-compose up -d
      fi
    fi
  fi
fi

if [[ "${SKIP_VERIFY}" == "true" ]]; then
  echo "[deploy-all] Verification skipped by request."
  exit 0
fi

echo "[deploy-all] Verifying container state..."
docker-compose ps

echo "[deploy-all] Verifying HTTP endpoints..."
backend_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs || true)"
frontend_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/ || true)"

echo "[deploy-all] backend_http=${backend_code} (expected 200)"
echo "[deploy-all] frontend_http=${frontend_code} (expected 200)"

if [[ "${backend_code}" != "200" || "${frontend_code}" != "200" ]]; then
  echo "[deploy-all] ERROR: health verification failed"
  echo "[deploy-all] Backend logs tail:"
  docker logs --tail 120 jetson-nano-backend || true
  echo "[deploy-all] Frontend logs tail:"
  docker logs --tail 80 jetson-nano-frontend || true
  exit 1
fi

echo "[deploy-all] SUCCESS: frontend and backend deployment completed."

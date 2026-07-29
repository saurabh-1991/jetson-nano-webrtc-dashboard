#!/usr/bin/env bash
set -euo pipefail

# Hybrid deployment helper:
# - Keep boot mode offline-safe (no-build) for reliability.
# - Run this script manually when internet is available and you want fresh online updates.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_GIT="false"
TARGET_BRANCH=""
SKIP_RESTART="false"

print_help() {
  cat <<'EOF'
Usage: ./scripts/deploy_online_update.sh [options]

Options:
  --project-dir <path>   Project root containing docker-compose.yml
  --sync-git             Fetch from origin and sync git before rebuild
  --branch <name>        Branch to sync to when --sync-git is used
  --skip-restart         Only sync git (if enabled), skip service restart
  --help                 Show this help

Examples:
  ./scripts/deploy_online_update.sh
  ./scripts/deploy_online_update.sh --sync-git
  ./scripts/deploy_online_update.sh --sync-git --branch poc_demo_v1.4.0

Notes:
  - This script intentionally performs an online rebuild path.
  - Boot service can still remain offline-safe (COMPOSE_REBUILD_ON_BOOT=false).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --sync-git)
      SYNC_GIT="true"
      shift 1
      ;;
    --branch)
      TARGET_BRANCH="$2"
      shift 2
      ;;
    --skip-restart)
      SKIP_RESTART="true"
      shift 1
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      print_help
      exit 1
      ;;
  esac
done

if [[ ! -f "${PROJECT_DIR}/docker-compose.yml" ]]; then
  echo "[ERROR] docker-compose.yml not found in PROJECT_DIR='${PROJECT_DIR}'"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed"
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "[ERROR] docker-compose is not installed"
  exit 1
fi

if [[ "${SYNC_GIT}" == "true" ]]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[ERROR] git is required for --sync-git"
    exit 1
  fi

  echo "[online-update] Syncing repository from origin..."
  cd "${PROJECT_DIR}"
  git fetch origin --prune

  if [[ -n "${TARGET_BRANCH}" ]]; then
    echo "[online-update] Checking out branch '${TARGET_BRANCH}' from origin"
    git checkout -B "${TARGET_BRANCH}" "origin/${TARGET_BRANCH}"
  else
    CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "${CURRENT_BRANCH}" == "HEAD" ]]; then
      echo "[ERROR] Detached HEAD detected. Use --branch <name> with --sync-git."
      exit 1
    fi
    echo "[online-update] Fast-forwarding current branch '${CURRENT_BRANCH}'"
    git pull --ff-only origin "${CURRENT_BRANCH}"
  fi
fi

if [[ "${SKIP_RESTART}" == "true" ]]; then
  echo "[online-update] Git sync complete. Restart skipped by request."
  exit 0
fi

echo "[online-update] Running online rebuild + runtime-nvidia backend refresh..."
cd "${PROJECT_DIR}"
COMPOSE_REBUILD=true ./scripts/run_backend_with_nvidia_runtime.sh

echo ""
echo "[online-update] Post-deploy quick checks:"
curl -sS http://127.0.0.1:8000/health || true
echo ""
curl -sS http://127.0.0.1:8000/api/system/status || true
echo ""
echo "[online-update] Done."

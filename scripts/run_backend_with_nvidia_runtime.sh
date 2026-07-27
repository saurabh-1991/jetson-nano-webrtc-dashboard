#!/usr/bin/env bash
set -euo pipefail

# Purpose:
# - Keep regular docker-compose workflow for frontend/aux services
# - Replace ONLY backend container with a runtime=nvidia equivalent
# - Preserve dual-camera mode and current env tuning
#
# Usage (on Jetson):
#   chmod +x scripts/run_backend_with_nvidia_runtime.sh
#   ./scripts/run_backend_with_nvidia_runtime.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK_NAME="jetsonnanowebrtcdashboard_jetson-network"
BACKEND_NAME="jetson-nano-backend"
BACKEND_IMAGE="jetsonnanowebrtcdashboard_jetson-backend:latest"

cd "$PROJECT_DIR"

echo "[nvidia-runtime] Ensuring compose services are up..."
# If a previously manual NVIDIA backend exists, remove it first so compose can proceed.
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true
docker-compose up -d --build

echo "[nvidia-runtime] Replacing backend container with --runtime nvidia..."
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$BACKEND_NAME" \
  --runtime nvidia \
  --privileged \
  --restart unless-stopped \
  --network "$NETWORK_NAME" \
  -p 8000:8000 \
  -v /dev:/dev \
  -v "$PROJECT_DIR/backend:/app" \
  -v "$PROJECT_DIR/.git:/workspace/.git:ro" \
  -e PYTHONUNBUFFERED=1 \
  -e API_DEBUG=False \
  -e LOG_LEVEL=INFO \
  -e CAMERA_SOURCE=usb \
  -e CAMERA_ENABLED_IDS=cam1,cam2 \
  -e CAMERA_STRICT_CAMERA_IDS=true \
  -e CAMERA_ACCELERATION=auto \
  -e CAMERA_USB_STARTUP_PROBE=true \
  -e CAMERA1_FPS=20 \
  -e CAMERA2_FPS=15 \
  -e CAMERA_BUFFER_FLUSH_GRABS=5 \
  -e CAMERA1_AUTO_BRIGHTNESS=true \
  -e CAMERA2_AUTO_BRIGHTNESS=true \
  -e CUDA_ENABLED=true \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  "$BACKEND_IMAGE" >/dev/null

echo "[nvidia-runtime] Waiting for backend..."
sleep 2

echo "[nvidia-runtime] Runtime:"
docker inspect "$BACKEND_NAME" --format 'runtime={{.HostConfig.Runtime}}'

echo "[nvidia-runtime] Plugin probe inside backend:"
docker exec "$BACKEND_NAME" sh -lc '
  gst-inspect-1.0 nvjpegdec >/dev/null 2>&1 && echo "nvjpegdec=OK" || echo "nvjpegdec=MISS"
  gst-inspect-1.0 nvvidconv >/dev/null 2>&1 && echo "nvvidconv=OK" || echo "nvvidconv=MISS"
'

echo "[nvidia-runtime] Health + camera availability:"
curl -sS http://127.0.0.1:8000/health ; echo
curl -sS http://127.0.0.1:8000/api/camera/enabled ; echo

echo "[nvidia-runtime] Done."

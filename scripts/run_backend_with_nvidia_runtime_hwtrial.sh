#!/usr/bin/env bash
set -euo pipefail

# Purpose:
# - Build optional HW-trial backend image (l4t-ml base)
# - Keep compose workflow for frontend/aux services
# - Replace backend with --runtime nvidia using HW-trial image
# - Print clear capability proof (OpenCV + camera diagnostics)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK_NAME="jetsonnanowebrtcdashboard_jetson-network"
BACKEND_NAME="jetson-nano-backend"
BACKEND_IMAGE="jetsonnanowebrtcdashboard_jetson-backend:hwtrial"

cd "$PROJECT_DIR"

echo "[hwtrial] Building backend image from backend/Dockerfile.jetpack46.hwtrial ..."
docker build -t "$BACKEND_IMAGE" -f backend/Dockerfile.jetpack46.hwtrial backend

echo "[hwtrial] Ensuring compose services are up (frontend, network, aux)..."
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true
docker-compose up -d --build

echo "[hwtrial] Replacing backend container with --runtime nvidia using $BACKEND_IMAGE ..."
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
  -e CAMERA1_ACCELERATION=direct \
  -e CAMERA2_ACCELERATION=hardware \
  -e CAMERA_USB_STARTUP_PROBE=true \
  -e CAMERA1_USB_STARTUP_PROBE=false \
  -e CAMERA2_USB_STARTUP_PROBE=false \
  -e CAMERA1_FPS=20 \
  -e CAMERA2_FPS=15 \
  -e CAMERA_BUFFER_FLUSH_GRABS=5 \
  -e CAMERA1_AUTO_BRIGHTNESS=true \
  -e CAMERA2_AUTO_BRIGHTNESS=true \
  -e CUDA_ENABLED=true \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  "$BACKEND_IMAGE" >/dev/null

echo "[hwtrial] Waiting for backend..."
sleep 3

echo "[hwtrial] Runtime:"
docker inspect "$BACKEND_NAME" --format 'runtime={{.HostConfig.Runtime}} image={{.Config.Image}}'

echo "[hwtrial] Plugin probe inside backend:"
docker exec "$BACKEND_NAME" sh -lc '
  gst-inspect-1.0 nvjpegdec >/dev/null 2>&1 && echo "nvjpegdec=OK" || echo "nvjpegdec=MISS"
  gst-inspect-1.0 nvvidconv >/dev/null 2>&1 && echo "nvvidconv=OK" || echo "nvvidconv=MISS"
'

echo "[hwtrial] OpenCV capability probe inside backend:"
docker exec "$BACKEND_NAME" python3 -c "import cv2; info=cv2.getBuildInformation(); print('cv2_file', cv2.__file__); print('cv2_version', cv2.__version__); print('has_cuda_mod', hasattr(cv2,'cuda')); print('cuda_devices', cv2.cuda.getCudaEnabledDeviceCount() if hasattr(cv2,'cuda') else 0); print('gstreamer_declared_yes', ('GStreamer: YES' in info) or ('GStreamer:                   YES' in info))"

echo "[hwtrial] API health + camera diagnostics:"
curl -sS http://127.0.0.1:8000/health ; echo
curl -sS http://127.0.0.1:8000/api/camera/enabled ; echo
curl -sS "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true" ; echo
curl -sS "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true" ; echo

echo "[hwtrial] Done."

#!/usr/bin/env bash
set -euo pipefail

# Purpose:
# - Keep regular docker-compose workflow for frontend/aux services
# - Replace ONLY backend container with a runtime=nvidia equivalent
# - Preserve dual-camera mode and validated acceleration tuning
#
# Usage (on Jetson):
#   chmod +x scripts/run_backend_with_nvidia_runtime.sh
#   ./scripts/run_backend_with_nvidia_runtime.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK_NAME="${NETWORK_NAME:-}"
BACKEND_NAME="jetson-nano-backend"
BACKEND_IMAGE="jetsonnanowebrtcdashboard_jetson-backend:latest"
COMPOSE_REBUILD="${COMPOSE_REBUILD:-false}"
WARMUP_STRICT="${WARMUP_STRICT:-false}"
CAM1_WARMUP_ATTEMPTS="${CAM1_WARMUP_ATTEMPTS:-4}"
CAM2_WARMUP_ATTEMPTS="${CAM2_WARMUP_ATTEMPTS:-10}"

cd "$PROJECT_DIR"

echo "[nvidia-runtime] Ensuring compose services are up..."
# If a previously manual NVIDIA backend exists, remove it first so compose can proceed.
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true
if [[ "$COMPOSE_REBUILD" == "true" ]]; then
  echo "[nvidia-runtime] Compose mode: rebuild images"
  docker-compose up -d --build
else
  echo "[nvidia-runtime] Compose mode: no-build (offline-safe)"
  if ! docker-compose up -d --no-build; then
    echo "[nvidia-runtime] WARN: '--no-build' unsupported on this compose version, retrying with plain up -d"
    docker-compose up -d
  fi
fi

if [[ -z "$NETWORK_NAME" ]]; then
  NETWORK_NAME="$(docker inspect "$BACKEND_NAME" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)"
fi
if [[ -z "$NETWORK_NAME" ]]; then
  NETWORK_NAME="jetsonnanowebrtcdashboard_jetson-network"
fi

if ! docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
  echo "[nvidia-runtime] ERROR: Backend image missing: $BACKEND_IMAGE"
  echo "[nvidia-runtime] Run once with COMPOSE_REBUILD=true when internet/build deps are available."
  exit 1
fi

echo "[nvidia-runtime] Replacing backend container with --runtime nvidia..."
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$BACKEND_NAME" \
  --runtime nvidia \
  --privileged \
  --restart unless-stopped \
  --network "$NETWORK_NAME" \
  --network-alias jetson-backend \
  -p 8000:8000 \
  -v /dev:/dev \
  -v /mnt/usb_recordings:/mnt/usb_recordings \
  -v "$PROJECT_DIR/backend:/app" \
  -v "$PROJECT_DIR/.git:/workspace/.git:ro" \
  -e PYTHONUNBUFFERED=1 \
  -e API_DEBUG=False \
  -e LOG_LEVEL=INFO \
  -e CAMERA_SOURCE=usb \
  -e CAMERA_ENABLED_IDS=cam1,cam2 \
  -e CAMERA_STRICT_CAMERA_IDS=true \
  -e CAMERA_ACCELERATION=direct \
  -e CAMERA1_ACCELERATION=direct \
  -e CAMERA2_ACCELERATION=direct \
  -e CAMERA_USB_STARTUP_PROBE=false \
  -e CAMERA1_USB_STARTUP_PROBE=false \
  -e CAMERA2_USB_STARTUP_PROBE=false \
  -e CAMERA_USB_PREFLIGHT_VALIDATE=false \
  -e CAMERA2_USB_PREFLIGHT_VALIDATE=false \
  -e CAMERA2_USB_HW_MODE_LOCK=false \
  -e CAMERA2_PREFER_GRAY8=false \
  -e CAMERA1_FPS=15 \
  -e CAMERA2_FPS=15 \
  -e CAMERA1_JPEG_QUALITY=68 \
  -e CAMERA2_JPEG_QUALITY=62 \
  -e CAMERA_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA1_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA2_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA_DIRECT_V4L2_TUNE=true \
  -e CAMERA1_AUTO_BRIGHTNESS=true \
  -e CAMERA2_AUTO_BRIGHTNESS=true \
  -e CUDA_ENABLED=true \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  "$BACKEND_IMAGE" >/dev/null

echo "[nvidia-runtime] Waiting for backend..."
sleep 2

if ! docker ps --format '{{.Names}}' | grep -q "^${BACKEND_NAME}$"; then
  echo "[nvidia-runtime] ERROR: backend container did not start"
  exit 1
fi

echo "[nvidia-runtime] Runtime:"
docker inspect "$BACKEND_NAME" --format 'runtime={{.HostConfig.Runtime}}'

echo "[nvidia-runtime] Plugin probe inside backend:"
docker exec "$BACKEND_NAME" sh -lc '
  gst-inspect-1.0 nvjpegdec >/dev/null 2>&1 && echo "nvjpegdec=OK" || echo "nvjpegdec=MISS"
  gst-inspect-1.0 nvvidconv >/dev/null 2>&1 && echo "nvvidconv=OK" || echo "nvvidconv=MISS"
'

echo "[nvidia-runtime] OpenCV capability probe inside backend:"
docker exec "$BACKEND_NAME" python3 -c "import cv2; info=cv2.getBuildInformation(); print('cv2_file', cv2.__file__); print('cv2_version', cv2.__version__); print('has_cuda_mod', hasattr(cv2,'cuda')); print('cuda_devices', cv2.cuda.getCudaEnabledDeviceCount() if hasattr(cv2,'cuda') else 0); print('gstreamer_declared_yes', ('GStreamer: YES' in info) or ('GStreamer:                   YES' in info))"

echo "[nvidia-runtime] Health + camera availability:"
curl -sS http://127.0.0.1:8000/health ; echo
curl -sS http://127.0.0.1:8000/api/camera/enabled ; echo
curl -sS "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true" ; echo
curl -sS "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true" ; echo

# Best-effort backend prewarm to reduce first-frame cold-start flakiness.
curl -sS -X POST http://127.0.0.1:8000/api/camera/prewarm >/dev/null 2>&1 || true

warmup_frame_check() {
  local camera_id="$1"
  local max_attempts="${2:-6}"
  local attempt=1
  local http_code=""

  while [ "$attempt" -le "$max_attempts" ]; do
    http_code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:8000/api/camera/frame?camera_id=${camera_id}") || http_code="000"
    if [ "$http_code" = "200" ]; then
      echo "[nvidia-runtime] ${camera_id} frame warm-up: OK on attempt ${attempt}"
      return 0
    fi
    echo "[nvidia-runtime] ${camera_id} frame warm-up: attempt ${attempt}/${max_attempts} returned HTTP ${http_code}"
    attempt=$((attempt + 1))
    sleep 1
  done

  echo "[nvidia-runtime] ERROR: ${camera_id} frame warm-up failed after ${max_attempts} attempts"
  return 1
}

echo "[nvidia-runtime] Camera frame warm-up checks:"

cam1_warmup_ok=true
cam2_warmup_ok=true

if ! warmup_frame_check cam1 "$CAM1_WARMUP_ATTEMPTS"; then
  cam1_warmup_ok=false
fi

if ! warmup_frame_check cam2 "$CAM2_WARMUP_ATTEMPTS"; then
  cam2_warmup_ok=false
fi

if [[ "$WARMUP_STRICT" == "true" ]]; then
  if [[ "$cam1_warmup_ok" != "true" || "$cam2_warmup_ok" != "true" ]]; then
    echo "[nvidia-runtime] ERROR: warm-up strict mode enabled and one or more cameras failed warm-up"
    exit 1
  fi
else
  if [[ "$cam1_warmup_ok" != "true" || "$cam2_warmup_ok" != "true" ]]; then
    echo "[nvidia-runtime] WARN: One or more cameras failed warm-up checks; services are up, runtime will continue with in-app recovery"
  fi
fi

echo "[nvidia-runtime] Done."

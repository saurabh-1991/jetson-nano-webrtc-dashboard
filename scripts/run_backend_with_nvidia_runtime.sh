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
H264_INPUT_MODE_EFFECTIVE="${CAMERA_H264_INPUT_MODE:-usb}"
H264_RTSP_LATENCY_EFFECTIVE="${CAMERA_H264_RTSP_LATENCY_MS:-60}"
H264_FRAGMENT_MS_EFFECTIVE="${CAMERA_H264_GST_FRAGMENT_MS:-180}"

cd "$PROJECT_DIR"

echo "[nvidia-runtime] Ensuring compose services are up..."
# If a previously manual NVIDIA backend exists, remove it first so compose can proceed.
docker rm -f "$BACKEND_NAME" >/dev/null 2>&1 || true
if [[ "$COMPOSE_REBUILD" == "true" ]]; then
  echo "[nvidia-runtime] Compose mode: rebuild images"
  docker-compose up -d --build
else
  echo "[nvidia-runtime] Compose mode: no-build (offline-safe)"
  if ! docker-compose up -d --no-build --no-recreate; then
    echo "[nvidia-runtime] WARN: '--no-recreate' unsupported on this compose version, retrying with --no-build"
    if ! docker-compose up -d --no-build; then
      echo "[nvidia-runtime] WARN: '--no-build' unsupported on this compose version, retrying with plain up -d"
      docker-compose up -d
    fi
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
  -e CAMERA_ACCELERATION="${CAMERA_ACCELERATION:-direct}" \
  -e CAMERA1_ACCELERATION="${CAMERA1_ACCELERATION:-direct}" \
  -e CAMERA2_ACCELERATION="${CAMERA2_ACCELERATION:-direct}" \
  -e CAMERA_USB_STARTUP_PROBE=false \
  -e CAMERA1_USB_STARTUP_PROBE=false \
  -e CAMERA2_USB_STARTUP_PROBE=false \
  -e CAMERA_USB_PREFLIGHT_VALIDATE=false \
  -e CAMERA2_USB_PREFLIGHT_VALIDATE=false \
  -e CAMERA2_USB_HW_MODE_LOCK=false \
  -e CAMERA2_PREFER_GRAY8=false \
  -e CAMERA1_WIDTH="${CAMERA1_WIDTH:-640}" \
  -e CAMERA1_HEIGHT="${CAMERA1_HEIGHT:-480}" \
  -e CAMERA1_FPS="${CAMERA1_FPS:-30}" \
  -e CAMERA2_FPS="${CAMERA2_FPS:-30}" \
  -e CAMERA1_JPEG_QUALITY=68 \
  -e CAMERA2_JPEG_QUALITY=62 \
  -e CAMERA_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA1_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA2_BUFFER_FLUSH_GRABS=1 \
  -e CAMERA_RECOVERY_BASE_BACKOFF_SECONDS=2.0 \
  -e CAMERA_RECOVERY_BACKOFF_MAX_SECONDS=30.0 \
  -e CAMERA_RECOVERY_MIN_REINIT_INTERVAL_SECONDS=0.75 \
  -e CAMERA_H264_STREAM_ENABLED=true \
  -e CAMERA_H264_STREAM_USE_GSTREAMER="${CAMERA_H264_STREAM_USE_GSTREAMER:-true}" \
  -e CAMERA_H264_INPUT_MODE="${H264_INPUT_MODE_EFFECTIVE}" \
  -e CAMERA_H264_RTSP_URL="${CAMERA_H264_RTSP_URL:-}" \
  -e CAMERA_H264_RTSP_LATENCY_MS="${H264_RTSP_LATENCY_EFFECTIVE}" \
  -e CAMERA_H264_RTSP_PROTOCOLS="${CAMERA_H264_RTSP_PROTOCOLS:-tcp}" \
  -e CAMERA_H264_FILE_PATH="${CAMERA_H264_FILE_PATH:-}" \
  -e CAMERA_H264_GST_INPUT_FORMAT="${CAMERA_H264_GST_INPUT_FORMAT:-YUY2}" \
  -e CAMERA_H264_GST_FRAGMENT_MS="${H264_FRAGMENT_MS_EFFECTIVE}" \
  -e CAMERA_H264_GST_MAXPERF_ENABLE="${CAMERA_H264_GST_MAXPERF_ENABLE:-true}" \
  -e CAMERA_H264_STREAM_ENCODER_PREFERENCE="${CAMERA_H264_STREAM_ENCODER_PREFERENCE:-h264_v4l2m2m,h264_omx,h264_nvmpi,libx264}" \
  -e CAMERA_H264_STREAM_BITRATE="${CAMERA_H264_STREAM_BITRATE:-1200000}" \
  -e CAMERA_H264_STREAM_GOP="${CAMERA_H264_STREAM_GOP:-15}" \
  -e CAMERA_H264_STREAM_MAX_FPS="${CAMERA_H264_STREAM_MAX_FPS:-20}" \
  -e CAMERA1_H264_STREAM_ENABLED="${CAMERA1_H264_STREAM_ENABLED:-true}" \
  -e CAMERA2_H264_STREAM_ENABLED="${CAMERA2_H264_STREAM_ENABLED:-true}" \
  -e CAMERA1_H264_STREAM_USE_GSTREAMER="${CAMERA1_H264_STREAM_USE_GSTREAMER:-${CAMERA_H264_STREAM_USE_GSTREAMER:-true}}" \
  -e CAMERA2_H264_STREAM_USE_GSTREAMER="${CAMERA2_H264_STREAM_USE_GSTREAMER:-${CAMERA_H264_STREAM_USE_GSTREAMER:-true}}" \
  -e CAMERA1_H264_STREAM_BITRATE="${CAMERA1_H264_STREAM_BITRATE:-${CAMERA_H264_STREAM_BITRATE:-1200000}}" \
  -e CAMERA2_H264_STREAM_BITRATE="${CAMERA2_H264_STREAM_BITRATE:-${CAMERA_H264_STREAM_BITRATE:-1200000}}" \
  -e CAMERA1_H264_STREAM_GOP="${CAMERA1_H264_STREAM_GOP:-${CAMERA_H264_STREAM_GOP:-15}}" \
  -e CAMERA2_H264_STREAM_GOP="${CAMERA2_H264_STREAM_GOP:-${CAMERA_H264_STREAM_GOP:-15}}" \
  -e CAMERA1_H264_STREAM_MAX_FPS="${CAMERA1_H264_STREAM_MAX_FPS:-30}" \
  -e CAMERA2_H264_STREAM_MAX_FPS="${CAMERA2_H264_STREAM_MAX_FPS:-${CAMERA_H264_STREAM_MAX_FPS:-20}}" \
  -e CAMERA_H264_FAIL_COOLDOWN_THRESHOLD="${CAMERA_H264_FAIL_COOLDOWN_THRESHOLD:-2}" \
  -e CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS="${CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS:-45}" \
  -e CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS="${CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS:-300}" \
  -e CAMERA_H264_FAIL_EARLY_SECONDS="${CAMERA_H264_FAIL_EARLY_SECONDS:-3}" \
  -e MEDIA_WEBRTC_GATEWAY_ENABLED="${MEDIA_WEBRTC_GATEWAY_ENABLED:-false}" \
  -e MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE="${MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE:-}" \
  -e MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL="${MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL:-}" \
  -e MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL="${MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL:-}" \
  -e MODBUS_ENABLED="${MODBUS_ENABLED:-true}" \
  -e MODBUS_TRANSPORT="${MODBUS_TRANSPORT:-serial}" \
  -e MODBUS_PORT="${MODBUS_PORT:-/dev/ttyUSB0}" \
  -e MODBUS_HOST="${MODBUS_HOST:-}" \
  -e MODBUS_TCP_PORT="${MODBUS_TCP_PORT:-502}" \
  -e MODBUS_SLAVE_ID="${MODBUS_SLAVE_ID:-1}" \
  -e MODBUS_BAUDRATE="${MODBUS_BAUDRATE:-9600}" \
  -e MODBUS_BYTESIZE="${MODBUS_BYTESIZE:-8}" \
  -e MODBUS_PARITY="${MODBUS_PARITY:-N}" \
  -e MODBUS_STOPBITS="${MODBUS_STOPBITS:-1}" \
  -e MODBUS_TIMEOUT="${MODBUS_TIMEOUT:-0.8}" \
  -e MODBUS_REGISTER_TYPE="${MODBUS_REGISTER_TYPE:-holding}" \
  -e MODBUS_ADDRESS_BASE="${MODBUS_ADDRESS_BASE:-0}" \
  -e MODBUS_ADDRESS_OFFSET="${MODBUS_ADDRESS_OFFSET:-0}" \
  -e FLOW_METER_ENABLED="${FLOW_METER_ENABLED:-false}" \
  -e FLOW_METER_TRANSPORT="${FLOW_METER_TRANSPORT:-tcp}" \
  -e FLOW_METER_HOST="${FLOW_METER_HOST:-}" \
  -e FLOW_METER_TCP_PORT="${FLOW_METER_TCP_PORT:-502}" \
  -e FLOW_METER_PORT="${FLOW_METER_PORT:-/dev/ttyUSB1}" \
  -e FLOW_METER_SLAVE_ID="${FLOW_METER_SLAVE_ID:-1}" \
  -e FLOW_METER_BAUDRATE="${FLOW_METER_BAUDRATE:-9600}" \
  -e FLOW_METER_BYTESIZE="${FLOW_METER_BYTESIZE:-8}" \
  -e FLOW_METER_PARITY="${FLOW_METER_PARITY:-N}" \
  -e FLOW_METER_STOPBITS="${FLOW_METER_STOPBITS:-1}" \
  -e FLOW_METER_TIMEOUT="${FLOW_METER_TIMEOUT:-0.8}" \
  -e FLOW_METER_REGISTER_TYPE="${FLOW_METER_REGISTER_TYPE:-holding}" \
  -e FLOW_METER_ADDRESS_BASE="${FLOW_METER_ADDRESS_BASE:-0}" \
  -e FLOW_METER_ADDRESS_OFFSET="${FLOW_METER_ADDRESS_OFFSET:-0}" \
  -e FLOW_METER_VALUE_ADDRESS="${FLOW_METER_VALUE_ADDRESS:-0}" \
  -e FLOW_METER_DECIMAL_ADDRESS="${FLOW_METER_DECIMAL_ADDRESS:-}" \
  -e FLOW_METER_STATUS_ADDRESS="${FLOW_METER_STATUS_ADDRESS:-}" \
  -e FLOW_METER_SCALE="${FLOW_METER_SCALE:-0.1}" \
  -e FLOW_METER_OFFSET="${FLOW_METER_OFFSET:-0.0}" \
  -e FLOW_METER_SIGNED="${FLOW_METER_SIGNED:-false}" \
  -e FLOW_METER_MIN_VALUE="${FLOW_METER_MIN_VALUE:-0.0}" \
  -e FLOW_METER_MAX_VALUE="${FLOW_METER_MAX_VALUE:-99999.0}" \
  -e FLOW_METER_FAILURE_BACKOFF_SECONDS="${FLOW_METER_FAILURE_BACKOFF_SECONDS:-5.0}" \
  -e MODBUS_FAILURE_BACKOFF_SECONDS="${MODBUS_FAILURE_BACKOFF_SECONDS:-5.0}" \
  -e SENSOR_SIMULATION_ENABLED="${SENSOR_SIMULATION_ENABLED:-false}" \
  -e VFD_ENABLED="${VFD_ENABLED:-false}" \
  -e VFD_HOST="${VFD_HOST:-}" \
  -e VFD_PORT="${VFD_PORT:-502}" \
  -e VFD_SLAVE_ID="${VFD_SLAVE_ID:-1}" \
  -e VFD_TIMEOUT_SECONDS="${VFD_TIMEOUT_SECONDS:-1.0}" \
  -e VFD_MIN_SPEED_HZ="${VFD_MIN_SPEED_HZ:-0.0}" \
  -e VFD_MAX_SPEED_HZ="${VFD_MAX_SPEED_HZ:-50.0}" \
  -e VFD_DEFAULT_SPEED_HZ="${VFD_DEFAULT_SPEED_HZ:-0.0}" \
  -e VFD_SPEED_SCALE="${VFD_SPEED_SCALE:-100}" \
  -e VFD_RUN_COMMAND_REGISTER="${VFD_RUN_COMMAND_REGISTER:-8192}" \
  -e VFD_SPEED_COMMAND_REGISTER="${VFD_SPEED_COMMAND_REGISTER:-8193}" \
  -e VFD_RUN_FORWARD_WORD="${VFD_RUN_FORWARD_WORD:-1}" \
  -e VFD_STOP_WORD="${VFD_STOP_WORD:-0}" \
  -e VFD_MIN_WRITE_INTERVAL_MS="${VFD_MIN_WRITE_INTERVAL_MS:-150}" \
  -e CAMERA_DIRECT_V4L2_TUNE=true \
  -e CAMERA1_AUTO_BRIGHTNESS=true \
  -e CAMERA2_AUTO_BRIGHTNESS=true \
  -e CUDA_ENABLED=true \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  "$BACKEND_IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 200 >/dev/null

echo "[nvidia-runtime] Waiting for backend..."
sleep 2

if ! docker ps --format '{{.Names}}' | grep -q "^${BACKEND_NAME}$"; then
  echo "[nvidia-runtime] ERROR: backend container did not start"
  exit 1
fi

echo "[nvidia-runtime] Runtime:"
docker inspect "$BACKEND_NAME" --format 'runtime={{.HostConfig.Runtime}}'

echo "[nvidia-runtime] H264 profile: mode=${H264_INPUT_MODE_EFFECTIVE} rtsp_latency_ms=${H264_RTSP_LATENCY_EFFECTIVE} fragment_ms=${H264_FRAGMENT_MS_EFFECTIVE}"

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

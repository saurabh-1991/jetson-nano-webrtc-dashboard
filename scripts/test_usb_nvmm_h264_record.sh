#!/usr/bin/env bash
set -euo pipefail

# USB webcam -> NVMM -> nvv4l2h264enc -> MP4 file
# Usage:
#   ./scripts/test_usb_nvmm_h264_record.sh [output.mp4]
#
# Optional env overrides:
#   CAMERA_DEVICE=/dev/video0
#   CAMERA_WIDTH=1280
#   CAMERA_HEIGHT=720
#   CAMERA_FPS=30
#   CAMERA_FORMAT=YUY2
#   CAMERA_BITRATE=1200000
#   CAMERA_GOP=15
#   RECORD_SECONDS=10

OUT_FILE="${1:-/tmp/jetson_usb_nvmm_h264_test.mp4}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video0}"
CAMERA_WIDTH="${CAMERA_WIDTH:-1280}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-720}"
CAMERA_FPS="${CAMERA_FPS:-30}"
CAMERA_FORMAT="${CAMERA_FORMAT:-YUY2}"
CAMERA_BITRATE="${CAMERA_BITRATE:-1200000}"
CAMERA_GOP="${CAMERA_GOP:-15}"
RECORD_SECONDS="${RECORD_SECONDS:-10}"

if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
  echo "ERROR: gst-launch-1.0 not found"
  exit 1
fi

if ! command -v v4l2-ctl >/dev/null 2>&1; then
  echo "WARN: v4l2-ctl not found; skipping mode listing"
else
  echo "[probe] Supported modes for ${CAMERA_DEVICE}:"
  v4l2-ctl -d "${CAMERA_DEVICE}" --list-formats-ext || true
fi

if [[ ! -e "${CAMERA_DEVICE}" ]]; then
  echo "ERROR: Camera device not found: ${CAMERA_DEVICE}"
  exit 1
fi

NUM_BUFFERS=$(( CAMERA_FPS * RECORD_SECONDS ))
if [[ "$NUM_BUFFERS" -lt 1 ]]; then
  NUM_BUFFERS=1
fi

echo "[record] Writing ${RECORD_SECONDS}s test clip to ${OUT_FILE}"

gst-launch-1.0 -e \
  v4l2src device="${CAMERA_DEVICE}" io-mode=2 do-timestamp=true num-buffers="${NUM_BUFFERS}" ! \
  "video/x-raw,format=${CAMERA_FORMAT},width=${CAMERA_WIDTH},height=${CAMERA_HEIGHT},framerate=${CAMERA_FPS}/1" ! \
  nvvidconv ! "video/x-raw(memory:NVMM),format=NV12" ! \
  nvv4l2h264enc bitrate="${CAMERA_BITRATE}" iframeinterval="${CAMERA_GOP}" idrinterval="${CAMERA_GOP}" insert-sps-pps=true maxperf-enable=true ! \
  h264parse ! qtmux ! filesink location="${OUT_FILE}" sync=false

if [[ -f "${OUT_FILE}" ]]; then
  ls -lh "${OUT_FILE}"
  echo "[ok] Test MP4 created"
else
  echo "ERROR: Output file was not created"
  exit 1
fi

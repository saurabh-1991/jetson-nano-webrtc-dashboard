#!/usr/bin/env bash
set -euo pipefail

# Native setup for Jetson Nano JetPack 4.6 (Python 3.6)
# Uses JetPack-provided OpenCV/GStreamer/CUDA libraries from apt.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${BACKEND_DIR}/.venv-jp46"

echo "[1/4] Installing system dependencies (JetPack-native OpenCV/GStreamer)..."
sudo apt-get update
sudo apt-get install -y \
  python3-pip \
  python3-venv \
  python3-dev \
  python3-opencv \
  python3-numpy \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav

echo "[2/4] Creating venv at ${VENV_DIR} with system-site-packages ..."
# IMPORTANT: use system-site-packages to reuse JetPack's apt-installed cv2/numpy/gstreamer bindings.
python3 -m venv --system-site-packages "${VENV_DIR}"

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

echo "[3/4] Installing Python dependencies (JP4.6 profile)..."
pip install --upgrade "pip<23" "setuptools<60" "wheel<0.38"
pip install -r "${BACKEND_DIR}/requirements.jetpack46.txt"

echo "[4/4] Probing runtime OpenCV/GStreamer capabilities..."
python - <<'PY'
import cv2
print("OpenCV version:", cv2.__version__)
print("Has cv2.cuda module:", hasattr(cv2, "cuda"))
if hasattr(cv2, "cuda"):
    try:
        print("CUDA device count:", cv2.cuda.getCudaEnabledDeviceCount())
    except Exception as e:
        print("CUDA device query error:", e)
print("Has cv2.cuda_GpuMat:", hasattr(cv2, "cuda_GpuMat"))
print("Has cv2.cuda.GpuMat:", hasattr(cv2.cuda, "GpuMat") if hasattr(cv2, "cuda") else False)
PY

echo "✅ Native JetPack 4.6 backend environment is ready."
echo "Activate with: source ${VENV_DIR}/bin/activate"

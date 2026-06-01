"""Configuration for Jetson Nano Dashboard"""

import os

# Camera Configuration
CAMERA_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "usb").lower()  # usb | csi

# GStreamer Pipeline Configuration
USB_GST_PIPELINE = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

CSI_GST_PIPELINE = (
    f"nvarguscamerasrc ! "
    f"video/x-raw(memory:NVMM), width={CAMERA_WIDTH}, height={CAMERA_HEIGHT}, format=NV12, framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

DEFAULT_GST_PIPELINE = CSI_GST_PIPELINE if CAMERA_SOURCE == "csi" else USB_GST_PIPELINE
GST_PIPELINE = os.getenv("GST_PIPELINE_OVERRIDE", DEFAULT_GST_PIPELINE)

# CUDA Processing Configuration
CUDA_ENABLED = True
PROCESSING_SCALE = (640, 480)

# GPIO Configuration
GPIO_LED_PIN = 12
GPIO_BUTTON_PIN = 16

# FastAPI Configuration
API_HOST = "0.0.0.0"
API_PORT = 8000
API_DEBUG = False

# WebRTC Configuration
STUN_SERVERS = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
]

# Logging Configuration
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

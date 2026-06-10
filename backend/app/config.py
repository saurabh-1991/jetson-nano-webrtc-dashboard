"""Configuration for Jetson Nano Dashboard"""

import os

# Camera Configuration
CAMERA_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "usb").lower()  # usb | csi
CAMERA_ACCELERATION = os.getenv("CAMERA_ACCELERATION", "auto").lower()  # auto | hardware | compat
CAMERA_USB_STARTUP_PROBE = os.getenv("CAMERA_USB_STARTUP_PROBE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

try:
    CAMERA_CSI_SENSOR_ID = int(os.getenv("CAMERA_CSI_SENSOR_ID", "0"))
except (TypeError, ValueError):
    CAMERA_CSI_SENSOR_ID = 0

if CAMERA_ACCELERATION not in ("auto", "hardware", "compat"):
    CAMERA_ACCELERATION = "auto"

# GStreamer Pipeline Configuration
# USB MJPEG + NVIDIA accelerated decode path (nvjpegdec + nvvidconv)
USB_GST_PIPELINE_HW = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegparse ! "
    "nvjpegdec ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

# USB MJPEG compatibility path (software jpegdec)
USB_GST_PIPELINE_COMPAT = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

# USB raw YUV + hardware conversion paths (NVIDIA documented v4l2src + nvvidconv flow)
USB_GST_PIPELINE_RAW_HW_UYVY = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"video/x-raw,format=UYVY,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw(memory:NVMM), format=NV12 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

USB_GST_PIPELINE_RAW_HW_YUY2 = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"video/x-raw,format=YUY2,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw(memory:NVMM), format=NV12 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

USB_GST_PIPELINE_COMPAT_RAW = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"video/x-raw,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

# Most permissive USB fallback (avoid strict caps, let camera pick mode)
USB_GST_PIPELINE_COMPAT_ANY = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

CSI_GST_PIPELINE = (
    f"nvarguscamerasrc sensor-id={CAMERA_CSI_SENSOR_ID} ! "
    f"video/x-raw(memory:NVMM), width={CAMERA_WIDTH}, height={CAMERA_HEIGHT}, format=NV12, framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1 max-buffers=1 sync=false"
)

if CAMERA_ACCELERATION == "compat":
    USB_GST_PIPELINE = USB_GST_PIPELINE_COMPAT
else:
    # hardware or auto => prefer hardware path by default
    USB_GST_PIPELINE = USB_GST_PIPELINE_HW

# Backward-compatible aliases for explicit naming
USB_GST_PIPELINE_MJPEG_HW = USB_GST_PIPELINE_HW
USB_GST_PIPELINE_COMPAT_MJPEG = USB_GST_PIPELINE_COMPAT

DEFAULT_GST_PIPELINE = CSI_GST_PIPELINE if CAMERA_SOURCE == "csi" else USB_GST_PIPELINE
GST_PIPELINE_OVERRIDE = os.getenv("GST_PIPELINE_OVERRIDE", "")
GST_PIPELINE_IS_OVERRIDE = bool(GST_PIPELINE_OVERRIDE)
GST_PIPELINE = GST_PIPELINE_OVERRIDE if GST_PIPELINE_IS_OVERRIDE else DEFAULT_GST_PIPELINE

# CUDA Processing Configuration
CUDA_ENABLED = os.getenv("CUDA_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
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

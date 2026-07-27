"""Configuration for Jetson Nano Dashboard"""

import os

# Camera Configuration
CAMERA_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA2_DEVICE = os.getenv("CAMERA2_DEVICE", "/dev/video1")
CAMERA2_WIDTH = int(os.getenv("CAMERA2_WIDTH", "640"))
CAMERA2_HEIGHT = int(os.getenv("CAMERA2_HEIGHT", "480"))
CAMERA2_FPS = int(os.getenv("CAMERA2_FPS", "20"))
CAMERA_DEFAULT_ID = os.getenv("CAMERA_DEFAULT_ID", "cam1").lower()
CAMERA2_DEVICE_HINT = os.getenv("CAMERA2_DEVICE_HINT", "arducam,ir")
CAMERA2_FORCE_MJPEG = os.getenv("CAMERA2_FORCE_MJPEG", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA2_PREFER_GRAY8 = os.getenv("CAMERA2_PREFER_GRAY8", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_ALLOW_YUY2_FALLBACK = os.getenv("CAMERA_ALLOW_YUY2_FALLBACK", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA1_JPEG_QUALITY = max(45, min(95, int(os.getenv("CAMERA1_JPEG_QUALITY", "74"))))
CAMERA2_JPEG_QUALITY = max(45, min(95, int(os.getenv("CAMERA2_JPEG_QUALITY", "70"))))
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

CAMERA_PROFILES = {
    "cam1": {
        "device": os.getenv("CAMERA1_DEVICE", CAMERA_DEVICE),
        "width": int(os.getenv("CAMERA1_WIDTH", str(CAMERA_WIDTH))),
        "height": int(os.getenv("CAMERA1_HEIGHT", str(CAMERA_HEIGHT))),
        "fps": int(os.getenv("CAMERA1_FPS", str(CAMERA_FPS))),
        "jpeg_quality": CAMERA1_JPEG_QUALITY,
    },
    "cam2": {
        "device": CAMERA2_DEVICE,
        "width": CAMERA2_WIDTH,
        "height": CAMERA2_HEIGHT,
        "fps": CAMERA2_FPS,
        "jpeg_quality": CAMERA2_JPEG_QUALITY,
    },
}

CAMERA_BUFFER_FLUSH_GRABS = max(0, int(os.getenv("CAMERA_BUFFER_FLUSH_GRABS", "2")))

# IR camera low-light adaptation (best-effort via V4L2 controls)
CAMERA2_ADAPTIVE_EXPOSURE = os.getenv("CAMERA2_ADAPTIVE_EXPOSURE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA2_EXPOSURE_ADAPT_INTERVAL_SECONDS = max(
    1.0, float(os.getenv("CAMERA2_EXPOSURE_ADAPT_INTERVAL_SECONDS", "1.5"))
)
CAMERA2_LUMA_TARGET = max(20.0, min(220.0, float(os.getenv("CAMERA2_LUMA_TARGET", "85"))))
CAMERA2_LUMA_TOLERANCE = max(3.0, min(60.0, float(os.getenv("CAMERA2_LUMA_TOLERANCE", "10"))))
CAMERA2_EXPOSURE_STEP = max(1, int(os.getenv("CAMERA2_EXPOSURE_STEP", "20")))
CAMERA2_GAIN_STEP = max(1, int(os.getenv("CAMERA2_GAIN_STEP", "4")))

GST_APPSINK_REALTIME = "appsink drop=1 max-buffers=1 sync=false enable-last-sample=false"

CAMERA2_GST_PIPELINE_MJPEG_HW_GRAY8 = (
    f"v4l2src io-mode=2 do-timestamp=true device={CAMERA2_DEVICE} ! "
    f"image/jpeg,width={CAMERA2_WIDTH},height={CAMERA2_HEIGHT},framerate={CAMERA2_FPS}/1 ! "
    "jpegparse ! "
    "nvjpegdec ! "
    "nvvidconv ! "
    "video/x-raw, format=GRAY8 ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

CAMERA2_GST_PIPELINE_MJPEG_COMPAT_GRAY8 = (
    f"v4l2src io-mode=2 do-timestamp=true device={CAMERA2_DEVICE} ! "
    f"image/jpeg,width={CAMERA2_WIDTH},height={CAMERA2_HEIGHT},framerate={CAMERA2_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=GRAY8 ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

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
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

# USB MJPEG compatibility path (software jpegdec)
USB_GST_PIPELINE_COMPAT = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
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
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
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
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

USB_GST_PIPELINE_COMPAT_RAW = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"video/x-raw,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

# Most permissive USB fallback (avoid strict caps, let camera pick mode)
USB_GST_PIPELINE_COMPAT_ANY = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
)

CSI_GST_PIPELINE = (
    f"nvarguscamerasrc sensor-id={CAMERA_CSI_SENSOR_ID} ! "
    f"video/x-raw(memory:NVMM), width={CAMERA_WIDTH}, height={CAMERA_HEIGHT}, format=NV12, framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "queue leaky=downstream max-size-buffers=1 ! "
    + GST_APPSINK_REALTIME
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

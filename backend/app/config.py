"""Configuration for Jetson Nano Dashboard"""

import os


def _parse_optional_bool_env(var_name: str):
    raw = os.getenv(var_name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _parse_optional_camera_accel(var_name: str) -> str:
    raw = str(os.getenv(var_name, "")).strip().lower()
    return raw if raw in ("", "auto", "hardware", "compat", "direct") else ""


def _parse_optional_v4l2_io_mode(var_name: str):
    raw = str(os.getenv(var_name, "")).strip()
    if raw == "":
        return None
    if raw.isdigit() and int(raw) in (0, 1, 2, 3, 4, 5):
        return int(raw)
    return None

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
CAMERA_ENABLED_IDS_RAW = os.getenv("CAMERA_ENABLED_IDS", "cam1,cam2")
CAMERA_STRICT_CAMERA_IDS = os.getenv("CAMERA_STRICT_CAMERA_IDS", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_REQUIRE_HARDWARE_ACCEL = os.getenv("CAMERA_REQUIRE_HARDWARE_ACCEL", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
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
CAMERA1_AUTO_BRIGHTNESS = os.getenv("CAMERA1_AUTO_BRIGHTNESS", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA2_AUTO_BRIGHTNESS = os.getenv("CAMERA2_AUTO_BRIGHTNESS", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA1_JPEG_QUALITY = max(45, min(95, int(os.getenv("CAMERA1_JPEG_QUALITY", "74"))))
CAMERA2_JPEG_QUALITY = max(45, min(95, int(os.getenv("CAMERA2_JPEG_QUALITY", "70"))))
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "usb").lower()  # usb | csi
CAMERA_ACCELERATION = os.getenv("CAMERA_ACCELERATION", "auto").lower()  # auto | hardware | compat
CAMERA1_ACCELERATION = _parse_optional_camera_accel("CAMERA1_ACCELERATION")
CAMERA2_ACCELERATION = _parse_optional_camera_accel("CAMERA2_ACCELERATION")
CAMERA_USB_STARTUP_PROBE = os.getenv("CAMERA_USB_STARTUP_PROBE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA1_USB_STARTUP_PROBE = _parse_optional_bool_env("CAMERA1_USB_STARTUP_PROBE")
CAMERA2_USB_STARTUP_PROBE = _parse_optional_bool_env("CAMERA2_USB_STARTUP_PROBE")
CAMERA_USB_PREFLIGHT_VALIDATE = os.getenv("CAMERA_USB_PREFLIGHT_VALIDATE", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA1_USB_PREFLIGHT_VALIDATE = _parse_optional_bool_env("CAMERA1_USB_PREFLIGHT_VALIDATE")
CAMERA2_USB_PREFLIGHT_VALIDATE = _parse_optional_bool_env("CAMERA2_USB_PREFLIGHT_VALIDATE")
CAMERA_USB_HW_MODE_LOCK = os.getenv("CAMERA_USB_HW_MODE_LOCK", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA1_USB_HW_MODE_LOCK = _parse_optional_bool_env("CAMERA1_USB_HW_MODE_LOCK")
CAMERA2_USB_HW_MODE_LOCK = _parse_optional_bool_env("CAMERA2_USB_HW_MODE_LOCK")
CAMERA_USB_V4L2_IO_MODE = _parse_optional_v4l2_io_mode("CAMERA_USB_V4L2_IO_MODE")
CAMERA1_USB_V4L2_IO_MODE = _parse_optional_v4l2_io_mode("CAMERA1_USB_V4L2_IO_MODE")
CAMERA2_USB_V4L2_IO_MODE = _parse_optional_v4l2_io_mode("CAMERA2_USB_V4L2_IO_MODE")

try:
    CAMERA_CSI_SENSOR_ID = int(os.getenv("CAMERA_CSI_SENSOR_ID", "0"))
except (TypeError, ValueError):
    CAMERA_CSI_SENSOR_ID = 0

if CAMERA_ACCELERATION not in ("auto", "hardware", "compat", "direct"):
    CAMERA_ACCELERATION = "auto"

_all_camera_profiles = {
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

_enabled_ids = []
for _raw_id in str(CAMERA_ENABLED_IDS_RAW or "").split(","):
    _camera_id = _raw_id.strip().lower()
    if _camera_id and _camera_id in _all_camera_profiles and _camera_id not in _enabled_ids:
        _enabled_ids.append(_camera_id)

# Always keep at least cam1 enabled as a safe default.
if not _enabled_ids:
    _enabled_ids = ["cam1"]

CAMERA_PROFILES = {camera_id: _all_camera_profiles[camera_id] for camera_id in _enabled_ids}

CAMERA_BUFFER_FLUSH_GRABS = max(0, int(os.getenv("CAMERA_BUFFER_FLUSH_GRABS", "1")))
CAMERA_DIRECT_V4L2_TUNE = os.getenv("CAMERA_DIRECT_V4L2_TUNE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_SHARED_FRAME_PRODUCER_ENABLED = os.getenv(
    "CAMERA_SHARED_FRAME_PRODUCER_ENABLED", "false"
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_SHARED_FRAME_PRODUCER_IDLE_SECONDS = max(
    1.0,
    float(os.getenv("CAMERA_SHARED_FRAME_PRODUCER_IDLE_SECONDS", "6.0")),
)
CAMERA_SHARED_FRAME_WAIT_MS = max(
    10,
    int(os.getenv("CAMERA_SHARED_FRAME_WAIT_MS", "260")),
)

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

# Experiment recording (Slice A)
EXPERIMENTS_STORAGE_PREFERRED_DIR = os.getenv("EXPERIMENTS_STORAGE_PREFERRED_DIR", "/mnt/usb_recordings")
EXPERIMENTS_STORAGE_FALLBACK_DIR = os.getenv("EXPERIMENTS_STORAGE_FALLBACK_DIR", "/tmp/jetson_dashboard_recordings")
EXPERIMENTS_ROOT_DIR = os.getenv("EXPERIMENTS_ROOT_DIR", EXPERIMENTS_STORAGE_PREFERRED_DIR)
EXPERIMENTS_SENSOR_INTERVAL_SECONDS = max(
    0.2,
    float(os.getenv("EXPERIMENTS_SENSOR_INTERVAL_SECONDS", "2.0")),
)
EXPERIMENTS_MANIFEST_FLUSH_SECONDS = max(
    0.5,
    float(os.getenv("EXPERIMENTS_MANIFEST_FLUSH_SECONDS", "2.0")),
)
EXPERIMENTS_MAX_HISTORY = max(1, int(os.getenv("EXPERIMENTS_MAX_HISTORY", "120")))
EXPERIMENTS_VIDEO_ENABLED = os.getenv("EXPERIMENTS_VIDEO_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EXPERIMENTS_VIDEO_FPS = max(1, int(os.getenv("EXPERIMENTS_VIDEO_FPS", "20")))
EXPERIMENTS_VIDEO_CODEC = os.getenv("EXPERIMENTS_VIDEO_CODEC", "mp4v")
EXPERIMENTS_VIDEO_SEGMENT_SECONDS = max(0, int(os.getenv("EXPERIMENTS_VIDEO_SEGMENT_SECONDS", "60")))
EXPERIMENTS_VIDEO_USE_SHARED_FRAME_CACHE = os.getenv("EXPERIMENTS_VIDEO_USE_SHARED_FRAME_CACHE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EXPERIMENTS_VIDEO_SHARED_MEMORY_STRICT = os.getenv(
    "EXPERIMENTS_VIDEO_SHARED_MEMORY_STRICT", "false"
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS = max(
    0.05,
    float(os.getenv("EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS", "0.35")),
)
EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS = max(
    0.1,
    float(os.getenv("EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS", "0.75")),
)
EXPERIMENTS_RETENTION_DAYS = max(0.0, float(os.getenv("EXPERIMENTS_RETENTION_DAYS", "7")))
EXPERIMENTS_MAX_TOTAL_GB = max(0.0, float(os.getenv("EXPERIMENTS_MAX_TOTAL_GB", "64")))
EXPERIMENTS_LOW_WATERMARK_GB = max(0.0, float(os.getenv("EXPERIMENTS_LOW_WATERMARK_GB", "3")))
EXPERIMENTS_CLEANUP_INTERVAL_SECONDS = max(
    10.0,
    float(os.getenv("EXPERIMENTS_CLEANUP_INTERVAL_SECONDS", "60")),
)
EXPERIMENTS_PLAYABLE_CACHE_DIR = os.getenv("EXPERIMENTS_PLAYABLE_CACHE_DIR", "/tmp/jetson_playable_cache")
EXPERIMENTS_PLAYABLE_CACHE_TTL_HOURS = max(
    0.0,
    float(os.getenv("EXPERIMENTS_PLAYABLE_CACHE_TTL_HOURS", "24")),
)
EXPERIMENTS_PLAYABLE_CACHE_MAX_GB = max(
    0.0,
    float(os.getenv("EXPERIMENTS_PLAYABLE_CACHE_MAX_GB", "5")),
)

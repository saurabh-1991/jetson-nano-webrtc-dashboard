"""Configuration for Jetson Nano Dashboard"""

import os


def _parse_optional_bool_env(var_name: str):
    raw = os.getenv(var_name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _parse_bool_with_default(var_name: str, default_value: bool) -> bool:
    parsed = _parse_optional_bool_env(var_name)
    if parsed is None:
        return bool(default_value)
    return bool(parsed)


def _parse_optional_camera_accel(var_name: str) -> str:
    raw = str(os.getenv(var_name, "")).strip().lower()
    return raw if raw in ("", "auto", "hardware", "compat", "direct") else ""


def _parse_camera_pipeline_strategy(var_name: str, default_value: str = "adaptive") -> str:
    raw = str(os.getenv(var_name, default_value)).strip().lower()
    if raw in ("adaptive", "single_path"):
        return raw
    return default_value


def _parse_optional_v4l2_io_mode(var_name: str):
    raw = str(os.getenv(var_name, "")).strip()
    if raw == "":
        return None
    if raw.isdigit() and int(raw) in (0, 1, 2, 3, 4, 5):
        return int(raw)
    return None


def _parse_camera_id_list(raw: str) -> list:
    ids = []
    for token in str(raw or "").split(","):
        camera_id = token.strip().lower()
        if camera_id and camera_id not in ids:
            ids.append(camera_id)
    return ids

# Camera Configuration
CAMERA_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA2_DEVICE = os.getenv("CAMERA2_DEVICE", "/dev/video1")
CAMERA2_WIDTH = int(os.getenv("CAMERA2_WIDTH", "640"))
CAMERA2_HEIGHT = int(os.getenv("CAMERA2_HEIGHT", "480"))
CAMERA2_FPS = int(os.getenv("CAMERA2_FPS", "30"))
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
CAMERA_PIPELINE_STRATEGY = _parse_camera_pipeline_strategy("CAMERA_PIPELINE_STRATEGY", "adaptive")
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

WEBRTC_ENABLED_CAMERA_IDS_RAW = os.getenv("WEBRTC_ENABLED_CAMERA_IDS", "cam1")
_webrtc_requested_ids = _parse_camera_id_list(WEBRTC_ENABLED_CAMERA_IDS_RAW)
if "*" in _webrtc_requested_ids:
    WEBRTC_ENABLED_CAMERA_IDS = list(CAMERA_PROFILES.keys())
else:
    WEBRTC_ENABLED_CAMERA_IDS = [
        camera_id for camera_id in _webrtc_requested_ids if camera_id in CAMERA_PROFILES
    ]

# Keep cam1 as default safe path when no valid id is provided.
if not WEBRTC_ENABLED_CAMERA_IDS:
    WEBRTC_ENABLED_CAMERA_IDS = [camera_id for camera_id in ("cam1",) if camera_id in CAMERA_PROFILES] or list(CAMERA_PROFILES.keys())

WEBRTC_MAX_CONNECTIONS = max(0, int(os.getenv("WEBRTC_MAX_CONNECTIONS", "1")))

# Optional external WebRTC gateway profile (e.g., MediaMTX WHEP)
MEDIA_WEBRTC_GATEWAY_ENABLED = os.getenv("MEDIA_WEBRTC_GATEWAY_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE = os.getenv("MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE", "").strip()
MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL = os.getenv("MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL", "").strip()
MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL = os.getenv("MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL", "").strip()

CAMERA_BUFFER_FLUSH_GRABS = max(0, int(os.getenv("CAMERA_BUFFER_FLUSH_GRABS", "1")))
CAMERA1_BUFFER_FLUSH_GRABS = max(0, int(os.getenv("CAMERA1_BUFFER_FLUSH_GRABS", str(CAMERA_BUFFER_FLUSH_GRABS))))
CAMERA2_BUFFER_FLUSH_GRABS = max(0, int(os.getenv("CAMERA2_BUFFER_FLUSH_GRABS", str(max(CAMERA_BUFFER_FLUSH_GRABS, 2)))))
CAMERA_DIRECT_V4L2_TUNE = os.getenv("CAMERA_DIRECT_V4L2_TUNE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_READ_STALL_SECONDS = max(0.2, float(os.getenv("CAMERA_READ_STALL_SECONDS", "1.2")))
CAMERA1_READ_STALL_SECONDS = max(
    0.2,
    float(os.getenv("CAMERA1_READ_STALL_SECONDS", str(CAMERA_READ_STALL_SECONDS))),
)
CAMERA2_READ_STALL_SECONDS = max(
    0.2,
    float(os.getenv("CAMERA2_READ_STALL_SECONDS", str(max(0.7, CAMERA_READ_STALL_SECONDS)))),
)
CAMERA_CONSECUTIVE_STALL_LIMIT = max(1, int(os.getenv("CAMERA_CONSECUTIVE_STALL_LIMIT", "3")))
CAMERA1_CONSECUTIVE_STALL_LIMIT = max(
    1,
    int(os.getenv("CAMERA1_CONSECUTIVE_STALL_LIMIT", str(CAMERA_CONSECUTIVE_STALL_LIMIT))),
)
CAMERA2_CONSECUTIVE_STALL_LIMIT = max(
    1,
    int(os.getenv("CAMERA2_CONSECUTIVE_STALL_LIMIT", str(max(2, CAMERA_CONSECUTIVE_STALL_LIMIT)))),
)
CAMERA_RECOVERY_BASE_BACKOFF_SECONDS = max(
    0.2,
    float(os.getenv("CAMERA_RECOVERY_BASE_BACKOFF_SECONDS", "2.0")),
)
CAMERA_RECOVERY_BACKOFF_MAX_SECONDS = max(
    CAMERA_RECOVERY_BASE_BACKOFF_SECONDS,
    float(os.getenv("CAMERA_RECOVERY_BACKOFF_MAX_SECONDS", "30.0")),
)
CAMERA_RECOVERY_MIN_REINIT_INTERVAL_SECONDS = max(
    0.0,
    float(os.getenv("CAMERA_RECOVERY_MIN_REINIT_INTERVAL_SECONDS", "0.75")),
)

# Phase 2 experimental live stream path (H.264 fragmented MP4 over HTTP)
CAMERA_H264_STREAM_ENABLED = os.getenv("CAMERA_H264_STREAM_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_H264_STREAM_BITRATE = max(200000, int(os.getenv("CAMERA_H264_STREAM_BITRATE", "1200000")))
CAMERA_H264_STREAM_GOP = max(5, int(os.getenv("CAMERA_H264_STREAM_GOP", "15")))
CAMERA_H264_STREAM_MAX_FPS = max(5, int(os.getenv("CAMERA_H264_STREAM_MAX_FPS", "20")))
CAMERA_H264_STREAM_ENCODER_PREFERENCE = os.getenv(
    "CAMERA_H264_STREAM_ENCODER_PREFERENCE",
    "h264_v4l2m2m,h264_omx,h264_nvmpi,libx264",
)
CAMERA_H264_STREAM_USE_GSTREAMER = os.getenv("CAMERA_H264_STREAM_USE_GSTREAMER", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CAMERA_H264_INPUT_MODE = os.getenv("CAMERA_H264_INPUT_MODE", "usb").strip().lower()
if CAMERA_H264_INPUT_MODE not in ("usb", "rtsp", "file"):
    CAMERA_H264_INPUT_MODE = "usb"
CAMERA_H264_RTSP_URL = os.getenv("CAMERA_H264_RTSP_URL", "").strip()
CAMERA_H264_RTSP_LATENCY_MS = max(0, int(os.getenv("CAMERA_H264_RTSP_LATENCY_MS", "80")))
CAMERA_H264_RTSP_PROTOCOLS = os.getenv("CAMERA_H264_RTSP_PROTOCOLS", "tcp").strip().lower() or "tcp"
CAMERA_H264_FILE_PATH = os.getenv("CAMERA_H264_FILE_PATH", "").strip()
CAMERA_H264_GST_INPUT_FORMAT = os.getenv("CAMERA_H264_GST_INPUT_FORMAT", "YUY2").strip().upper() or "YUY2"
CAMERA_H264_GST_FRAGMENT_MS = max(100, int(os.getenv("CAMERA_H264_GST_FRAGMENT_MS", "250")))
CAMERA_H264_GST_MAXPERF_ENABLE = os.getenv("CAMERA_H264_GST_MAXPERF_ENABLE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

CAMERA1_H264_STREAM_ENABLED = _parse_bool_with_default("CAMERA1_H264_STREAM_ENABLED", CAMERA_H264_STREAM_ENABLED)
CAMERA2_H264_STREAM_ENABLED = _parse_bool_with_default("CAMERA2_H264_STREAM_ENABLED", CAMERA_H264_STREAM_ENABLED)
CAMERA1_H264_STREAM_BITRATE = max(
    200000,
    int(os.getenv("CAMERA1_H264_STREAM_BITRATE", str(CAMERA_H264_STREAM_BITRATE))),
)
CAMERA2_H264_STREAM_BITRATE = max(
    200000,
    int(os.getenv("CAMERA2_H264_STREAM_BITRATE", str(CAMERA_H264_STREAM_BITRATE))),
)
CAMERA1_H264_STREAM_GOP = max(
    5,
    int(os.getenv("CAMERA1_H264_STREAM_GOP", str(CAMERA_H264_STREAM_GOP))),
)
CAMERA2_H264_STREAM_GOP = max(
    5,
    int(os.getenv("CAMERA2_H264_STREAM_GOP", str(CAMERA_H264_STREAM_GOP))),
)
CAMERA1_H264_STREAM_MAX_FPS = max(
    5,
    int(os.getenv("CAMERA1_H264_STREAM_MAX_FPS", str(CAMERA_H264_STREAM_MAX_FPS))),
)
CAMERA2_H264_STREAM_MAX_FPS = max(
    5,
    int(os.getenv("CAMERA2_H264_STREAM_MAX_FPS", str(CAMERA_H264_STREAM_MAX_FPS))),
)
CAMERA1_H264_STREAM_USE_GSTREAMER = _parse_bool_with_default(
    "CAMERA1_H264_STREAM_USE_GSTREAMER",
    CAMERA_H264_STREAM_USE_GSTREAMER,
)
CAMERA2_H264_STREAM_USE_GSTREAMER = _parse_bool_with_default(
    "CAMERA2_H264_STREAM_USE_GSTREAMER",
    CAMERA_H264_STREAM_USE_GSTREAMER,
)

CAMERA_H264_STREAM_PROFILES = {
    "cam1": {
        "enabled": CAMERA1_H264_STREAM_ENABLED,
        "bitrate": CAMERA1_H264_STREAM_BITRATE,
        "gop": CAMERA1_H264_STREAM_GOP,
        "max_fps": CAMERA1_H264_STREAM_MAX_FPS,
        "use_gstreamer": CAMERA1_H264_STREAM_USE_GSTREAMER,
    },
    "cam2": {
        "enabled": CAMERA2_H264_STREAM_ENABLED,
        "bitrate": CAMERA2_H264_STREAM_BITRATE,
        "gop": CAMERA2_H264_STREAM_GOP,
        "max_fps": CAMERA2_H264_STREAM_MAX_FPS,
        "use_gstreamer": CAMERA2_H264_STREAM_USE_GSTREAMER,
    },
}

CAMERA_H264_FAIL_COOLDOWN_THRESHOLD = max(
    1,
    int(os.getenv("CAMERA_H264_FAIL_COOLDOWN_THRESHOLD", "2")),
)
CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS = max(
    5,
    int(os.getenv("CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS", "45")),
)
CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS = max(
    CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS,
    int(os.getenv("CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS", "300")),
)
CAMERA_H264_FAIL_EARLY_SECONDS = max(
    1,
    int(os.getenv("CAMERA_H264_FAIL_EARLY_SECONDS", "3")),
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

GST_QUEUE_MAX_BUFFERS = max(1, int(os.getenv("GST_QUEUE_MAX_BUFFERS", "1")))
GST_QUEUE_MAX_BYTES = max(0, int(os.getenv("GST_QUEUE_MAX_BYTES", "0")))
GST_QUEUE_MAX_TIME_NS = max(0, int(os.getenv("GST_QUEUE_MAX_TIME_NS", "0")))
GST_QUEUE_REALTIME = (
    "queue leaky=downstream "
    f"max-size-buffers={GST_QUEUE_MAX_BUFFERS} "
    f"max-size-bytes={GST_QUEUE_MAX_BYTES} "
    f"max-size-time={GST_QUEUE_MAX_TIME_NS}"
)
GST_APPSINK_REALTIME = "appsink drop=true max-buffers=1 sync=false enable-last-sample=false wait-on-eos=false"

CAMERA2_GST_PIPELINE_MJPEG_HW_GRAY8 = (
    f"v4l2src io-mode=2 do-timestamp=true device={CAMERA2_DEVICE} ! "
    f"image/jpeg,width={CAMERA2_WIDTH},height={CAMERA2_HEIGHT},framerate={CAMERA2_FPS}/1 ! "
    "jpegparse ! "
    "nvjpegdec ! "
    "nvvidconv ! "
    "video/x-raw, format=GRAY8 ! " +
    GST_QUEUE_REALTIME + " ! "
    + GST_APPSINK_REALTIME
)

CAMERA2_GST_PIPELINE_MJPEG_COMPAT_GRAY8 = (
    f"v4l2src io-mode=2 do-timestamp=true device={CAMERA2_DEVICE} ! "
    f"image/jpeg,width={CAMERA2_WIDTH},height={CAMERA2_HEIGHT},framerate={CAMERA2_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=GRAY8 ! " +
    GST_QUEUE_REALTIME + " ! "
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
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
    + GST_APPSINK_REALTIME
)

# USB MJPEG compatibility path (software jpegdec)
USB_GST_PIPELINE_COMPAT = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegdec ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
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
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
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
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
    + GST_APPSINK_REALTIME
)

USB_GST_PIPELINE_COMPAT_RAW = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"video/x-raw,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
    + GST_APPSINK_REALTIME
)

# Most permissive USB fallback (avoid strict caps, let camera pick mode)
USB_GST_PIPELINE_COMPAT_ANY = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
    + GST_APPSINK_REALTIME
)

CSI_GST_PIPELINE = (
    f"nvarguscamerasrc sensor-id={CAMERA_CSI_SENSOR_ID} ! "
    f"video/x-raw(memory:NVMM), width={CAMERA_WIDTH}, height={CAMERA_HEIGHT}, format=NV12, framerate={CAMERA_FPS}/1 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! " +
    GST_QUEUE_REALTIME + " ! "
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

# Delta VFD (MS300) Modbus TCP control configuration.
# Keep disabled by default until networking/register mapping is verified on-site.
def _build_vfd_profile(prefix: str, default_enabled: bool = False) -> dict:
    enabled = _parse_bool_with_default(f"{prefix}_ENABLED", default_enabled)
    return {
        "enabled": bool(enabled),
        "host": os.getenv(f"{prefix}_HOST", "").strip(),
        "port": max(1, int(os.getenv(f"{prefix}_PORT", "502"))),
        "slave_id": max(1, int(os.getenv(f"{prefix}_SLAVE_ID", "1"))),
        "timeout_seconds": max(0.2, float(os.getenv(f"{prefix}_TIMEOUT_SECONDS", "1.0"))),
        "min_speed_hz": float(os.getenv(f"{prefix}_MIN_SPEED_HZ", "0.0")),
        "max_speed_hz": float(os.getenv(f"{prefix}_MAX_SPEED_HZ", "50.0")),
        "default_speed_hz": float(os.getenv(f"{prefix}_DEFAULT_SPEED_HZ", "0.0")),
        "speed_scale": max(1, int(os.getenv(f"{prefix}_SPEED_SCALE", "100"))),
        # Defaults match common Delta profiles but must be verified against MS300 datasheet.
        "run_command_register": int(os.getenv(f"{prefix}_RUN_COMMAND_REGISTER", "8192")),
        "speed_command_register": int(os.getenv(f"{prefix}_SPEED_COMMAND_REGISTER", "8193")),
        "run_forward_word": int(os.getenv(f"{prefix}_RUN_FORWARD_WORD", "1")),
        "stop_word": int(os.getenv(f"{prefix}_STOP_WORD", "0")),
        # Rate limit control writes to avoid burst toggling from UI retries.
        "min_write_interval_ms": max(50, int(os.getenv(f"{prefix}_MIN_WRITE_INTERVAL_MS", "150"))),
    }


VFD_CONFIGS = {
    "vfd1": _build_vfd_profile("VFD", default_enabled=False),
    "vfd2": _build_vfd_profile("VFD2", default_enabled=False),
}

# Backward-compatible aliases (vfd1 remains the default public control target).
VFD_ENABLED = bool(VFD_CONFIGS["vfd1"]["enabled"])
VFD_HOST = str(VFD_CONFIGS["vfd1"]["host"])
VFD_PORT = int(VFD_CONFIGS["vfd1"]["port"])
VFD_SLAVE_ID = int(VFD_CONFIGS["vfd1"]["slave_id"])
VFD_TIMEOUT_SECONDS = float(VFD_CONFIGS["vfd1"]["timeout_seconds"])
VFD_MIN_SPEED_HZ = float(VFD_CONFIGS["vfd1"]["min_speed_hz"])
VFD_MAX_SPEED_HZ = float(VFD_CONFIGS["vfd1"]["max_speed_hz"])
VFD_DEFAULT_SPEED_HZ = float(VFD_CONFIGS["vfd1"]["default_speed_hz"])
VFD_SPEED_SCALE = int(VFD_CONFIGS["vfd1"]["speed_scale"])
VFD_RUN_COMMAND_REGISTER = int(VFD_CONFIGS["vfd1"]["run_command_register"])
VFD_SPEED_COMMAND_REGISTER = int(VFD_CONFIGS["vfd1"]["speed_command_register"])
VFD_RUN_FORWARD_WORD = int(VFD_CONFIGS["vfd1"]["run_forward_word"])
VFD_STOP_WORD = int(VFD_CONFIGS["vfd1"]["stop_word"])
VFD_MIN_WRITE_INTERVAL_MS = int(VFD_CONFIGS["vfd1"]["min_write_interval_ms"])

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
EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS = max(
    0.05,
    float(os.getenv("EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS", "0.35")),
)
EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS = max(
    0.1,
    float(os.getenv("EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS", "0.75")),
)
EXPERIMENTS_VIDEO_QUEUE_MAX_FRAMES = max(
    1,
    int(os.getenv("EXPERIMENTS_VIDEO_QUEUE_MAX_FRAMES", "2")),
)
EXPERIMENTS_VIDEO_PRODUCER_POLL_SECONDS = max(
    0.002,
    float(os.getenv("EXPERIMENTS_VIDEO_PRODUCER_POLL_SECONDS", "0.008")),
)
EXPERIMENTS_VIDEO_PRODUCER_REBIND_THRESHOLD = max(
    3,
    # Counts genuine failed direct pulls only (spaced ~EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS
    # apart), so 5 * 0.75s ~= 3.75s of real camera unresponsiveness before rebinding.
    int(os.getenv("EXPERIMENTS_VIDEO_PRODUCER_REBIND_THRESHOLD", "5")),
)
EXPERIMENTS_VIDEO_PRODUCER_REBIND_COOLDOWN_SECONDS = max(
    0.5,
    float(os.getenv("EXPERIMENTS_VIDEO_PRODUCER_REBIND_COOLDOWN_SECONDS", "2.0")),
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
EXPERIMENTS_DOWNLOAD_MAX_CONCURRENT = max(
    1,
    int(os.getenv("EXPERIMENTS_DOWNLOAD_MAX_CONCURRENT", "1")),
)
EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_ACTIVE_RUN = os.getenv("EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_ACTIVE_RUN", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_LIVE_STREAMING = os.getenv("EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_LIVE_STREAMING", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EXPERIMENTS_DOWNLOAD_ARCHIVE_DIR = os.getenv("EXPERIMENTS_DOWNLOAD_ARCHIVE_DIR", "/tmp/jetson_download_archives")

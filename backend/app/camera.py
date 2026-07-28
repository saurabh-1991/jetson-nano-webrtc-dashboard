"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import re
import shlex
import subprocess
import time
import threading
import glob
import cv2
import numpy as np
from .config import (
    CAMERA_ALLOW_YUY2_FALLBACK,
    CAMERA_ACCELERATION,
    CAMERA1_ACCELERATION,
    CAMERA1_AUTO_BRIGHTNESS,
    CAMERA1_BUFFER_FLUSH_GRABS,
    CAMERA1_CONSECUTIVE_STALL_LIMIT,
    CAMERA1_READ_STALL_SECONDS,
    CAMERA1_USB_HW_MODE_LOCK,
    CAMERA1_USB_PREFLIGHT_VALIDATE,
    CAMERA1_USB_V4L2_IO_MODE,
    CAMERA1_USB_STARTUP_PROBE,
    CAMERA2_ACCELERATION,
    CAMERA2_ADAPTIVE_EXPOSURE,
    CAMERA2_BUFFER_FLUSH_GRABS,
    CAMERA2_CONSECUTIVE_STALL_LIMIT,
    CAMERA2_USB_HW_MODE_LOCK,
    CAMERA2_USB_PREFLIGHT_VALIDATE,
    CAMERA2_USB_V4L2_IO_MODE,
    CAMERA2_USB_STARTUP_PROBE,
    CAMERA_DEVICE,
    CAMERA_DEFAULT_ID,
    CAMERA_DIRECT_V4L2_TUNE,
    CAMERA_REQUIRE_HARDWARE_ACCEL,
    CAMERA_BUFFER_FLUSH_GRABS,
    CAMERA2_EXPOSURE_ADAPT_INTERVAL_SECONDS,
    CAMERA2_EXPOSURE_STEP,
    CAMERA2_FORCE_MJPEG,
    CAMERA2_GAIN_STEP,
    CAMERA2_GST_PIPELINE_MJPEG_COMPAT_GRAY8,
    CAMERA2_GST_PIPELINE_MJPEG_HW_GRAY8,
    CAMERA2_READ_STALL_SECONDS,
    CAMERA_CONSECUTIVE_STALL_LIMIT,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA2_DEVICE_HINT,
    CAMERA2_AUTO_BRIGHTNESS,
    CAMERA2_LUMA_TARGET,
    CAMERA2_LUMA_TOLERANCE,
    CAMERA2_PREFER_GRAY8,
    CAMERA_PROFILES,
    CAMERA_READ_STALL_SECONDS,
    CAMERA_SOURCE,
    CAMERA_USB_HW_MODE_LOCK,
    CAMERA_USB_PREFLIGHT_VALIDATE,
    CAMERA_USB_V4L2_IO_MODE,
    CAMERA_USB_STARTUP_PROBE,
    CAMERA_WIDTH,
    CUDA_ENABLED,
    GST_PIPELINE,
    GST_PIPELINE_IS_OVERRIDE,
    USB_GST_PIPELINE_COMPAT,
    USB_GST_PIPELINE_HW,
    USB_GST_PIPELINE_RAW_HW_UYVY,
    USB_GST_PIPELINE_RAW_HW_YUY2,
    USB_GST_PIPELINE_COMPAT_RAW,
    USB_GST_PIPELINE_COMPAT_ANY,
    PROCESSING_SCALE,
    GST_APPSINK_REALTIME,
    GST_QUEUE_REALTIME,
)

logger = logging.getLogger(__name__)

_gst_element_probe_cache = {}


def _gst_element_available(element_name: str) -> bool:
    """Check whether a GStreamer element is available in current runtime."""
    key = str(element_name or "").strip()
    if not key:
        return False

    if key in _gst_element_probe_cache:
        return _gst_element_probe_cache[key]

    try:
        result = subprocess.run(
            ["gst-inspect-1.0", key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=1.5,
            check=False,
        )
        ok = result.returncode == 0
    except Exception:
        ok = False

    _gst_element_probe_cache[key] = ok
    return ok


def _discover_v4l2_devices_static() -> list:
    devices = []
    for path in glob.glob("/dev/video*"):
        match = re.match(r"^/dev/video(\d+)$", path)
        if not match:
            continue
        devices.append((int(match.group(1)), path))
    devices.sort(key=lambda item: item[0])
    return [path for _, path in devices]


def _resolve_camera2_device_from_hint(default_device: str) -> str:
    hint_tokens = [tok.strip().lower() for tok in str(CAMERA2_DEVICE_HINT or "").split(",") if tok.strip()]
    if not hint_tokens:
        return default_device

    for dev_path in _discover_v4l2_devices_static():
        dev_name = dev_path.replace("/dev/", "")
        sys_name_path = f"/sys/class/video4linux/{dev_name}/name"
        try:
            with open(sys_name_path, "r", encoding="utf-8", errors="ignore") as f:
                friendly_name = (f.read() or "").strip().lower()
            if all(token in friendly_name for token in hint_tokens):
                logger.info("Resolved cam2 device by hint '%s': %s (%s)", CAMERA2_DEVICE_HINT, dev_path, friendly_name)
                return dev_path
        except Exception:
            continue

    return default_device


class CameraCapture:
    """Capture video from camera using GStreamer and OpenCV"""

    def __init__(self, camera_id: str = "cam1", profile: dict = None):
        profile = profile or {}
        self.camera_id = (camera_id or "cam1").lower()
        self.camera_device = str(profile.get("device") or CAMERA_DEVICE)
        self.capture_width = int(profile.get("width") or CAMERA_WIDTH)
        self.capture_height = int(profile.get("height") or CAMERA_HEIGHT)
        self.capture_fps = max(1, int(profile.get("fps") or CAMERA_FPS))
        self.jpeg_quality = int(profile.get("jpeg_quality") or 80)
        if self.camera_id == "cam2":
            self.buffer_flush_grabs = max(0, int(CAMERA2_BUFFER_FLUSH_GRABS))
        elif self.camera_id == "cam1":
            self.buffer_flush_grabs = max(0, int(CAMERA1_BUFFER_FLUSH_GRABS))
        else:
            self.buffer_flush_grabs = max(0, int(CAMERA_BUFFER_FLUSH_GRABS))
        if self.camera_id == "cam2":
            self.read_stall_seconds = float(CAMERA2_READ_STALL_SECONDS)
            self.consecutive_stall_limit = max(1, int(CAMERA2_CONSECUTIVE_STALL_LIMIT))
        elif self.camera_id == "cam1":
            self.read_stall_seconds = float(CAMERA1_READ_STALL_SECONDS)
            self.consecutive_stall_limit = max(1, int(CAMERA1_CONSECUTIVE_STALL_LIMIT))
        else:
            self.read_stall_seconds = float(CAMERA_READ_STALL_SECONDS)
            self.consecutive_stall_limit = max(1, int(CAMERA_CONSECUTIVE_STALL_LIMIT))
        self.force_mjpeg = bool(self.camera_id == "cam2" and CAMERA2_FORCE_MJPEG)
        self.prefer_gray8 = bool(self.camera_id == "cam2" and CAMERA2_PREFER_GRAY8)
        self.auto_brightness_enabled = bool(
            CAMERA2_AUTO_BRIGHTNESS if self.camera_id == "cam2" else CAMERA1_AUTO_BRIGHTNESS
        )
        self.cap = None
        self.is_open = False
        self.frame_count = 0
        self.target_fps = self.capture_fps
        self.frame_interval_seconds = 1.0 / float(self.target_fps)
        self.cuda_enabled = False
        self.cuda_available = False
        self.cuda_device_count = 0
        self._cuda_gpmat_ctor = None
        self.selected_pipeline = None
        self.selected_pipeline_mode = None
        self.selected_pipeline_source = None
        self.selected_pipeline_backend = None
        self.startup_probe_enabled = CAMERA_USB_STARTUP_PROBE
        if self.camera_id == "cam1" and CAMERA1_USB_STARTUP_PROBE is not None:
            self.startup_probe_enabled = bool(CAMERA1_USB_STARTUP_PROBE)
        if self.camera_id == "cam2" and CAMERA2_USB_STARTUP_PROBE is not None:
            self.startup_probe_enabled = bool(CAMERA2_USB_STARTUP_PROBE)
        self.usb_preflight_validate = CAMERA_USB_PREFLIGHT_VALIDATE
        if self.camera_id == "cam1" and CAMERA1_USB_PREFLIGHT_VALIDATE is not None:
            self.usb_preflight_validate = bool(CAMERA1_USB_PREFLIGHT_VALIDATE)
        if self.camera_id == "cam2" and CAMERA2_USB_PREFLIGHT_VALIDATE is not None:
            self.usb_preflight_validate = bool(CAMERA2_USB_PREFLIGHT_VALIDATE)
        if self.camera_id == "cam2" and self.usb_preflight_validate:
            # Cam2 IR streams can fail gst-launch preflight negotiation even when
            # OpenCV capture works reliably, which causes slow startups and
            # transient "camera unavailable" states. Prefer direct open probing.
            logger.info("Disabling GST preflight validation for cam2 to avoid false negatives")
            self.usb_preflight_validate = False
        self.usb_hw_mode_lock = CAMERA_USB_HW_MODE_LOCK
        if self.camera_id == "cam1" and CAMERA1_USB_HW_MODE_LOCK is not None:
            self.usb_hw_mode_lock = bool(CAMERA1_USB_HW_MODE_LOCK)
        if self.camera_id == "cam2" and CAMERA2_USB_HW_MODE_LOCK is not None:
            self.usb_hw_mode_lock = bool(CAMERA2_USB_HW_MODE_LOCK)
        self.usb_v4l2_io_mode = CAMERA_USB_V4L2_IO_MODE
        if self.camera_id == "cam1" and CAMERA1_USB_V4L2_IO_MODE is not None:
            self.usb_v4l2_io_mode = CAMERA1_USB_V4L2_IO_MODE
        if self.camera_id == "cam2" and CAMERA2_USB_V4L2_IO_MODE is not None:
            self.usb_v4l2_io_mode = CAMERA2_USB_V4L2_IO_MODE
        camera_accel_override = CAMERA1_ACCELERATION if self.camera_id == "cam1" else CAMERA2_ACCELERATION
        self.camera_acceleration_mode = str(camera_accel_override or CAMERA_ACCELERATION or "auto").lower()
        if self.camera_acceleration_mode not in ("auto", "hardware", "compat", "direct"):
            self.camera_acceleration_mode = "auto"
        self.startup_probe_formats = {}
        self.startup_probe_scores = {}
        self.startup_probe_order = []
        self.preflight_results = {}
        self.last_camera_error = None
        self.detected_usb_modes = {}
        self._frame_lock = threading.Lock()
        self._last_frame = None
        self._last_frame_timestamp = 0.0
        self._last_jpeg_bytes = None
        self._last_jpeg_frame_count = -1
        self._last_jpeg_quality = 80
        self._last_client_access_ts = time.time()
        self._frame_cache_hits = 0
        self._frame_cache_misses = 0
        self._jpeg_cache_hits = 0
        self._jpeg_cache_misses = 0
        self._jpeg_stale_fallback_hits = 0
        self._jpeg_encode_total_ms = 0.0
        self._jpeg_encode_count = 0
        self._read_failure_count = 0
        self._read_stall_count = 0
        self._max_consecutive_read_failures = 4
        self._recovery_attempt_count = 0
        self._recovery_success_count = 0
        self._recovery_failed_count = 0
        self._consecutive_recovery_failures = 0
        self._recovery_base_backoff_seconds = 1.5
        self._recovery_backoff_max_seconds = 20.0
        self._next_recovery_allowed_ts = 0.0
        self._last_recovery_ts = None
        self._last_recovery_reason = None
        self._adaptive_exposure_enabled = bool(
            CAMERA2_ADAPTIVE_EXPOSURE and self.camera_id == "cam2" and not self.auto_brightness_enabled
        )
        self._next_exposure_adjust_ts = 0.0
        self._last_luma_mean = None
        self._v4l2_ctrl_ranges = {}
        self._current_exposure_absolute = None
        self._current_gain = None
        self.opencv_gstreamer_enabled = self._check_opencv_gstreamer_support()
        self.nvjpegdec_available = _gst_element_available("nvjpegdec")
        self.nvvidconv_available = _gst_element_available("nvvidconv")
        self.hardware_pipeline_eligible = bool(
            self.opencv_gstreamer_enabled and self.nvjpegdec_available and self.nvvidconv_available
        )
        self._detect_cuda_capability()
        self._initialize_camera()

    def _set_v4l2_control(self, control_name: str, value: int) -> bool:
        try:
            result = subprocess.run(
                [
                    "v4l2-ctl",
                    "--device",
                    self.camera_device,
                    "--set-ctrl",
                    f"{control_name}={int(value)}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=1.5,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _load_v4l2_control_ranges(self):
        """Parse available V4L2 control ranges for adaptive low-light tuning."""
        self._v4l2_ctrl_ranges = {}
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", self.camera_device, "-L"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=2.0,
                check=False,
            )
            if result.returncode != 0:
                return

            for raw_line in (result.stdout or "").splitlines():
                line = raw_line.strip()
                if not line or ":" not in line:
                    continue
                name = line.split(":", 1)[0].strip()
                min_match = re.search(r"min=(-?\d+)", line)
                max_match = re.search(r"max=(-?\d+)", line)
                default_match = re.search(r"default=(-?\d+)", line)
                if min_match and max_match:
                    self._v4l2_ctrl_ranges[name] = {
                        "min": int(min_match.group(1)),
                        "max": int(max_match.group(1)),
                        "default": int(default_match.group(1)) if default_match else None,
                    }
        except Exception:
            self._v4l2_ctrl_ranges = {}

    def _apply_initial_ir_low_light_controls(self):
        """Apply best-effort defaults for dark-room IR usage on UVC cameras."""
        if not self._adaptive_exposure_enabled:
            return

        self._load_v4l2_control_ranges()

        # Try enabling auto exposure while disabling FPS-priority behavior that often boosts gain/noise.
        self._set_v4l2_control("exposure_auto", 3)
        self._set_v4l2_control("exposure_auto_priority", 0)

        if "exposure_absolute" in self._v4l2_ctrl_ranges:
            ctrl = self._v4l2_ctrl_ranges["exposure_absolute"]
            default_val = ctrl.get("default")
            if default_val is None:
                default_val = int((ctrl["min"] + ctrl["max"]) / 2)
            self._current_exposure_absolute = max(ctrl["min"], min(ctrl["max"], int(default_val)))

        if "gain" in self._v4l2_ctrl_ranges:
            ctrl = self._v4l2_ctrl_ranges["gain"]
            default_val = ctrl.get("default")
            if default_val is None:
                default_val = int((ctrl["min"] + ctrl["max"]) / 3)
            self._current_gain = max(ctrl["min"], min(ctrl["max"], int(default_val)))

    def _apply_auto_brightness_controls(self):
        """Best-effort auto controls for USB webcams to keep brightness adaptive."""
        if not self.auto_brightness_enabled:
            return

        self._set_v4l2_control("exposure_auto", 3)
        self._set_v4l2_control("exposure_auto_priority", 0)
        self._set_v4l2_control("white_balance_temperature_auto", 1)

        # Keep gain moderate if control exists to reduce dark-scene grain spikes.
        self._load_v4l2_control_ranges()
        if "gain" in self._v4l2_ctrl_ranges:
            ctrl = self._v4l2_ctrl_ranges["gain"]
            target_gain = int((2 * ctrl["min"] + ctrl["max"]) / 3)
            self._set_v4l2_control("gain", target_gain)

    def _maybe_adapt_ir_exposure(self, frame_bgr: np.ndarray):
        """Adjust exposure/gain occasionally based on frame luminance for low-light IR scene."""
        if not self._adaptive_exposure_enabled:
            return

        now_ts = time.time()
        if now_ts < self._next_exposure_adjust_ts:
            return
        self._next_exposure_adjust_ts = now_ts + float(CAMERA2_EXPOSURE_ADAPT_INTERVAL_SECONDS)

        if frame_bgr is None or frame_bgr.size == 0:
            return

        try:
            if len(frame_bgr.shape) == 2:
                gray = frame_bgr
            else:
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            luma = float(np.mean(gray))
            self._last_luma_mean = luma
        except Exception:
            return

        lower = float(CAMERA2_LUMA_TARGET) - float(CAMERA2_LUMA_TOLERANCE)
        upper = float(CAMERA2_LUMA_TARGET) + float(CAMERA2_LUMA_TOLERANCE)

        if lower <= luma <= upper:
            return

        # If very dark: increase exposure first, then gain.
        if luma < lower:
            if self._current_exposure_absolute is not None and "exposure_absolute" in self._v4l2_ctrl_ranges:
                ctrl = self._v4l2_ctrl_ranges["exposure_absolute"]
                new_val = min(ctrl["max"], int(self._current_exposure_absolute) + int(CAMERA2_EXPOSURE_STEP))
                if new_val != self._current_exposure_absolute and self._set_v4l2_control("exposure_absolute", new_val):
                    self._current_exposure_absolute = new_val
                    return

            if self._current_gain is not None and "gain" in self._v4l2_ctrl_ranges:
                ctrl = self._v4l2_ctrl_ranges["gain"]
                new_val = min(ctrl["max"], int(self._current_gain) + int(CAMERA2_GAIN_STEP))
                if new_val != self._current_gain and self._set_v4l2_control("gain", new_val):
                    self._current_gain = new_val
                    return

        # If too bright: reduce gain first, then exposure.
        if luma > upper:
            if self._current_gain is not None and "gain" in self._v4l2_ctrl_ranges:
                ctrl = self._v4l2_ctrl_ranges["gain"]
                new_val = max(ctrl["min"], int(self._current_gain) - int(CAMERA2_GAIN_STEP))
                if new_val != self._current_gain and self._set_v4l2_control("gain", new_val):
                    self._current_gain = new_val
                    return

            if self._current_exposure_absolute is not None and "exposure_absolute" in self._v4l2_ctrl_ranges:
                ctrl = self._v4l2_ctrl_ranges["exposure_absolute"]
                new_val = max(ctrl["min"], int(self._current_exposure_absolute) - int(CAMERA2_EXPOSURE_STEP))
                if new_val != self._current_exposure_absolute and self._set_v4l2_control("exposure_absolute", new_val):
                    self._current_exposure_absolute = new_val
                    return

    def _record_recovery_result(self, success: bool, reason: str):
        """Track recovery outcomes and apply adaptive backoff on repeated failures."""
        now_ts = time.time()
        self._last_recovery_ts = now_ts
        self._last_recovery_reason = reason

        if success:
            self._recovery_success_count += 1
            self._consecutive_recovery_failures = 0
            self._next_recovery_allowed_ts = 0.0
            return

        self._recovery_failed_count += 1
        self._consecutive_recovery_failures += 1
        backoff_seconds = min(
            self._recovery_backoff_max_seconds,
            self._recovery_base_backoff_seconds * (2 ** max(0, self._consecutive_recovery_failures - 1)),
        )
        self._next_recovery_allowed_ts = now_ts + backoff_seconds
        logger.warning(
            "Camera recovery failed (reason=%s). consecutive_failures=%s next_retry_in=%.2fs",
            reason,
            self._consecutive_recovery_failures,
            backoff_seconds,
        )

    def _attempt_recovery_locked(self, reason: str) -> bool:
        """Attempt to recover camera while holding frame lock."""
        now_ts = time.time()
        if now_ts < self._next_recovery_allowed_ts:
            return False

        self._recovery_attempt_count += 1
        logger.info("Attempting camera recovery #%s (%s)", self._recovery_attempt_count, reason)
        self._initialize_camera()
        success = bool(self.is_open and self.cap is not None)
        self._record_recovery_result(success, reason)
        return success

    def _discover_v4l2_devices(self) -> list:
        """Discover available /dev/video* nodes sorted by numeric index."""
        return _discover_v4l2_devices_static()

    def _check_opencv_gstreamer_support(self) -> bool:
        """Detect whether OpenCV can actually use CAP_GSTREAMER at runtime."""
        build_flag = None
        try:
            info = cv2.getBuildInformation()
            # Handles variants like:
            # - "GStreamer: YES"
            # - "GStreamer:                   YES"
            # - "GStreamer: NO"
            match = re.search(r"gstreamer\s*:\s*(yes|no)", info, flags=re.IGNORECASE)
            if match:
                build_flag = match.group(1).strip().lower() == "yes"
        except Exception as e:
            logger.warning("Unable to read OpenCV build info (%s); falling back to runtime probe", e)

        runtime_probe_ok = False
        cap = None
        try:
            # Lightweight probe for CAP_GSTREAMER in this runtime.
            # `videotestsrc` avoids touching camera devices during capability detection.
            probe_pipeline = (
                "videotestsrc num-buffers=1 ! "
                "video/x-raw,format=BGR,width=160,height=120,framerate=1/1 ! "
                "appsink drop=1 max-buffers=1 sync=false"
            )
            cap = cv2.VideoCapture(probe_pipeline, cv2.CAP_GSTREAMER)
            if cap is not None and cap.isOpened():
                ret, frame = cap.read()
                runtime_probe_ok = bool(ret and frame is not None)
        except Exception:
            runtime_probe_ok = False
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

        # If build info explicitly says YES, trust it. Otherwise require a successful runtime probe.
        enabled = bool(build_flag is True or runtime_probe_ok)
        if not enabled:
            logger.warning(
                "OpenCV CAP_GSTREAMER unavailable (build_flag=%s runtime_probe_ok=%s); USB capture will use V4L2 fallback",
                build_flag,
                runtime_probe_ok,
            )
        return enabled

    def _build_usb_pipeline_mjpeg_compat(self, width: int, height: int, fps: int) -> str:
        """Build a software-compatible MJPEG pipeline known to work with OpenCV appsink."""
        io_mode_clause = f"io-mode={int(self.usb_v4l2_io_mode)} " if self.usb_v4l2_io_mode is not None else ""
        return (
            f"v4l2src {io_mode_clause}do-timestamp=true device={self.camera_device} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "jpegdec ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! " +
            GST_QUEUE_REALTIME + " ! " + GST_APPSINK_REALTIME
        )

    def _build_usb_pipeline_yuy2_compat(self, width: int, height: int, fps: int) -> str:
        """Build a software-compatible YUY2 pipeline known to work with OpenCV appsink."""
        io_mode_clause = f"io-mode={int(self.usb_v4l2_io_mode)} " if self.usb_v4l2_io_mode is not None else ""
        return (
            f"v4l2src {io_mode_clause}do-timestamp=true device={self.camera_device} ! "
            f"video/x-raw,format=YUY2,width={width},height={height},framerate={fps}/1 ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! " +
            GST_QUEUE_REALTIME + " ! " + GST_APPSINK_REALTIME
        )

    def _build_usb_pipeline_mjpeg_hw(self, width: int, height: int, fps: int) -> str:
        """Build an NVIDIA hardware MJPEG pipeline bound to this camera profile."""
        io_mode_clause = f"io-mode={int(self.usb_v4l2_io_mode)} " if self.usb_v4l2_io_mode is not None else ""
        return (
            f"v4l2src {io_mode_clause}do-timestamp=true device={self.camera_device} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "jpegparse ! "
            "nvjpegdec ! "
            "nvvidconv ! "
            "video/x-raw, format=BGRx ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! " +
            GST_QUEUE_REALTIME + " ! " + GST_APPSINK_REALTIME
        )

    def _build_usb_pipeline_mjpeg_hw_stable(self, width: int, height: int, fps: int) -> str:
        """Build a stricter MJPEG HW path with explicit parser/queue to reduce startup jitter."""
        io_mode_clause = f"io-mode={int(self.usb_v4l2_io_mode)} " if self.usb_v4l2_io_mode is not None else ""
        return (
            f"v4l2src {io_mode_clause}do-timestamp=true device={self.camera_device} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "jpegparse ! " +
            GST_QUEUE_REALTIME + " ! " +
            "nvjpegdec ! "
            "nvvidconv ! "
            "video/x-raw, format=BGRx ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! " +
            GST_QUEUE_REALTIME + " ! " + GST_APPSINK_REALTIME
        )

    def _pick_best_mode(self, modes, preferred_w, preferred_h, preferred_fps):
        """Pick nearest advertised mode using a simple distance metric."""
        if not modes:
            return None

        best = None
        best_score = None

        for mode in modes:
            w, h, fps = mode
            score = (
                abs(w - preferred_w) * 1000
                + abs(h - preferred_h) * 1000
                + abs(fps - preferred_fps)
            )
            if best_score is None or score < best_score:
                best = mode
                best_score = score

        return best

    def _detect_usb_modes(self) -> dict:
        """Parse v4l2-ctl mode list into {'mjpeg': [(w,h,fps)], 'yuy2': [(w,h,fps)]}."""
        parsed = {"mjpeg": [], "yuy2": []}

        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", self.camera_device, "--list-formats-ext"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=3,
                check=False,
            )

            if result.returncode != 0:
                return parsed

            current_format = None
            current_size = None

            for raw_line in (result.stdout or "").splitlines():
                line = raw_line.strip()

                if "Pixel Format:" in line:
                    lower = line.lower()
                    if "'mjpg'" in lower or "mjpeg" in lower:
                        current_format = "mjpeg"
                    elif "'yuyv'" in lower or "yuy2" in lower or "yuyv" in lower:
                        current_format = "yuy2"
                    else:
                        current_format = None
                    current_size = None
                    continue

                size_match = re.search(r"Size:\s*Discrete\s*(\d+)x(\d+)", line)
                if size_match:
                    current_size = (int(size_match.group(1)), int(size_match.group(2)))
                    continue

                fps_match = re.search(r"\((\d+(?:\.\d+)?)\s*fps\)", line)
                if fps_match and current_format and current_size:
                    fps = int(float(fps_match.group(1)))
                    parsed[current_format].append((current_size[0], current_size[1], fps))

            # Deduplicate while preserving order
            for key in parsed:
                seen = set()
                uniq = []
                for mode in parsed[key]:
                    if mode not in seen:
                        uniq.append(mode)
                        seen.add(mode)
                parsed[key] = uniq

            return parsed
        except Exception:
            return parsed

    def _build_adaptive_usb_candidates(self) -> list:
        """Build USB candidates from camera-advertised formats with compatibility-first pipelines."""
        candidates = []
        modes = self._detect_usb_modes()
        self.detected_usb_modes = modes

        mjpeg_mode = self._pick_best_mode(modes.get("mjpeg", []), 1280, 720, 30)
        yuy2_mode = self._pick_best_mode(modes.get("yuy2", []), 640, 480, 30)

        if mjpeg_mode:
            mw, mh, mfps = mjpeg_mode
            candidates.append(
                {
                    "source": self._build_usb_pipeline_mjpeg_compat(mw, mh, mfps),
                    "backend": cv2.CAP_GSTREAMER,
                    "label": (
                        "USB adaptive MJPEG compatibility pipeline "
                        f"({mw}x{mh}@{mfps})"
                    ),
                    "format_key": "mjpeg",
                }
            )

        if yuy2_mode and CAMERA_ALLOW_YUY2_FALLBACK and not self.force_mjpeg:
            yw, yh, yfps = yuy2_mode
            candidates.append(
                {
                    "source": self._build_usb_pipeline_yuy2_compat(yw, yh, yfps),
                    "backend": cv2.CAP_GSTREAMER,
                    "label": (
                        "USB adaptive YUY2 compatibility pipeline "
                        f"({yw}x{yh}@{yfps})"
                    ),
                    "format_key": "yuy2",
                }
            )

        return candidates

    def _build_locked_mjpeg_mode_candidate(self):
        """Build a profile-locked MJPEG mode candidate from probed camera capabilities."""
        if not self.detected_usb_modes:
            self.detected_usb_modes = self._detect_usb_modes()

        mjpeg_mode = self._pick_best_mode(
            self.detected_usb_modes.get("mjpeg", []),
            int(self.capture_width),
            int(self.capture_height),
            int(self.capture_fps),
        )
        if not mjpeg_mode:
            return None

        mw, mh, mfps = mjpeg_mode
        return {
            "source": self._build_usb_pipeline_mjpeg_hw_stable(mw, mh, mfps),
            "backend": cv2.CAP_GSTREAMER,
            "label": f"USB hardware pipeline mode-locked ({mw}x{mh}@{mfps})",
            "format_key": "mjpeg",
        }

    def _open_v4l2_with_preferred_format(self):
        """Try direct OpenCV V4L2 with camera-advertised preferred formats."""
        # Ensure we have parsed modes; this is inexpensive and cached in diagnostics.
        if not self.detected_usb_modes:
            self.detected_usb_modes = self._detect_usb_modes()

        preferred = []

        mjpeg_mode = self._pick_best_mode(self.detected_usb_modes.get("mjpeg", []), 1280, 720, 30)
        if mjpeg_mode:
            preferred.append(("MJPG", mjpeg_mode))

        yuy2_mode = self._pick_best_mode(self.detected_usb_modes.get("yuy2", []), 640, 480, 30)
        if yuy2_mode and CAMERA_ALLOW_YUY2_FALLBACK and not self.force_mjpeg:
            preferred.append(("YUYV", yuy2_mode))

        if not preferred:
            preferred.append(("MJPG", (1280, 720, 30)))

        camera_index = 0
        try:
            if isinstance(self.camera_device, str) and self.camera_device.startswith("/dev/video"):
                camera_index = int(self.camera_device.replace("/dev/video", ""))
        except Exception:
            camera_index = 0

        for fourcc_name, mode in preferred:
            w, h, fps = mode
            # OpenCV 3.2 (JP4.6 apt build) does not always support the 2-argument
            # VideoCapture constructor in Python bindings.
            cap = None
            cap_v4l2 = getattr(cv2, "CAP_V4L2", None)
            if cap_v4l2 is not None:
                try:
                    cap = cv2.VideoCapture(camera_index, cap_v4l2)
                except Exception:
                    cap = None
            if cap is None:
                cap = cv2.VideoCapture(camera_index)
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue

            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc_name))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(w))
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(h))
                cap.set(cv2.CAP_PROP_FPS, int(fps))

                ret, frame = cap.read()
                if ret and frame is not None:
                    self.selected_pipeline = (
                        f"V4L2 direct preferred format {fourcc_name} ({w}x{h}@{fps})"
                    )
                    self.selected_pipeline_mode = "compat"
                    self.selected_pipeline_source = self.camera_device
                    self.selected_pipeline_backend = None
                    logger.info("Camera opened using %s", self.selected_pipeline)
                    return cap
            except Exception:
                pass

            cap.release()

        return None

    def _tune_direct_v4l2_capture(self, cap) -> None:
        """Apply low-latency capture settings to direct V4L2 handles."""
        if not CAMERA_DIRECT_V4L2_TUNE or cap is None:
            return

        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        target_mode = None
        try:
            if not self.detected_usb_modes:
                self.detected_usb_modes = self._detect_usb_modes()
            target_mode = self._pick_best_mode(
                self.detected_usb_modes.get("mjpeg", []),
                int(self.capture_width),
                int(self.capture_height),
                int(self.capture_fps),
            )
        except Exception:
            target_mode = None

        w = int(target_mode[0]) if target_mode else int(self.capture_width)
        h = int(target_mode[1]) if target_mode else int(self.capture_height)
        fps = int(target_mode[2]) if target_mode else int(self.capture_fps)

        # Prefer MJPEG over USB to reduce bus load and improve frame freshness.
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass

        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_FPS, max(1, fps))
        except Exception:
            pass

        logger.info(
            "Applied direct V4L2 tuning for %s: %sx%s@%s (camera=%s)",
            self.camera_device,
            w,
            h,
            fps,
            self.camera_id,
        )

    def _infer_pipeline_mode(self, label: str) -> str:
        """Infer pipeline mode from descriptive label."""
        text = (label or "").lower()

        if "configured gstreamer pipeline" in text and GST_PIPELINE_IS_OVERRIDE:
            return "override"

        if "hardware" in text or "nvjpegdec" in text or "nvvidconv" in text:
            return "hardware"

        if "compatibility" in text or "jpegdec" in text or "videoconvert" in text:
            return "compat"

        return "custom"

    def _resolve_cuda_gpmat_ctor(self):
        """Resolve available OpenCV CUDA GpuMat constructor across versions/builds."""
        # Older bindings often expose cv2.cuda_GpuMat
        if hasattr(cv2, "cuda_GpuMat"):
            return cv2.cuda_GpuMat

        # Some builds expose cv2.cuda.GpuMat
        if hasattr(cv2, "cuda") and hasattr(cv2.cuda, "GpuMat"):
            return cv2.cuda.GpuMat

        return None

    def _detect_cuda_capability(self):
        """Detect CUDA support at startup and set runtime flags."""
        if not CUDA_ENABLED:
            logger.info("CUDA processing disabled by configuration")
            self.cuda_enabled = False
            self.cuda_available = False
            self.cuda_device_count = 0
            return

        if not hasattr(cv2, "cuda"):
            logger.warning("OpenCV build has no cv2.cuda module; using CPU fallback")
            self.cuda_enabled = False
            self.cuda_available = False
            self.cuda_device_count = 0
            return

        self._cuda_gpmat_ctor = self._resolve_cuda_gpmat_ctor()
        if self._cuda_gpmat_ctor is None:
            logger.warning(
                "OpenCV CUDA module exists but GpuMat constructor is unavailable; using CPU fallback"
            )
            self.cuda_enabled = False
            self.cuda_available = False
            self.cuda_device_count = 0
            return

        if not hasattr(cv2.cuda, "resize"):
            logger.warning("OpenCV CUDA resize API unavailable; using CPU fallback")
            self.cuda_enabled = False
            self.cuda_available = False
            self.cuda_device_count = 0
            return

        try:
            count = int(cv2.cuda.getCudaEnabledDeviceCount())
            self.cuda_device_count = count
            self.cuda_available = count > 0
            self.cuda_enabled = self.cuda_available

            if self.cuda_available:
                logger.info(f"CUDA enabled with {count} device(s)")
            else:
                logger.warning(
                    "CUDA requested but OpenCV reports zero CUDA devices; using CPU fallback"
                )
        except Exception as e:
            logger.warning(f"OpenCV CUDA runtime unavailable: {e}; using CPU fallback")
            self.cuda_enabled = False
            self.cuda_available = False
            self.cuda_device_count = 0

    def _detect_usb_supported_formats(self) -> dict:
        """Detect USB camera-advertised formats via v4l2-ctl when available."""
        # Conservative default: keep all candidates enabled if detection is unavailable.
        default_formats = {"mjpeg": True, "yuy2": True, "uyvy": True}

        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", self.camera_device, "--list-formats-ext"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=2,
                check=False,
            )

            if result.returncode != 0:
                logger.info(
                    "USB format probe skipped (v4l2-ctl returned %s); keeping default candidate set",
                    result.returncode,
                )
                self.startup_probe_formats = default_formats.copy()
                return default_formats

            output = (result.stdout or "").lower()
            detected = {
                "mjpeg": ("mjpg" in output) or ("mjpeg" in output),
                "yuy2": ("yuyv" in output) or ("yuy2" in output),
                "uyvy": "uyvy" in output,
            }

            if not any(detected.values()):
                logger.info(
                    "USB format probe found no explicit MJPEG/YUY2/UYVY markers; keeping default candidate set"
                )
                self.startup_probe_formats = default_formats.copy()
                return default_formats

            supported = [name for name, enabled in detected.items() if enabled]
            logger.info("USB format probe detected: %s", ", ".join(supported))
            self.startup_probe_formats = detected.copy()
            return detected

        except FileNotFoundError:
            logger.info("USB format probe skipped (v4l2-ctl not installed)")
            self.startup_probe_formats = default_formats.copy()
            return default_formats
        except Exception as e:
            logger.info("USB format probe failed (%s); keeping default candidate set", e)
            self.startup_probe_formats = default_formats.copy()
            return default_formats

    def _benchmark_capture_source(
        self,
        source,
        backend,
        label,
        probe_frames: int = 8,
        probe_timeout_seconds: float = 2.0,
    ) -> float:
        """Probe a capture source quickly and return effective FPS-like score."""
        cap = self._open_capture(source, backend, f"{label} [startup-probe]")
        if cap is None:
            self.startup_probe_scores[label] = 0.0
            return 0.0

        try:
            frames = 0
            started = time.perf_counter()
            deadline = started + probe_timeout_seconds

            while frames < probe_frames and time.perf_counter() < deadline:
                ret, frame = cap.read()
                if not ret or frame is None:
                    break
                frames += 1

            elapsed = max(time.perf_counter() - started, 1e-6)
            if frames < 2:
                logger.info("Startup probe %s insufficient frames (%d)", label, frames)
                return 0.0

            score = frames / elapsed
            logger.info(
                "Startup probe %s score %.2f fps-equivalent (%d frames / %.3fs)",
                label,
                score,
                frames,
                elapsed,
            )
            self.startup_probe_scores[label] = score
            return score
        except Exception as e:
            logger.info("Startup probe failed for %s: %s", label, e)
            self.startup_probe_scores[label] = 0.0
            return 0.0
        finally:
            try:
                cap.release()
            except Exception:
                pass

    def _reorder_usb_candidates_with_probe(self, candidates: list) -> list:
        """Reorder USB candidates using format hints and quick runtime probing."""
        if not self.startup_probe_enabled or not candidates:
            return candidates

        # Cam1 on Jetson Nano has shown transient open failures after repeated
        # startup probe opens/closes across multiple candidate pipelines.
        # Keep the declared candidate order for cam1 to reduce churn.
        if self.camera_id == "cam1":
            self.startup_probe_order = [item.get("label") for item in candidates]
            logger.info("Skipping USB startup probe for cam1 to reduce open/close churn")
            return candidates

        supported_formats = self._detect_usb_supported_formats()

        supported_candidates = []
        unsupported_candidates = []

        for candidate in candidates:
            format_key = candidate.get("format_key", "any")
            is_supported = format_key == "any" or supported_formats.get(format_key, True)
            if is_supported:
                supported_candidates.append(candidate)
            else:
                unsupported_candidates.append(candidate)

        scored = []
        for candidate in supported_candidates:
            score = self._benchmark_capture_source(
                candidate["source"],
                candidate["backend"],
                candidate["label"],
            )
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)

        ordered = []
        seen = set()

        for _, candidate in scored:
            key = "{0}|{1}".format(candidate["source"], candidate["backend"])
            if key not in seen:
                ordered.append(candidate)
                seen.add(key)

        for candidate in unsupported_candidates:
            key = "{0}|{1}".format(candidate["source"], candidate["backend"])
            if key not in seen:
                ordered.append(candidate)
                seen.add(key)

        # Keep any original candidates that somehow were not included above.
        for candidate in candidates:
            key = "{0}|{1}".format(candidate["source"], candidate["backend"])
            if key not in seen:
                ordered.append(candidate)
                seen.add(key)

        if ordered:
            logger.info(
                "USB startup probe selected initial candidate order: %s",
                " -> ".join(item["label"] for item in ordered),
            )
            self.startup_probe_order = [item["label"] for item in ordered]
        else:
            self.startup_probe_order = []

        return ordered

    def _build_gst_preflight_pipeline(self, pipeline: str, num_buffers: int = 20) -> str:
        """Convert an appsink pipeline to a short-lived gst-launch preflight pipeline."""
        probe_pipeline = str(pipeline or "")
        if not probe_pipeline:
            return probe_pipeline

        # Ensure the capture source is finite to avoid hangs.
        if "v4l2src" in probe_pipeline and "num-buffers=" not in probe_pipeline:
            probe_pipeline = probe_pipeline.replace("v4l2src ", f"v4l2src num-buffers={int(num_buffers)} ", 1)

        # Replace terminal appsink branch with fakesink for deterministic probe.
        probe_pipeline = re.sub(r"appsink\b.*$", "fakesink sync=false", probe_pipeline)
        return probe_pipeline

    def _gst_preflight_check(self, pipeline: str, label: str, timeout_seconds: float = 7.0) -> bool:
        """Run a lightweight gst-launch probe and return True when pipeline is viable."""
        try:
            launch_check = subprocess.run(
                ["gst-launch-1.0", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=1.5,
                check=False,
            )
            has_gst_launch = launch_check.returncode == 0
        except Exception:
            has_gst_launch = False

        if not has_gst_launch:
            self.preflight_results[label] = {
                "status": "skipped",
                "reason": "gst-launch-1.0 unavailable",
            }
            return True

        probe_pipeline = self._build_gst_preflight_pipeline(pipeline)
        if not probe_pipeline:
            self.preflight_results[label] = {"status": "skipped", "reason": "empty pipeline"}
            return False

        try:
            cmd = ["gst-launch-1.0", "-q"] + shlex.split(probe_pipeline)
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
            )
            ok = result.returncode == 0
            self.preflight_results[label] = {
                "status": "pass" if ok else "fail",
                "returncode": result.returncode,
                "stderr": (result.stderr or "").strip()[:500],
            }
            if not ok:
                logger.info("GST preflight rejected %s (rc=%s)", label, result.returncode)
            return ok
        except subprocess.TimeoutExpired:
            self.preflight_results[label] = {"status": "fail", "reason": "timeout"}
            logger.info("GST preflight timeout for %s", label)
            return False
        except Exception as e:
            self.preflight_results[label] = {"status": "error", "reason": str(e)[:240]}
            logger.info("GST preflight error for %s: %s", label, e)
            return False

    def _apply_device_profile_to_pipeline(self, pipeline: str) -> str:
        """Rebind pipeline string to this camera device and profile dimensions."""
        if not isinstance(pipeline, str) or not pipeline:
            return pipeline

        rebased = pipeline.replace(f"device={CAMERA_DEVICE}", f"device={self.camera_device}")

        rebased = re.sub(
            r"width=\d+",
            f"width={self.capture_width}",
            rebased,
        )
        rebased = re.sub(
            r"height=\d+",
            f"height={self.capture_height}",
            rebased,
        )
        rebased = re.sub(
            r"framerate=\d+/1",
            f"framerate={self.capture_fps}/1",
            rebased,
        )
        return rebased

    def _initialize_camera(self):
        """Initialize camera capture"""
        try:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.is_open = False

            self.last_camera_error = None
            self.startup_probe_scores = {}
            self.startup_probe_order = []

            fallback_sources = []

            if not (CAMERA_SOURCE == "usb" and self.camera_acceleration_mode == "hardware"):
                fallback_sources.append(
                    (
                        self._apply_device_profile_to_pipeline(GST_PIPELINE),
                        cv2.CAP_GSTREAMER,
                        "configured GStreamer pipeline",
                    )
                )

            if CAMERA_SOURCE == "usb" and not GST_PIPELINE_IS_OVERRIDE:
                logger.info("USB camera acceleration mode: %s (camera=%s)", self.camera_acceleration_mode, self.camera_id)

                if self.camera_acceleration_mode == "direct":
                    # Direct mode is an explicit "no-GStreamer" safety path.
                    # Keep candidate list minimal and deterministic to avoid
                    # transient v4l2src/GStreamer lockups on /dev/videoN.
                    fallback_sources = []
                    fallback_sources.append(
                        (
                            self.camera_device,
                            None,
                            "V4L2 device (direct)",
                        )
                    )

                    # In single-camera setups, allow alternate /dev/videoN fallback.
                    if len(CAMERA_PROFILES) <= 1:
                        discovered_devices = self._discover_v4l2_devices()
                        for device_path in discovered_devices:
                            if device_path == self.camera_device:
                                continue
                            fallback_sources.append(
                                (
                                    device_path,
                                    None,
                                    f"V4L2 alternate device (direct) {device_path}",
                                )
                            )
                else:
                    if CAMERA_REQUIRE_HARDWARE_ACCEL and not self.hardware_pipeline_eligible:
                        self.last_camera_error = (
                            "Hardware acceleration required but unavailable "
                            f"(opencv_gstreamer_enabled={self.opencv_gstreamer_enabled}, "
                            f"nvjpegdec={self.nvjpegdec_available}, nvvidconv={self.nvvidconv_available})"
                        )
                        logger.error(self.last_camera_error)
                        self.is_open = False
                        return

                    if not self.opencv_gstreamer_enabled:
                        cap = self._open_v4l2_with_preferred_format()
                        if cap is not None:
                            self.cap = cap
                            self.is_open = True
                            self._apply_auto_brightness_controls()
                            logger.info("Camera initialized successfully")
                            return
                        if CAMERA_REQUIRE_HARDWARE_ACCEL:
                            self.last_camera_error = (
                                "Hardware acceleration required, but OpenCV GStreamer backend is disabled"
                            )
                            logger.error(self.last_camera_error)
                            self.is_open = False
                            return

                    usb_candidates = []

                    if self.camera_id == "cam2" and self.prefer_gray8:
                        usb_candidates.append(
                            {
                                "source": CAMERA2_GST_PIPELINE_MJPEG_HW_GRAY8,
                                "backend": cv2.CAP_GSTREAMER,
                                "label": "Cam2 MJPEG hardware pipeline GRAY8 (nvjpegdec)",
                                "format_key": "mjpeg",
                            }
                        )
                        usb_candidates.append(
                            {
                                "source": CAMERA2_GST_PIPELINE_MJPEG_COMPAT_GRAY8,
                                "backend": cv2.CAP_GSTREAMER,
                                "label": "Cam2 MJPEG compatibility pipeline GRAY8",
                                "format_key": "mjpeg",
                            }
                        )

                    # Adaptive compatibility pipelines from detected camera formats are tried first,
                    # because they are validated via gst-inspect + v4l2 mode introspection.
                    # In camera-specific hardware mode, skip adaptive compatibility probing to
                    # reduce startup churn and keep candidate selection deterministic.
                    if self.camera_acceleration_mode != "hardware":
                        adaptive_candidates = self._build_adaptive_usb_candidates()
                        if adaptive_candidates:
                            logger.info(
                                "Detected USB camera modes: mjpeg=%s yuy2=%s",
                                self.detected_usb_modes.get("mjpeg", []),
                                self.detected_usb_modes.get("yuy2", []),
                            )
                            usb_candidates.extend(adaptive_candidates)

                    hardware_candidates_allowed = self.camera_acceleration_mode in ("auto", "hardware") and self.hardware_pipeline_eligible

                    if self.camera_acceleration_mode in ("auto", "hardware") and not self.hardware_pipeline_eligible:
                        logger.warning(
                            "Skipping hardware pipelines (opencv_gstreamer_enabled=%s, nvjpegdec=%s, nvvidconv=%s)",
                            self.opencv_gstreamer_enabled,
                            self.nvjpegdec_available,
                            self.nvvidconv_available,
                        )

                    if hardware_candidates_allowed:
                        if self.usb_hw_mode_lock:
                            locked_candidate = self._build_locked_mjpeg_mode_candidate()
                            if locked_candidate is not None:
                                usb_candidates.append(locked_candidate)
                            else:
                                logger.warning(
                                    "USB HW mode-lock requested but no MJPEG mode detected for %s; falling back to standard HW candidates",
                                    self.camera_device,
                                )

                        if not usb_candidates or not self.usb_hw_mode_lock:
                            usb_candidates.append(
                                {
                                    "source": self._build_usb_pipeline_mjpeg_hw_stable(
                                        int(self.capture_width),
                                        int(self.capture_height),
                                        int(self.capture_fps),
                                    ),
                                    "backend": cv2.CAP_GSTREAMER,
                                    "label": (
                                        "USB hardware pipeline stabilized "
                                        f"({self.capture_width}x{self.capture_height}@{self.capture_fps})"
                                    ),
                                    "format_key": "mjpeg",
                                }
                            )
                            usb_candidates.append(
                                {
                                    "source": self._build_usb_pipeline_mjpeg_hw(
                                        int(self.capture_width),
                                        int(self.capture_height),
                                        int(self.capture_fps),
                                    ),
                                    "backend": cv2.CAP_GSTREAMER,
                                    "label": (
                                        "USB hardware pipeline profile-locked "
                                        f"({self.capture_width}x{self.capture_height}@{self.capture_fps})"
                                    ),
                                    "format_key": "mjpeg",
                                }
                            )
                            usb_candidates.append(
                                {
                                    "source": USB_GST_PIPELINE_HW,
                                    "backend": cv2.CAP_GSTREAMER,
                                    "label": "USB hardware pipeline (nvjpegdec/nvvidconv)",
                                    "format_key": "mjpeg",
                                }
                            )
                            if CAMERA_ALLOW_YUY2_FALLBACK and not self.force_mjpeg:
                                usb_candidates.append(
                                    {
                                        "source": USB_GST_PIPELINE_RAW_HW_UYVY,
                                        "backend": cv2.CAP_GSTREAMER,
                                        "label": "USB raw hardware pipeline UYVY (v4l2src + nvvidconv)",
                                        "format_key": "uyvy",
                                    }
                                )
                                usb_candidates.append(
                                    {
                                        "source": USB_GST_PIPELINE_RAW_HW_YUY2,
                                        "backend": cv2.CAP_GSTREAMER,
                                        "label": "USB raw hardware pipeline YUY2 (v4l2src + nvvidconv)",
                                        "format_key": "yuy2",
                                    }
                                )

                    if self.camera_acceleration_mode in ("auto", "compat") and not CAMERA_REQUIRE_HARDWARE_ACCEL:
                        usb_candidates.append(
                            {
                                "source": USB_GST_PIPELINE_COMPAT,
                                "backend": cv2.CAP_GSTREAMER,
                                "label": "USB compatibility pipeline (jpegdec)",
                                "format_key": "mjpeg",
                            }
                        )
                        if CAMERA_ALLOW_YUY2_FALLBACK and not self.force_mjpeg:
                            usb_candidates.append(
                                {
                                    "source": USB_GST_PIPELINE_COMPAT_RAW,
                                    "backend": cv2.CAP_GSTREAMER,
                                    "label": "USB raw compatibility pipeline (videoconvert)",
                                    "format_key": "any",
                                }
                            )
                            usb_candidates.append(
                                {
                                    "source": USB_GST_PIPELINE_COMPAT_ANY,
                                    "backend": cv2.CAP_GSTREAMER,
                                    "label": "USB permissive compatibility pipeline (no strict caps)",
                                    "format_key": "any",
                                }
                            )

                    usb_candidates = self._reorder_usb_candidates_with_probe(usb_candidates)
                    for candidate in usb_candidates:
                        fallback_sources.append(
                            (
                                self._apply_device_profile_to_pipeline(candidate["source"]),
                                candidate["backend"],
                                candidate["label"],
                            )
                        )

                    if not CAMERA_REQUIRE_HARDWARE_ACCEL:
                        # Last-resort USB fallback: direct V4L2 capture (no GStreamer pipeline string).
                        fallback_sources.append(
                            (
                                self.camera_device,
                                None,
                                "V4L2 device (direct)",
                            )
                        )

                        # Additional fallback for hosts where the active camera is not /dev/video0.
                        # In dual-camera mode, skip alternate-device probing to avoid one logical camera
                        # stealing the other camera's dedicated /dev/videoN node.
                        if len(CAMERA_PROFILES) <= 1:
                            discovered_devices = self._discover_v4l2_devices()
                            for device_path in discovered_devices:
                                if device_path == self.camera_device:
                                    continue
                                fallback_sources.append(
                                    (
                                        device_path,
                                        None,
                                        f"V4L2 alternate device (direct) {device_path}",
                                    )
                                )

            tried_sources = set()
            for source, backend, label in fallback_sources:
                dedupe_key = "{0}|{1}".format(source, backend)
                if dedupe_key in tried_sources:
                    continue
                tried_sources.add(dedupe_key)

                if (
                    CAMERA_SOURCE == "usb"
                    and self.usb_preflight_validate
                    and backend == cv2.CAP_GSTREAMER
                    and isinstance(source, str)
                    and "v4l2src" in source
                ):
                    if not self._gst_preflight_check(source, label):
                        logger.info("Skipping %s due to failing GST preflight", label)
                        continue

                cap = self._open_capture(source, backend, label)
                if cap is not None:
                    self.cap = cap
                    self.is_open = True
                    self._apply_auto_brightness_controls()
                    self._apply_initial_ir_low_light_controls()
                    self.selected_pipeline = label
                    self.selected_pipeline_mode = self._infer_pipeline_mode(label)
                    self.selected_pipeline_source = source
                    self.selected_pipeline_backend = backend
                    logger.info("Camera initialized successfully")
                    return

            if CAMERA_SOURCE == "usb" and not CAMERA_REQUIRE_HARDWARE_ACCEL:
                cap = self._open_v4l2_with_preferred_format()
                if cap is not None:
                    self.cap = cap
                    self.is_open = True
                    self._apply_auto_brightness_controls()
                    self._apply_initial_ir_low_light_controls()
                    self.selected_pipeline = "V4L2 direct preferred format fallback"
                    self.selected_pipeline_mode = "compat"
                    self.selected_pipeline_source = self.camera_device
                    self.selected_pipeline_backend = None
                    logger.info("Camera initialized successfully")
                    return

            logger.error("Failed to initialize camera")
            self.last_camera_error = "Failed to initialize camera from all configured sources"

        except Exception as e:
            logger.error(f"Error initializing camera: {e}")
            self.last_camera_error = str(e)
            self.is_open = False

    def _open_capture(self, source, backend, label):
        """Try to open a capture source and release resources immediately on failure."""
        cap = None
        try:
            # Direct V4L2 fallback handling for /dev/videoN device paths.
            # Some OpenCV builds may treat '/dev/video0' as an image sequence path when backend is unspecified.
            if backend is None and isinstance(source, str) and source.startswith("/dev/video"):
                cap_v4l2 = getattr(cv2, "CAP_V4L2", None)
                if cap_v4l2 is not None:
                    try:
                        cap = cv2.VideoCapture(source, cap_v4l2)
                    except Exception:
                        cap = None
                if cap is None:
                    cap = cv2.VideoCapture(source)

                if cap is None or not cap.isOpened():
                    try:
                        camera_index = int(source.replace("/dev/video", ""))
                    except ValueError:
                        camera_index = None

                    if camera_index is not None:
                        try:
                            if cap is not None:
                                cap.release()
                        except Exception:
                            pass
                        if cap_v4l2 is not None:
                            try:
                                cap = cv2.VideoCapture(camera_index, cap_v4l2)
                            except Exception:
                                cap = None
                        if cap is None:
                            cap = cv2.VideoCapture(camera_index)
            elif backend is None:
                cap = cv2.VideoCapture(source)
            else:
                cap = cv2.VideoCapture(source, backend)

            if cap is not None and cap.isOpened():
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

                if backend is None and isinstance(source, str) and source.startswith("/dev/video"):
                    self._tune_direct_v4l2_capture(cap)

                logger.info("Camera opened using %s", label)
                return cap

            logger.warning("Failed to open camera using %s", label)
            return None
        except Exception as e:
            logger.warning("Error opening camera using %s: %s", label, e)
            return None
        finally:
            if cap is not None and not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass

    def get_frame(self) -> tuple:
        """
        Capture and process a frame from the camera
        
        Returns:
            tuple: (success, frame) where frame is processed BGR image
        """
        with self._frame_lock:
            if not self.is_open or self.cap is None:
                self._attempt_recovery_locked("camera_closed_on_frame_request")
                if not self.is_open or self.cap is None:
                    return False, None

            now = time.perf_counter()
            self._last_client_access_ts = time.time()

            # Share the most recent frame across concurrent consumers to avoid
            # multiplying camera reads when multiple clients are connected.
            if (
                self._last_frame is not None
                and (now - self._last_frame_timestamp) < self.frame_interval_seconds
            ):
                self._frame_cache_hits += 1
                return True, self._last_frame.copy()

            try:
                if self.buffer_flush_grabs > 0:
                    for _ in range(self.buffer_flush_grabs):
                        ok = self.cap.grab()
                        if not ok:
                            break

                ret, frame = self.cap.read()
                read_elapsed_seconds = max(0.0, time.perf_counter() - now)

                if read_elapsed_seconds >= float(self.read_stall_seconds):
                    self._read_stall_count += 1
                    logger.warning(
                        "Slow camera read detected (camera=%s elapsed=%.3fs threshold=%.3fs stall_count=%s)",
                        self.camera_id,
                        read_elapsed_seconds,
                        self.read_stall_seconds,
                        self._read_stall_count,
                    )
                else:
                    self._read_stall_count = 0

                if not ret or frame is None:
                    self._read_failure_count += 1
                    logger.warning(
                        "Failed to read frame from camera (consecutive_failures=%s)",
                        self._read_failure_count,
                    )

                    if self._read_failure_count >= self._max_consecutive_read_failures:
                        logger.warning(
                            "Consecutive camera frame failures reached threshold (%s). Cycling camera.",
                            self._max_consecutive_read_failures,
                        )
                        if self.cap is not None:
                            try:
                                self.cap.release()
                            except Exception:
                                pass
                        self.cap = None
                        self.is_open = False
                        self._last_frame = None
                        self._last_jpeg_bytes = None
                        self._last_jpeg_frame_count = -1
                        self._last_frame_timestamp = 0.0
                        self._attempt_recovery_locked("consecutive_frame_read_failures")

                    return False, None

                if self._read_stall_count >= self.consecutive_stall_limit:
                    logger.warning(
                        "Consecutive slow reads reached threshold (camera=%s threshold=%s). Cycling camera.",
                        self.camera_id,
                        self.consecutive_stall_limit,
                    )
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    self.is_open = False
                    self._last_frame = None
                    self._last_jpeg_bytes = None
                    self._last_jpeg_frame_count = -1
                    self._last_frame_timestamp = 0.0
                    self._attempt_recovery_locked("consecutive_slow_frame_reads")
                    return False, None

                self.frame_count += 1
                self._read_failure_count = 0
                self._read_stall_count = 0
                self._frame_cache_misses += 1

                # Process frame using CUDA if available
                if self.cuda_enabled:
                    try:
                        processed = self._process_with_cuda(frame)
                    except Exception as e:
                        logger.warning(f"CUDA processing failed: {e}, using CPU")
                        self.cuda_enabled = False
                        self.cuda_available = False
                        processed = self._process_with_cpu(frame)
                else:
                    processed = self._process_with_cpu(frame)

                self._maybe_adapt_ir_exposure(processed)

                self._last_frame = processed
                self._last_frame_timestamp = now
                # Invalidate cached JPEG for the new frame.
                self._last_jpeg_frame_count = -1
                self._last_jpeg_bytes = None
                return True, processed.copy()

            except Exception as e:
                logger.error(f"Error getting frame: {e}")
                self.release()
                return False, None

    def get_jpeg_frame(self, quality: int = 80) -> tuple:
        """Get current frame encoded as JPEG with shared cache across clients."""
        success, frame = self.get_frame()
        if not success or frame is None:
            with self._frame_lock:
                # Avoid black screen during short camera hiccups by replaying the
                # most recent encoded frame for a short window.
                if self._last_jpeg_bytes is None:
                    return False, None

                max_stale_age = max(1.2, self.frame_interval_seconds * 8.0)
                stale_age = time.perf_counter() - float(self._last_frame_timestamp or 0.0)
                if stale_age <= max_stale_age:
                    self._jpeg_stale_fallback_hits += 1
                    self._jpeg_cache_hits += 1
                    return True, self._last_jpeg_bytes
            return False, None

        with self._frame_lock:
            current_frame_count = self.frame_count

            if (
                self._last_jpeg_bytes is not None
                and self._last_jpeg_frame_count == current_frame_count
                and self._last_jpeg_quality == int(quality)
            ):
                self._jpeg_cache_hits += 1
                return True, self._last_jpeg_bytes

            source_frame = self._last_frame if self._last_frame is not None else frame
            encode_started = time.perf_counter()
            ok, jpeg = cv2.imencode(".jpg", source_frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
            if not ok:
                return False, None
            encode_elapsed_ms = (time.perf_counter() - encode_started) * 1000.0

            self._last_jpeg_bytes = jpeg.tobytes()
            self._last_jpeg_frame_count = current_frame_count
            self._last_jpeg_quality = int(quality)
            self._jpeg_cache_misses += 1
            self._jpeg_encode_total_ms += encode_elapsed_ms
            self._jpeg_encode_count += 1
            return True, self._last_jpeg_bytes

    def get_cached_frame(self, max_age_seconds: float = 0.35) -> tuple:
        """Return the latest cached frame if it's fresh enough, without reading camera again."""
        with self._frame_lock:
            if self._last_frame is None:
                return False, None

            age_seconds = time.perf_counter() - float(self._last_frame_timestamp or 0.0)
            if age_seconds > float(max(0.01, max_age_seconds)):
                return False, None

            self._last_client_access_ts = time.time()
            self._frame_cache_hits += 1
            return True, self._last_frame.copy()

    def get_performance_stats(self) -> dict:
        """Return camera cache/encoding performance counters."""
        with self._frame_lock:
            frame_total = self._frame_cache_hits + self._frame_cache_misses
            jpeg_total = self._jpeg_cache_hits + self._jpeg_cache_misses

            frame_hit_ratio = (
                float(self._frame_cache_hits) / float(frame_total) if frame_total > 0 else 0.0
            )
            jpeg_hit_ratio = (
                float(self._jpeg_cache_hits) / float(jpeg_total) if jpeg_total > 0 else 0.0
            )
            avg_jpeg_encode_ms = (
                float(self._jpeg_encode_total_ms) / float(self._jpeg_encode_count)
                if self._jpeg_encode_count > 0
                else 0.0
            )

            return {
                "frame_cache": {
                    "hits": self._frame_cache_hits,
                    "misses": self._frame_cache_misses,
                    "hit_ratio": frame_hit_ratio,
                },
                "jpeg_cache": {
                    "hits": self._jpeg_cache_hits,
                    "misses": self._jpeg_cache_misses,
                    "hit_ratio": jpeg_hit_ratio,
                    "stale_fallback_hits": self._jpeg_stale_fallback_hits,
                },
                "jpeg_encode": {
                    "count": self._jpeg_encode_count,
                    "avg_ms": avg_jpeg_encode_ms,
                },
                "last_client_access_ts": self._last_client_access_ts,
                "target_fps": self.target_fps,
            }

    def maybe_release_if_idle(self, idle_seconds: int, active_mjpeg_clients: int = 0, webrtc_connections: int = 0) -> bool:
        """Release camera when idle and no active viewers."""
        with self._frame_lock:
            if not self.is_open or self.cap is None:
                return False

            if active_mjpeg_clients > 0 or webrtc_connections > 0:
                return False

            idle_for = time.time() - float(self._last_client_access_ts)
            if idle_for < float(idle_seconds):
                return False

            try:
                self.cap.release()
            except Exception:
                pass

            self.cap = None
            self.is_open = False
            self._last_frame = None
            self._last_jpeg_bytes = None
            self._last_jpeg_frame_count = -1
            self._last_frame_timestamp = 0.0
            logger.info(
                "Camera auto-released after %.2fs idle (mjpeg=%s, webrtc=%s)",
                idle_for,
                active_mjpeg_clients,
                webrtc_connections,
            )
            return True

    def _process_with_cuda(self, frame) -> np.ndarray:
        """
        Process frame using CUDA acceleration
        
        Args:
            frame: Input frame from camera
            
        Returns:
            np.ndarray: Processed frame
        """
        try:
            if self._cuda_gpmat_ctor is None:
                raise RuntimeError("OpenCV CUDA GpuMat constructor unavailable")

            # Upload frame to GPU
            gpu_frame = self._cuda_gpmat_ctor()
            gpu_frame.upload(frame)

            # Resize using CUDA
            gpu_resized = cv2.cuda.resize(gpu_frame, PROCESSING_SCALE)

            # Download back to CPU
            processed = gpu_resized.download()

            return processed
        except Exception as e:
            logger.warning(f"CUDA processing error: {e}")
            # Fallback to CPU resize and disable further CUDA attempts for this runtime.
            self.cuda_enabled = False
            self.cuda_available = False
            return self._process_with_cpu(frame)

    def _process_with_cpu(self, frame) -> np.ndarray:
        """CPU frame processing fallback path."""
        return cv2.resize(frame, PROCESSING_SCALE)

    def get_frame_count(self) -> int:
        """Get total frames captured"""
        return self.frame_count

    def release(self):
        """Release camera resources"""
        try:
            if not hasattr(self, "_frame_lock"):
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
                self.is_open = False
                return

            with self._frame_lock:
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
                self.is_open = False
                self._last_frame = None
                self._last_jpeg_bytes = None
                self._last_jpeg_frame_count = -1
                self._last_frame_timestamp = 0.0
                logger.info("Camera released")
        except Exception as e:
            logger.error(f"Error releasing camera: {e}")

    def get_runtime_diagnostics(self) -> dict:
        """Get runtime camera diagnostics including selected pipeline details."""
        source_preview = self.selected_pipeline_source
        if isinstance(source_preview, str) and len(source_preview) > 220:
            source_preview = source_preview[:220] + "..."

        return {
            "camera_id": self.camera_id,
            "camera_device": self.camera_device,
            "capture_profile": {
                "width": self.capture_width,
                "height": self.capture_height,
                "fps": self.capture_fps,
                "jpeg_quality": self.jpeg_quality,
            },
            "selected_pipeline": self.selected_pipeline,
            "selected_pipeline_mode": self.selected_pipeline_mode,
            "selected_pipeline_backend": self.selected_pipeline_backend,
            "selected_pipeline_source": source_preview,
            "hardware_accel": {
                "required": CAMERA_REQUIRE_HARDWARE_ACCEL,
                "opencv_gstreamer_enabled": self.opencv_gstreamer_enabled,
                "nvjpegdec_available": self.nvjpegdec_available,
                "nvvidconv_available": self.nvvidconv_available,
                "hardware_pipeline_eligible": self.hardware_pipeline_eligible,
            },
            "detected_usb_modes": self.detected_usb_modes,
            "startup_probe_enabled": self.startup_probe_enabled,
            "usb_preflight_validate": self.usb_preflight_validate,
            "usb_hw_mode_lock": self.usb_hw_mode_lock,
            "usb_v4l2_io_mode": self.usb_v4l2_io_mode,
            "preflight_results": self.preflight_results,
            "startup_probe_formats": self.startup_probe_formats,
            "startup_probe_scores": self.startup_probe_scores,
            "startup_probe_order": self.startup_probe_order,
            "last_camera_error": self.last_camera_error,
            "recovery": {
                "attempts": self._recovery_attempt_count,
                "successes": self._recovery_success_count,
                "failures": self._recovery_failed_count,
                "consecutive_failures": self._consecutive_recovery_failures,
                "consecutive_read_failures": self._read_failure_count,
                "max_consecutive_read_failures": self._max_consecutive_read_failures,
                "consecutive_read_stalls": self._read_stall_count,
                "read_stall_threshold_seconds": self.read_stall_seconds,
                "consecutive_stall_limit": self.consecutive_stall_limit,
                "next_recovery_allowed_in_seconds": max(0.0, self._next_recovery_allowed_ts - time.time())
                if self._next_recovery_allowed_ts
                else 0.0,
                "last_recovery_ts": self._last_recovery_ts,
                "last_recovery_reason": self._last_recovery_reason,
            },
            "performance": self.get_performance_stats(),
            "ir_low_light": {
                "adaptive_enabled": self._adaptive_exposure_enabled,
                "last_luma_mean": self._last_luma_mean,
                "exposure_absolute": self._current_exposure_absolute,
                "gain": self._current_gain,
                "next_adjust_in_seconds": max(0.0, self._next_exposure_adjust_ts - time.time()),
                "force_mjpeg": self.force_mjpeg,
                "prefer_gray8": self.prefer_gray8,
                "auto_brightness_enabled": self.auto_brightness_enabled,
            },
        }

    def __del__(self):
        """Cleanup on deletion"""
        self.release()


# Global camera instances
cameras = {}


def get_camera_profile(camera_id: str) -> dict:
    camera_key = (camera_id or CAMERA_DEFAULT_ID or "cam1").lower()
    if camera_key in CAMERA_PROFILES:
        profile = dict(CAMERA_PROFILES[camera_key])
        if camera_key == "cam2":
            profile["device"] = _resolve_camera2_device_from_hint(str(profile.get("device") or CAMERA_DEVICE))
        return profile
    return CAMERA_PROFILES.get("cam1", {"device": CAMERA_DEVICE, "width": CAMERA_WIDTH, "height": CAMERA_HEIGHT, "fps": CAMERA_FPS})


def get_camera(camera_id: str = None, create_if_missing: bool = True) -> CameraCapture:
    """Get or create a camera instance by logical camera id."""
    global cameras
    camera_key = (camera_id or CAMERA_DEFAULT_ID or "cam1").lower()
    if camera_key not in cameras or cameras[camera_key] is None:
        if not create_if_missing:
            return None
        cameras[camera_key] = CameraCapture(camera_id=camera_key, profile=get_camera_profile(camera_key))
    return cameras[camera_key]


def get_existing_camera(camera_id: str = None):
    """Return camera instance only if already initialized; never creates one."""
    return get_camera(camera_id=camera_id, create_if_missing=False)


def get_camera_ids() -> list:
    """Return configured logical camera ids."""
    return sorted(CAMERA_PROFILES.keys())


def release_camera(camera_id: str):
    """Release and remove a camera instance from registry."""
    global cameras
    camera_key = (camera_id or CAMERA_DEFAULT_ID or "cam1").lower()
    cam = cameras.get(camera_key)
    if cam is not None:
        cam.release()
    cameras[camera_key] = None


def release_all_cameras():
    """Release all instantiated cameras."""
    global cameras
    for camera_id in list(cameras.keys()):
        try:
            cam = cameras.get(camera_id)
            if cam is not None:
                cam.release()
        except Exception:
            pass
        cameras[camera_id] = None


def probe_camera_devices_gstreamer() -> dict:
    """Probe /dev/video* nodes and include GStreamer-visible capabilities."""
    devices = sorted(glob.glob("/dev/video*"))
    profiles = {
        camera_id: {
            "device": profile.get("device"),
            "width": int(profile.get("width") or CAMERA_WIDTH),
            "height": int(profile.get("height") or CAMERA_HEIGHT),
            "fps": int(profile.get("fps") or CAMERA_FPS),
        }
        for camera_id, profile in CAMERA_PROFILES.items()
    }

    gst_monitor_output = ""
    gst_available = False

    try:
        gst_check = subprocess.run(
            ["gst-inspect-1.0", "v4l2src"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=2,
            check=False,
        )
        gst_available = gst_check.returncode == 0
    except Exception:
        gst_available = False

    if gst_available:
        try:
            monitor = subprocess.run(
                ["gst-device-monitor-1.0", "Video/Source"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=3,
                check=False,
            )
            if monitor.returncode == 0:
                gst_monitor_output = (monitor.stdout or "")
        except Exception:
            gst_monitor_output = ""

    per_device_formats = {}
    for dev in devices:
        per_device_formats[dev] = {"gstreamer_caps": [], "v4l2_modes": {"mjpeg": [], "yuy2": []}}

        if gst_monitor_output:
            try:
                for line in gst_monitor_output.splitlines():
                    if dev in line:
                        per_device_formats[dev]["gstreamer_caps"].append(line.strip())
            except Exception:
                pass

        try:
            ctl = subprocess.run(
                ["v4l2-ctl", "--device", dev, "--list-formats-ext"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=3,
                check=False,
            )
            if ctl.returncode == 0:
                current_format = None
                current_size = None
                for raw_line in (ctl.stdout or "").splitlines():
                    line = raw_line.strip()
                    lower = line.lower()
                    if "pixel format" in lower:
                        if "mjpg" in lower or "mjpeg" in lower:
                            current_format = "mjpeg"
                        elif "yuyv" in lower or "yuy2" in lower:
                            current_format = "yuy2"
                        else:
                            current_format = None
                        current_size = None
                        continue

                    size_match = re.search(r"Size:\s*Discrete\s*(\d+)x(\d+)", line)
                    if size_match:
                        current_size = (int(size_match.group(1)), int(size_match.group(2)))
                        continue

                    fps_match = re.search(r"\((\d+(?:\.\d+)?)\s*fps\)", line)
                    if fps_match and current_format and current_size:
                        fps = int(float(fps_match.group(1)))
                        per_device_formats[dev]["v4l2_modes"][current_format].append(
                            [current_size[0], current_size[1], fps]
                        )
        except Exception:
            pass

    mapping = {}
    for cam_id, profile in profiles.items():
        mapped_device = profile.get("device")
        mapping[cam_id] = {
            "configured_device": mapped_device,
            "present": mapped_device in devices,
            "formats": per_device_formats.get(mapped_device, {}),
        }

    return {
        "configured_profiles": profiles,
        "discovered_video_devices": devices,
        "gstreamer_available": gst_available,
        "camera_mapping": mapping,
        "all_device_formats": per_device_formats,
    }


def check_cuda_availability() -> dict:
    """Check CUDA availability on the system"""
    has_cv2_cuda = hasattr(cv2, "cuda")
    has_gpmat = hasattr(cv2, "cuda_GpuMat") or (
        has_cv2_cuda and hasattr(cv2.cuda, "GpuMat")
    )

    try:
        if not has_cv2_cuda:
            return {
                "cuda_available": False,
                "cuda_device_count": 0,
                "cv2_cuda_module": False,
                "cv2_cuda_gpmat": has_gpmat,
                "reason": "cv2.cuda module missing"
            }

        count = int(cv2.cuda.getCudaEnabledDeviceCount())
        cuda_enabled = count > 0

        reason = None
        if not has_gpmat:
            reason = "cv2.cuda GpuMat constructor missing"
        elif not cuda_enabled:
            reason = "OpenCV CUDA device count is 0"

        return {
            "cuda_available": cuda_enabled,
            "cuda_device_count": count,
            "cv2_cuda_module": has_cv2_cuda,
            "cv2_cuda_gpmat": has_gpmat,
            "reason": reason
        }
    except Exception as e:
        logger.warning(f"Failed to check CUDA: {e}")
        return {
            "cuda_available": False,
            "cuda_device_count": 0,
            "cv2_cuda_module": has_cv2_cuda,
            "cv2_cuda_gpmat": has_gpmat,
            "reason": str(e)
        }

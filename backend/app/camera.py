"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import re
import subprocess
import time
import threading
import glob
import cv2
import numpy as np
from .config import (
    CAMERA_ACCELERATION,
    CAMERA_DEVICE,
    CAMERA_DEFAULT_ID,
    CAMERA_BUFFER_FLUSH_GRABS,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA2_DEVICE_HINT,
    CAMERA_PROFILES,
    CAMERA_SOURCE,
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
)

logger = logging.getLogger(__name__)


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
        self.buffer_flush_grabs = max(0, int(CAMERA_BUFFER_FLUSH_GRABS))
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
        self.startup_probe_formats = {}
        self.startup_probe_scores = {}
        self.startup_probe_order = []
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
        self._jpeg_encode_total_ms = 0.0
        self._jpeg_encode_count = 0
        self._read_failure_count = 0
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
        self.opencv_gstreamer_enabled = self._check_opencv_gstreamer_support()
        self._detect_cuda_capability()
        self._initialize_camera()

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
        """Detect whether OpenCV build has GStreamer backend enabled."""
        try:
            info = cv2.getBuildInformation()
            enabled = "gstreamer: yes" in info.lower()
            if not enabled:
                logger.warning(
                    "OpenCV build reports GStreamer backend disabled; USB capture will use V4L2 fallback"
                )
            return enabled
        except Exception as e:
            logger.warning("Unable to read OpenCV build info (%s); assuming no GStreamer", e)
            return False

    def _build_usb_pipeline_mjpeg_compat(self, width: int, height: int, fps: int) -> str:
        """Build a software-compatible MJPEG pipeline known to work with OpenCV appsink."""
        return (
            f"v4l2src device={self.camera_device} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "jpegdec ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! "
            "appsink drop=1 max-buffers=1 sync=false"
        )

    def _build_usb_pipeline_yuy2_compat(self, width: int, height: int, fps: int) -> str:
        """Build a software-compatible YUY2 pipeline known to work with OpenCV appsink."""
        return (
            f"v4l2src device={self.camera_device} ! "
            f"video/x-raw,format=YUY2,width={width},height={height},framerate={fps}/1 ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! "
            "appsink drop=1 max-buffers=1 sync=false"
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

        if yuy2_mode:
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
        if yuy2_mode:
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
        if not CAMERA_USB_STARTUP_PROBE or not candidates:
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

            fallback_sources = [
                (
                    self._apply_device_profile_to_pipeline(GST_PIPELINE),
                    cv2.CAP_GSTREAMER,
                    "configured GStreamer pipeline",
                ),
            ]

            if CAMERA_SOURCE == "usb" and not GST_PIPELINE_IS_OVERRIDE:
                logger.info("USB camera acceleration mode: %s", CAMERA_ACCELERATION)

                if not self.opencv_gstreamer_enabled:
                    cap = self._open_v4l2_with_preferred_format()
                    if cap is not None:
                        self.cap = cap
                        self.is_open = True
                        logger.info("Camera initialized successfully")
                        return

                usb_candidates = []

                # Adaptive compatibility pipelines from detected camera formats are tried first,
                # because they are validated via gst-inspect + v4l2 mode introspection.
                adaptive_candidates = self._build_adaptive_usb_candidates()
                if adaptive_candidates:
                    logger.info(
                        "Detected USB camera modes: mjpeg=%s yuy2=%s",
                        self.detected_usb_modes.get("mjpeg", []),
                        self.detected_usb_modes.get("yuy2", []),
                    )
                    usb_candidates.extend(adaptive_candidates)

                if CAMERA_ACCELERATION in ("auto", "hardware"):
                    usb_candidates.append(
                        {
                            "source": USB_GST_PIPELINE_HW,
                            "backend": cv2.CAP_GSTREAMER,
                            "label": "USB hardware pipeline (nvjpegdec/nvvidconv)",
                            "format_key": "mjpeg",
                        }
                    )
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

                if CAMERA_ACCELERATION in ("auto", "compat"):
                    usb_candidates.append(
                        {
                            "source": USB_GST_PIPELINE_COMPAT,
                            "backend": cv2.CAP_GSTREAMER,
                            "label": "USB compatibility pipeline (jpegdec)",
                            "format_key": "mjpeg",
                        }
                    )
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

                # Last-resort USB fallback: direct V4L2 capture (no GStreamer pipeline string).
                fallback_sources.append(
                    (
                        self.camera_device,
                        None,
                        "V4L2 device (direct)",
                    )
                )

                # Additional fallback for hosts where the active camera is not /dev/video0.
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

                cap = self._open_capture(source, backend, label)
                if cap is not None:
                    self.cap = cap
                    self.is_open = True
                    self.selected_pipeline = label
                    self.selected_pipeline_mode = self._infer_pipeline_mode(label)
                    self.selected_pipeline_source = source
                    self.selected_pipeline_backend = backend
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

                self.frame_count += 1
                self._read_failure_count = 0
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
            },
            "selected_pipeline": self.selected_pipeline,
            "selected_pipeline_mode": self.selected_pipeline_mode,
            "selected_pipeline_backend": self.selected_pipeline_backend,
            "selected_pipeline_source": source_preview,
            "detected_usb_modes": self.detected_usb_modes,
            "startup_probe_enabled": self.startup_probe_enabled,
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
                "next_recovery_allowed_in_seconds": max(0.0, self._next_recovery_allowed_ts - time.time())
                if self._next_recovery_allowed_ts
                else 0.0,
                "last_recovery_ts": self._last_recovery_ts,
                "last_recovery_reason": self._last_recovery_reason,
            },
            "performance": self.get_performance_stats(),
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


def get_camera(camera_id: str = None) -> CameraCapture:
    """Get or create a camera instance by logical camera id."""
    global cameras
    camera_key = (camera_id or CAMERA_DEFAULT_ID or "cam1").lower()
    if camera_key not in cameras or cameras[camera_key] is None:
        cameras[camera_key] = CameraCapture(camera_id=camera_key, profile=get_camera_profile(camera_key))
    return cameras[camera_key]


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

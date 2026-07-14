"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import re
import subprocess
import time
import threading
import cv2
import numpy as np
from .config import (
    CAMERA_ACCELERATION,
    CAMERA_DEVICE,
    CAMERA_FPS,
    CAMERA_SOURCE,
    CAMERA_USB_STARTUP_PROBE,
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


class CameraCapture:
    """Capture video from camera using GStreamer and OpenCV"""

    def __init__(self):
        self.cap = None
        self.is_open = False
        self.frame_count = 0
        self.target_fps = max(1, int(CAMERA_FPS))
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
        self.opencv_gstreamer_enabled = self._check_opencv_gstreamer_support()
        self._detect_cuda_capability()
        self._initialize_camera()

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
            f"v4l2src device={CAMERA_DEVICE} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            "jpegdec ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! "
            "appsink drop=1 max-buffers=1 sync=false"
        )

    def _build_usb_pipeline_yuy2_compat(self, width: int, height: int, fps: int) -> str:
        """Build a software-compatible YUY2 pipeline known to work with OpenCV appsink."""
        return (
            f"v4l2src device={CAMERA_DEVICE} ! "
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
                ["v4l2-ctl", "--device", CAMERA_DEVICE, "--list-formats-ext"],
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
            if isinstance(CAMERA_DEVICE, str) and CAMERA_DEVICE.startswith("/dev/video"):
                camera_index = int(CAMERA_DEVICE.replace("/dev/video", ""))
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
                    self.selected_pipeline_source = CAMERA_DEVICE
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
                ["v4l2-ctl", "--device", CAMERA_DEVICE, "--list-formats-ext"],
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

    def _initialize_camera(self):
        """Initialize camera capture"""
        try:
            self.last_camera_error = None
            self.startup_probe_scores = {}
            self.startup_probe_order = []

            fallback_sources = [
                (GST_PIPELINE, cv2.CAP_GSTREAMER, "configured GStreamer pipeline"),
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
                            candidate["source"],
                            candidate["backend"],
                            candidate["label"],
                        )
                    )

                # Last-resort USB fallback: direct V4L2 capture (no GStreamer pipeline string).
                fallback_sources.append(
                    (
                        CAMERA_DEVICE,
                        None,
                        "V4L2 device (direct)",
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
        if not self.is_open or self.cap is None:
            return False, None

        with self._frame_lock:
            now = time.perf_counter()

            # Share the most recent frame across concurrent consumers to avoid
            # multiplying camera reads when multiple clients are connected.
            if (
                self._last_frame is not None
                and (now - self._last_frame_timestamp) < self.frame_interval_seconds
            ):
                return True, self._last_frame.copy()

            try:
                ret, frame = self.cap.read()

                if not ret or frame is None:
                    logger.warning("Failed to read frame from camera")
                    self.release()
                    return False, None

                self.frame_count += 1

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
                return True, self._last_jpeg_bytes

            source_frame = self._last_frame if self._last_frame is not None else frame
            ok, jpeg = cv2.imencode(".jpg", source_frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
            if not ok:
                return False, None

            self._last_jpeg_bytes = jpeg.tobytes()
            self._last_jpeg_frame_count = current_frame_count
            self._last_jpeg_quality = int(quality)
            return True, self._last_jpeg_bytes

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
        }

    def __del__(self):
        """Cleanup on deletion"""
        self.release()


# Global camera instance
camera = None


def get_camera() -> CameraCapture:
    """Get or create camera instance"""
    global camera
    if camera is None:
        camera = CameraCapture()
    return camera


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

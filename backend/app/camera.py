"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import subprocess
import time
import cv2
import numpy as np
from .config import (
    CAMERA_ACCELERATION,
    CAMERA_DEVICE,
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
    PROCESSING_SCALE,
)

logger = logging.getLogger(__name__)


class CameraCapture:
    """Capture video from camera using GStreamer and OpenCV"""

    def __init__(self):
        self.cap = None
        self.is_open = False
        self.frame_count = 0
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
        self._detect_cuda_capability()
        self._initialize_camera()

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
                capture_output=True,
                text=True,
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

                usb_candidates = []

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

                usb_candidates = self._reorder_usb_candidates_with_probe(usb_candidates)
                for candidate in usb_candidates:
                    fallback_sources.append(
                        (
                            candidate["source"],
                            candidate["backend"],
                            candidate["label"],
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
            if backend is None:
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

        try:
            ret, frame = self.cap.read()

            if not ret or frame is None:
                logger.warning("Failed to read frame from camera")
                return False, None

            self.frame_count += 1

            # Process frame using CUDA if available
            if self.cuda_enabled:
                try:
                    processed = self._process_with_cuda(frame)
                    return True, processed
                except Exception as e:
                    logger.warning(f"CUDA processing failed: {e}, using CPU")
                    self.cuda_enabled = False
                    self.cuda_available = False
                    return True, self._process_with_cpu(frame)
            else:
                return True, self._process_with_cpu(frame)

        except Exception as e:
            logger.error(f"Error getting frame: {e}")
            return False, None

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
            if self.cap is not None:
                self.cap.release()
                self.is_open = False
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

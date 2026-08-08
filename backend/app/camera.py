"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import cv2
import numpy as np
import time
from .config import (
    GST_PIPELINE,
    CUDA_ENABLED,
    PROCESSING_SCALE,
    CAMERA_DEVICE,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
    CAMERA_FPS,
    CAMERA_DEFAULT_ID,
    CAMERA_PROFILES,
)

logger = logging.getLogger(__name__)


class CameraCapture:
    """Capture video from camera using GStreamer and OpenCV"""

    def __init__(self, camera_id: str = None):
        self.camera_id = _normalize_camera_id(camera_id)
        profile = CAMERA_PROFILES.get(self.camera_id, {})
        self.camera_device = str(profile.get("device") or CAMERA_DEVICE)
        self.camera_width = int(profile.get("width") or CAMERA_WIDTH)
        self.camera_height = int(profile.get("height") or CAMERA_HEIGHT)
        self.camera_fps = int(profile.get("fps") or CAMERA_FPS)
        self.cap = None
        self.is_open = False
        self.frame_count = 0
        self.opened_at_ts = time.time()
        self.last_frame_ts = 0.0
        self.last_success_ts = 0.0
        self.last_error = None
        self._last_frame = None
        self.selected_pipeline = None
        self.selected_pipeline_mode = None
        self.cuda_enabled = False
        self.cuda_available = False
        self.cuda_device_count = 0
        self._cuda_gpmat_ctor = None
        self._detect_cuda_capability()
        self._initialize_camera()

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
            # Log a brief hint from build information to help debugging
            try:
                info = cv2.getBuildInformation()
                # find first line mentioning CUDA or cuDNN
                cuda_hint = next((l for l in info.splitlines() if "CUDA" in l or "cuDNN" in l), None)
                logger.debug("OpenCV build information (CUDA hint): %s", cuda_hint)
            except Exception:
                logger.debug("Failed to obtain OpenCV build information for CUDA diagnostics")
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

    def _initialize_camera(self):
        """Initialize camera capture"""
        try:
            fallback_sources = [
                (self.camera_device, None, "V4L2 device (direct)"),
                (self._build_usb_raw_pipeline(), cv2.CAP_GSTREAMER, "USB raw GStreamer pipeline"),
            ]

            # Keep legacy configured pipeline as a late fallback for cam1/default path.
            if self.camera_id == _normalize_camera_id(CAMERA_DEFAULT_ID):
                fallback_sources.append((GST_PIPELINE, cv2.CAP_GSTREAMER, "configured GStreamer pipeline"))

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
                    self.selected_pipeline = str(source)
                    self.selected_pipeline_mode = label
                    logger.info(
                        "Camera initialized successfully: id=%s device=%s",
                        self.camera_id,
                        self.camera_device,
                    )
                    return

            logger.error("Failed to initialize camera: id=%s device=%s", self.camera_id, self.camera_device)
            self.last_error = "camera_init_failed"

        except Exception as e:
            logger.error(f"Error initializing camera: {e}")
            self.is_open = False
            self.last_error = str(e)

    def _build_usb_raw_pipeline(self) -> str:
        """Build a tolerant USB camera GStreamer pipeline (non-MJPEG-specific)."""
        return (
            "v4l2src device={device} ! "
            "video/x-raw,width={width},height={height},framerate={fps}/1 ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! "
            "appsink drop=1 max-buffers=1 sync=false"
        ).format(
            device=self.camera_device,
            width=self.camera_width,
            height=self.camera_height,
            fps=self.camera_fps,
        )

    def _open_capture(self, source, backend, label):
        """Try to open a capture source and release resources immediately on failure."""
        cap = None
        try:
            if backend is None:
                cap = cv2.VideoCapture(source)
            else:
                cap = cv2.VideoCapture(source, backend)

            if cap is not None and cap.isOpened():
                # Validate that a frame can actually be read (some backends report opened
                # before returning frames). Try a few short retries.
                for attempt in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        logger.info("Camera opened and frame read using %s (attempt %d)", label, attempt + 1)
                        # rewind is not possible for live capture; keep cap open
                        return cap
                    logger.debug("No frame yet from %s (attempt %d), retrying...", label, attempt + 1)
                    time.sleep(0.2)
                logger.warning("Camera opened but no frames read using %s", label)
                try:
                    cap.release()
                except Exception:
                    pass
                return None

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
                self.last_error = "frame_read_failed"
                return False, None

            self.frame_count += 1
            self.last_frame_ts = time.time()
            self.last_success_ts = self.last_frame_ts
            self._last_frame = frame

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
            self.last_error = str(e)
            return False, None

    def get_cached_frame(self, max_age_seconds: float = 0.5) -> tuple:
        """Return a recent frame if available, otherwise capture a fresh frame."""
        now_ts = time.time()
        if self._last_frame is not None and (now_ts - self.last_frame_ts) <= float(max_age_seconds):
            return True, self._last_frame.copy()
        return self.get_frame()

    def get_jpeg_frame(self, quality: int = 80) -> tuple:
        """Capture frame and return JPEG bytes for HTTP streaming."""
        success, frame = self.get_cached_frame(max_age_seconds=0.25)
        if not success or frame is None:
            return False, None

        try:
            q = max(20, min(95, int(quality)))
            ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not ok or encoded is None:
                self.last_error = "jpeg_encode_failed"
                return False, None
            return True, encoded.tobytes()
        except Exception as e:
            self.last_error = str(e)
            return False, None

    def maybe_release_if_idle(self, idle_seconds: int = 6, active_mjpeg_clients: int = 0, webrtc_connections: int = 0) -> bool:
        """Release camera when idle and there are no active viewers."""
        if not self.is_open or self.cap is None:
            return False

        if int(active_mjpeg_clients) > 0 or int(webrtc_connections) > 0:
            return False

        now_ts = time.time()
        last_activity_ts = self.last_frame_ts or self.last_success_ts or self.opened_at_ts
        if (now_ts - float(last_activity_ts)) < float(idle_seconds):
            return False

        logger.info("Releasing idle camera after %.2fs without viewers", now_ts - float(last_activity_ts))
        self.release()
        return True

    def get_runtime_diagnostics(self) -> dict:
        """Return runtime diagnostics used by API responses."""
        return {
            "selected_pipeline": self.selected_pipeline,
            "selected_pipeline_source": self.selected_pipeline,
            "selected_pipeline_mode": self.selected_pipeline_mode,
            "is_open": bool(self.is_open),
            "frame_count": int(self.frame_count),
            "last_frame_ts": float(self.last_frame_ts),
            "last_error": self.last_error,
            "recovery": {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "consecutive_failures": 0,
                "next_recovery_allowed_in_seconds": 0.0,
                "last_recovery_reason": None,
            },
        }

    def get_performance_stats(self) -> dict:
        """Return lightweight camera performance metrics."""
        uptime_seconds = max(0.001, time.time() - float(self.opened_at_ts))
        approx_fps = float(self.frame_count) / uptime_seconds
        return {
            "uptime_seconds": round(uptime_seconds, 3),
            "frame_count": int(self.frame_count),
            "approx_fps": round(approx_fps, 2),
            "cuda_enabled": bool(self.cuda_enabled),
            "is_open": bool(self.is_open),
        }

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
                self.selected_pipeline = None
                self.selected_pipeline_mode = None
                logger.info("Camera released")
        except Exception as e:
            logger.error(f"Error releasing camera: {e}")

    def __del__(self):
        """Cleanup on deletion"""
        self.release()


# Global camera instance
camera = None
camera_registry = {}


def _normalize_camera_id(camera_id: str = None) -> str:
    candidate = str(camera_id or CAMERA_DEFAULT_ID or "cam1").strip().lower()
    if candidate in CAMERA_PROFILES:
        return candidate
    if CAMERA_PROFILES:
        return list(CAMERA_PROFILES.keys())[0]
    return "cam1"


def get_camera(camera_id: str = None, create_if_missing: bool = True) -> CameraCapture:
    """Get or create camera instance by camera ID.

    This compatibility layer keeps legacy single-camera behavior while exposing
    the multi-camera function signature used by the API layer.
    """
    global camera
    normalized_id = _normalize_camera_id(camera_id)
    existing = camera_registry.get(normalized_id)
    if existing is not None:
        return existing

    if not create_if_missing:
        return None

    cam = CameraCapture(normalized_id)
    camera_registry[normalized_id] = cam
    if normalized_id == _normalize_camera_id(CAMERA_DEFAULT_ID):
        camera = cam
    return cam


def get_existing_camera(camera_id: str = None) -> CameraCapture:
    """Compatibility helper: return camera instance only if already created."""
    normalized_id = _normalize_camera_id(camera_id)
    return camera_registry.get(normalized_id)


def get_camera_ids() -> list:
    """Return enabled camera IDs from configuration."""
    if CAMERA_PROFILES:
        return list(CAMERA_PROFILES.keys())
    return [_normalize_camera_id(CAMERA_DEFAULT_ID)]


def release_camera(camera_id: str = None) -> None:
    """Release one camera instance by ID."""
    global camera
    normalized_id = _normalize_camera_id(camera_id)
    cam = camera_registry.pop(normalized_id, None)
    if cam is not None:
        try:
            cam.release()
        except Exception:
            pass

    if normalized_id == _normalize_camera_id(CAMERA_DEFAULT_ID):
        camera = None


def release_all_cameras() -> None:
    """Release all camera instances."""
    global camera
    for cam in list(camera_registry.values()):
        try:
            cam.release()
        except Exception:
            pass
    camera_registry.clear()
    camera = None


def try_rebind_camera(camera_id: str = None, reason: str = "manual") -> CameraCapture:
    """Best-effort camera rebind helper."""
    normalized_id = _normalize_camera_id(camera_id)
    logger.warning("Rebinding camera %s reason=%s", normalized_id, reason)
    release_camera(normalized_id)
    return get_camera(normalized_id, create_if_missing=True)


def probe_camera_devices_gstreamer() -> dict:
    """Return lightweight probe information for API diagnostics."""
    return {
        "gstreamer_probe": {
            "pipeline": GST_PIPELINE,
            "camera_device": CAMERA_DEVICE,
            "camera_ids": get_camera_ids(),
        }
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

"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import cv2
import numpy as np
from .config import (
    GST_PIPELINE,
    CUDA_ENABLED,
    PROCESSING_SCALE,
    CAMERA_DEVICE,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
    CAMERA_FPS,
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
                (GST_PIPELINE, cv2.CAP_GSTREAMER, "configured GStreamer pipeline"),
                (self._build_usb_raw_pipeline(), cv2.CAP_GSTREAMER, "USB raw GStreamer pipeline"),
            ]

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
                    logger.info("Camera initialized successfully")
                    return

            logger.error("Failed to initialize camera")

        except Exception as e:
            logger.error(f"Error initializing camera: {e}")
            self.is_open = False

    def _build_usb_raw_pipeline(self) -> str:
        """Build a tolerant USB camera GStreamer pipeline (non-MJPEG-specific)."""
        return (
            "v4l2src device={device} ! "
            "video/x-raw,width={width},height={height},framerate={fps}/1 ! "
            "videoconvert ! "
            "video/x-raw, format=BGR ! "
            "appsink drop=1 max-buffers=1 sync=false"
        ).format(
            device=CAMERA_DEVICE,
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fps=CAMERA_FPS,
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

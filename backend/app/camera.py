"""Camera capture using GStreamer and OpenCV CUDA"""

import logging
import cv2
import numpy as np
from .config import GST_PIPELINE, CUDA_ENABLED, PROCESSING_SCALE

logger = logging.getLogger(__name__)


class CameraCapture:
    """Capture video from camera using GStreamer and OpenCV"""

    def __init__(self):
        self.cap = None
        self.is_open = False
        self.frame_count = 0
        self.cuda_enabled = CUDA_ENABLED
        self._initialize_camera()

    def _initialize_camera(self):
        """Initialize camera capture"""
        try:
            self.cap = cv2.VideoCapture(GST_PIPELINE, cv2.CAP_GSTREAMER)
            
            if not self.cap.isOpened():
                logger.error("Failed to open camera with GStreamer")
                # Fallback to default camera
                self.cap = cv2.VideoCapture(0)
                
            if self.cap.isOpened():
                self.is_open = True
                logger.info("Camera initialized successfully")
            else:
                logger.error("Failed to initialize camera")
                
        except Exception as e:
            logger.error(f"Error initializing camera: {e}")
            self.is_open = False

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
                    return True, frame
            else:
                return True, frame

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
            # Upload frame to GPU
            gpu_frame = cv2.cuda_GpuMat()
            gpu_frame.upload(frame)

            # Resize using CUDA
            gpu_resized = cv2.cuda.resize(gpu_frame, PROCESSING_SCALE)

            # Download back to CPU
            processed = gpu_resized.download()

            return processed
        except Exception as e:
            logger.warning(f"CUDA processing error: {e}")
            # Fallback to CPU resize
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
    try:
        cuda_enabled = cv2.cuda.getCudaEnabledDeviceCount() > 0
        return {
            "cuda_available": cuda_enabled,
            "cuda_device_count": cv2.cuda.getCudaEnabledDeviceCount() if cuda_enabled else 0
        }
    except Exception as e:
        logger.warning(f"Failed to check CUDA: {e}")
        return {
            "cuda_available": False,
            "cuda_device_count": 0
        }

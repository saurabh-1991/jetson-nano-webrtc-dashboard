"""Configuration for Jetson Nano Dashboard"""

# Camera Configuration
CAMERA_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30

# GStreamer Pipeline Configuration
GST_PIPELINE = (
    f"v4l2src device={CAMERA_DEVICE} ! "
    f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
    "jpegparse ! "
    "nvjpegdec ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink drop=1"
)

# CUDA Processing Configuration
CUDA_ENABLED = True
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

"""FastAPI Backend for Jetson Nano Dashboard"""

import atexit
import logging
import asyncio
import signal
import sys
from datetime import datetime
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import cv2

from .config import API_DEBUG, LOG_LEVEL, LOG_FORMAT
from .camera import get_camera, check_cuda_availability
from . import camera as camera_module
from .gpio_control import get_gpio_controller
from . import gpio_control as gpio_module
from .websocket import (
    handle_websocket_connection,
    get_device_status,
    broadcast_device_status
)


def is_webrtc_available() -> bool:
    """Check whether WebRTC dependencies are available at runtime."""
    try:
        import aiortc  # noqa: F401
        from .webrtc import get_webrtc_manager as _get_webrtc_manager  # noqa: F401
        return True
    except Exception:
        return False


def get_webrtc_manager_safe():
    """Lazy import WebRTC manager to avoid hard startup dependency."""
    from .webrtc import get_webrtc_manager
    return get_webrtc_manager()

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Status tracking
status_broadcast_task = None


def cleanup_resources():
    """Cleanup resources on interpreter exit."""
    try:
        if getattr(camera_module, 'camera', None) is not None:
            camera_module.camera.release()
    except Exception as e:
        logger.warning(f"Camera cleanup failed at exit: {e}")
    try:
        if getattr(gpio_module, 'gpio_controller', None) is not None:
            gpio_module.gpio_controller.cleanup()
    except Exception as e:
        logger.warning(f"GPIO cleanup failed at exit: {e}")


atexit.register(cleanup_resources)


def handle_exit(signal_number, frame):
    """Handle process exit signals."""
    logger.info(f"Received signal {signal_number}, cleaning up resources...")
    if status_broadcast_task:
        try:
            status_broadcast_task.cancel()
        except Exception as e:
            logger.warning(f"Failed to cancel status broadcast task: {e}")
    cleanup_resources()
    sys.exit(0)

for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, handle_exit)


# Create FastAPI app
app = FastAPI(
    title="Jetson Nano Dashboard API",
    description="Real-time video streaming and GPIO control",
    version="1.0.0"
)

# Startup and shutdown handlers (compatible with Python 3.6)
@app.on_event("startup")
async def on_startup():
    global status_broadcast_task
    logger.info("Starting Jetson Nano Dashboard backend")
    status_broadcast_task = asyncio.ensure_future(broadcast_device_status())


@app.on_event("shutdown")
async def on_shutdown():
    global status_broadcast_task
    logger.info("Shutting down Jetson Nano Dashboard backend")
    if status_broadcast_task:
        status_broadcast_task.cancel()
        try:
            await status_broadcast_task
        except asyncio.CancelledError:
            pass

    # Clean up resources
    if getattr(camera_module, 'camera', None) is not None:
        camera_module.camera.release()
    if getattr(gpio_module, 'gpio_controller', None) is not None:
        gpio_module.gpio_controller.cleanup()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== ROOT ENDPOINTS ====================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "Jetson Nano Dashboard",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    camera = get_camera()
    return {
        "status": "healthy",
        "camera": {
            "is_open": camera.is_open,
            "frame_count": camera.get_frame_count()
        },
        "timestamp": datetime.now().isoformat()
    }


# ==================== SYSTEM INFO ENDPOINTS ====================

@app.get("/api/system/info")
async def system_info():
    """Get system information"""
    cuda_info = check_cuda_availability()
    return {
        "device": "Jetson Nano",
        "cuda": cuda_info,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/system/status")
async def system_status():
    """Get complete system status"""
    status = get_device_status()
    status["timestamp"] = datetime.now().isoformat()
    return status


# ==================== CAMERA ENDPOINTS ====================

@app.get("/api/camera/info")
async def camera_info():
    """Get camera information"""
    camera = get_camera()
    return {
        "is_open": camera.is_open,
        "frame_count": camera.get_frame_count(),
        "cuda_enabled": camera.cuda_enabled,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/camera/frame")
async def get_frame():
    """Get single frame as JPEG"""
    camera = get_camera()
    
    success, frame = camera.get_frame()
    if not success or frame is None:
        raise HTTPException(status_code=500, detail="Failed to capture frame")

    # Encode frame as JPEG
    success, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode frame")

    return StreamingResponse(
        iter([jpeg.tobytes()]),
        media_type="image/jpeg"
    )


@app.get("/api/camera/stream")
async def stream_mjpeg():
    """Stream video as MJPEG (fallback for low-latency needs)"""
    async def generate():
        camera = get_camera()
        
        while True:
            try:
                success, frame = camera.get_frame()
                if not success or frame is None:
                    continue

                # Encode frame as JPEG
                success, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not success:
                    continue

                # Yield MJPEG boundary
                yield b"--frame\r\n"
                yield b"Content-Type: image/jpeg\r\n"
                yield b"Content-Length: " + str(len(jpeg.tobytes())).encode() + b"\r\n\r\n"
                yield jpeg.tobytes()
                yield b"\r\n"

                # Small delay to limit frame rate
                await asyncio.sleep(0.033)  # ~30 FPS

            except Exception as e:
                logger.error(f"Error in MJPEG stream: {e}")
                break

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ==================== GPIO ENDPOINTS ====================

@app.get("/api/gpio/status")
async def gpio_status():
    """Get GPIO status"""
    gpio = get_gpio_controller()
    return {
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/on")
async def gpio_on():
    """Turn LED on"""
    gpio = get_gpio_controller()
    result = gpio.led_on()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/off")
async def gpio_off():
    """Turn LED off"""
    gpio = get_gpio_controller()
    result = gpio.led_off()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/toggle")
async def gpio_toggle():
    """Toggle LED"""
    gpio = get_gpio_controller()
    result = gpio.toggle_led()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


# ==================== WEBRTC ENDPOINTS ====================

@app.post("/api/webrtc/offer")
async def webrtc_offer(request: dict):
    """Handle WebRTC offer"""
    if not is_webrtc_available():
        raise HTTPException(
            status_code=503,
            detail="WebRTC is unavailable on this target build. Use /api/camera/stream (MJPEG) instead."
        )

    try:
        from aiortc import RTCSessionDescription
        from .webrtc import CameraVideoTrack
        
        manager = get_webrtc_manager_safe()
        pc = manager.create_peer_connection()
        
        # Handle the offer
        offer = RTCSessionDescription(
            sdp=request["sdp"],
            type=request["type"]
        )
        
        await pc.setRemoteDescription(offer)

        # Add the camera track after setting the remote description
        pc.addTrack(CameraVideoTrack())
        
        # Create answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
    except Exception as e:
        logger.exception("WebRTC error")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication"""
    await handle_websocket_connection(websocket)


# ==================== STATUS ENDPOINTS ====================

@app.get("/api/stats")
async def get_stats():
    """Get application statistics"""
    camera = get_camera()
    webrtc_connections = 0
    if is_webrtc_available():
        try:
            webrtc_mgr = get_webrtc_manager_safe()
            webrtc_connections = webrtc_mgr.get_connection_count()
        except Exception:
            webrtc_connections = 0
    
    return {
        "camera_frames": camera.get_frame_count(),
        "webrtc_connections": webrtc_connections,
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=API_DEBUG,
        log_level=LOG_LEVEL.lower()
    )

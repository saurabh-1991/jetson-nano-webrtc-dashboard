"""FastAPI Backend for Jetson Nano Dashboard"""

import atexit
import logging
import asyncio
import signal
import sys
import os
import time
import uuid
import subprocess
from datetime import datetime
from typing import Any, Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .config import API_DEBUG, LOG_LEVEL, LOG_FORMAT
from .camera import get_camera, check_cuda_availability
from . import camera as camera_module
from .gpio_control import get_gpio_controller
from . import gpio_control as gpio_module
from .sensor_data import get_sensor_data_service
from .event_logger import get_event_logger
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


def _run_git_command(path: str, args: List[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except Exception:
        return ""
    return ""


def get_software_version_info() -> Dict[str, str]:
    """Return software version metadata for operator visibility in UI footer."""
    env_branch = (os.getenv("APP_GIT_BRANCH") or "").strip()
    env_commit = (os.getenv("APP_GIT_COMMIT") or "").strip()

    candidate_paths = [
        "/workspace",
        "/workspace/backend",
        "/app",
    ]

    branch = env_branch
    commit = env_commit

    if not branch:
        for path in candidate_paths:
            branch = _run_git_command(path, ["rev-parse", "--abbrev-ref", "HEAD"])
            if branch:
                break

    if not commit:
        for path in candidate_paths:
            commit = _run_git_command(path, ["rev-parse", "--short", "HEAD"])
            if commit:
                break

    if not branch:
        branch = "unknown"
    if not commit:
        commit = "unknown"

    return {
        "branch": branch,
        "commit": commit,
        "label": f"{branch}@{commit}",
    }

# Status tracking
status_broadcast_task = None
camera_idle_watchdog_task = None
safety_watchdog_task = None
active_mjpeg_sessions = set()
active_mjpeg_lock = asyncio.Lock()
CAMERA_IDLE_RELEASE_SECONDS = max(3, int(os.getenv("CAMERA_IDLE_RELEASE_SECONDS", "6")))

CONTROL_HEARTBEAT_TIMEOUT_SECONDS = max(
    5, int(os.getenv("CONTROL_HEARTBEAT_TIMEOUT_SECONDS", "20"))
)
EVENT_LOG_COMPACT_SECONDS = max(5, int(os.getenv("EVENT_LOG_COMPACT_SECONDS", "10")))

last_frontend_heartbeat_ts = 0.0
frontend_heartbeat_seen = False
last_control_activity_ts = time.time()
safety_reset_count = 0
next_event_compact_ts = 0.0


async def camera_idle_watchdog():
    """Release camera automatically after inactivity when no viewers remain."""
    while True:
        try:
            await asyncio.sleep(1.0)

            camera = getattr(camera_module, "camera", None)
            if camera is None:
                continue

            async with active_mjpeg_lock:
                current_mjpeg_clients = len(active_mjpeg_sessions)

            current_webrtc_connections = 0
            if is_webrtc_available():
                try:
                    current_webrtc_connections = get_webrtc_manager_safe().get_connection_count()
                except Exception:
                    current_webrtc_connections = 0

            released = camera.maybe_release_if_idle(
                idle_seconds=CAMERA_IDLE_RELEASE_SECONDS,
                active_mjpeg_clients=current_mjpeg_clients,
                webrtc_connections=current_webrtc_connections,
            )
            if released:
                camera_module.camera = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Camera idle watchdog error: {e}")


async def safety_watchdog_loop():
    """Apply fail-safe GPIO OFF when heartbeat/control path appears unhealthy."""
    global safety_reset_count, next_event_compact_ts

    event_log = get_event_logger()
    while True:
        try:
            await asyncio.sleep(1.0)
            now_ts = time.time()

            # Keep on-disk event file compacted to retention window.
            if now_ts >= next_event_compact_ts:
                event_log.compact_now()
                next_event_compact_ts = now_ts + EVENT_LOG_COMPACT_SECONDS

            if not frontend_heartbeat_seen:
                continue

            stale_frontend = (now_ts - last_frontend_heartbeat_ts) > CONTROL_HEARTBEAT_TIMEOUT_SECONDS
            stale_control = (now_ts - last_control_activity_ts) > CONTROL_HEARTBEAT_TIMEOUT_SECONDS

            if stale_frontend and stale_control:
                gpio = get_gpio_controller()
                if gpio.any_output_on():
                    success = gpio.force_all_outputs_off(reason="safety_watchdog_timeout")
                    safety_reset_count += 1
                    event_log.log_event(
                        source="backend",
                        event_type="safety_watchdog_reset",
                        severity="warning",
                        payload={
                            "success": bool(success),
                            "timeout_seconds": CONTROL_HEARTBEAT_TIMEOUT_SECONDS,
                            "safety_reset_count": safety_reset_count,
                        },
                    )
                    logger.warning(
                        "Safety watchdog triggered fail-safe reset. success=%s count=%s",
                        success,
                        safety_reset_count,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Safety watchdog loop error: %s", e)


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
    global status_broadcast_task, camera_idle_watchdog_task, safety_watchdog_task
    logger.info("Starting Jetson Nano Dashboard backend")
    status_broadcast_task = asyncio.ensure_future(broadcast_device_status())
    camera_idle_watchdog_task = asyncio.ensure_future(camera_idle_watchdog())
    safety_watchdog_task = asyncio.ensure_future(safety_watchdog_loop())
    get_event_logger().log_event("backend", "startup", "info", {"version": "1.0.0"})


@app.on_event("shutdown")
async def on_shutdown():
    global status_broadcast_task, camera_idle_watchdog_task, safety_watchdog_task
    logger.info("Shutting down Jetson Nano Dashboard backend")
    get_event_logger().log_event("backend", "shutdown", "info", {})
    if status_broadcast_task:
        status_broadcast_task.cancel()
        try:
            await status_broadcast_task
        except asyncio.CancelledError:
            pass
    if camera_idle_watchdog_task:
        camera_idle_watchdog_task.cancel()
        try:
            await camera_idle_watchdog_task
        except asyncio.CancelledError:
            pass
    if safety_watchdog_task:
        safety_watchdog_task.cancel()
        try:
            await safety_watchdog_task
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


def _is_control_path(path: str) -> bool:
    return path.startswith("/api/gpio") or path.startswith("/api/system/status")


@app.middleware("http")
async def request_event_middleware(request: Request, call_next):
    """Log backend request telemetry and track control path liveness."""
    global last_control_activity_ts

    started = time.time()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
        duration_ms = round((time.time() - started) * 1000.0, 2)
        client_host = request.client.host if request.client else None

        if _is_control_path(path) and response.status_code < 500:
            last_control_activity_ts = time.time()

        if path.startswith("/api"):
            if response.status_code >= 500:
                severity = "error"
            elif response.status_code >= 400:
                severity = "warning"
            else:
                severity = "info"

            get_event_logger().log_event(
                source="backend",
                event_type="api_request",
                severity=severity,
                payload={
                    "message": f"{method} {path} -> {int(response.status_code)} in {duration_ms} ms",
                    "method": method,
                    "path": path,
                    "status": int(response.status_code),
                    "duration_ms": duration_ms,
                    "client_host": client_host,
                },
            )
        return response
    except Exception as exc:
        duration_ms = round((time.time() - started) * 1000.0, 2)
        client_host = request.client.host if request.client else None
        get_event_logger().log_event(
            source="backend",
            event_type="api_exception",
            severity="error",
            payload={
                "message": f"{method} {path} failed in {duration_ms} ms: {exc}",
                "method": method,
                "path": path,
                "duration_ms": duration_ms,
                "error": str(exc),
                "client_host": client_host,
            },
        )
        raise


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
    camera = getattr(camera_module, "camera", None)

    return {
        "status": "healthy",
        "camera": {
            "is_open": camera.is_open if camera else False,
            "frame_count": camera.get_frame_count() if camera else 0
        },
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/safety/heartbeat")
async def safety_heartbeat(payload: Dict[str, Any] = None):
    """Heartbeat from frontend to prove control UI loop is alive."""
    global last_frontend_heartbeat_ts, frontend_heartbeat_seen

    payload = payload or {}
    frontend_heartbeat_seen = True
    last_frontend_heartbeat_ts = time.time()

    get_event_logger().log_event(
        source="frontend",
        event_type="heartbeat",
        severity="info",
        payload={
            "message": "Frontend heartbeat received",
            "session_id": payload.get("session_id"),
            "connection_state": payload.get("connection_state"),
        },
    )
    return {"ok": True, "timestamp": datetime.now().isoformat()}


@app.post("/api/events/frontend")
async def ingest_frontend_events(payload: Dict[str, Any]):
    """Ingest frontend event batch for 2-minute rolling diagnostics."""
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events must be an array")

    event_log = get_event_logger()
    accepted = 0
    for item in events[:300]:
        if not isinstance(item, dict):
            continue
        event_log.log_event(
            source="frontend",
            event_type=str(item.get("type", "frontend_event")),
            severity=str(item.get("severity", "info")),
            payload={
                "message": item.get("message"),
                "meta": item.get("meta", {}),
                "at": item.get("at"),
                "session_id": payload.get("session_id"),
            },
        )
        accepted += 1

    return {
        "accepted": accepted,
        "retention_seconds": get_event_logger().get_meta().get("retention_seconds", 120),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/events/recent")
async def get_recent_events():
    """Get recent backend/frontend events retained in rolling 2-minute window."""
    event_log = get_event_logger()
    return {
        "meta": event_log.get_meta(),
        "events": event_log.get_recent_events(),
        "safety": {
            "frontend_heartbeat_seen": frontend_heartbeat_seen,
            "last_frontend_heartbeat_age_seconds": round(max(0.0, time.time() - last_frontend_heartbeat_ts), 2)
            if last_frontend_heartbeat_ts > 0
            else None,
            "last_control_activity_age_seconds": round(max(0.0, time.time() - last_control_activity_ts), 2),
            "watchdog_timeout_seconds": CONTROL_HEARTBEAT_TIMEOUT_SECONDS,
            "safety_reset_count": safety_reset_count,
        },
        "timestamp": datetime.now().isoformat(),
    }


# ==================== SYSTEM INFO ENDPOINTS ====================

@app.get("/api/system/info")
async def system_info():
    """Get system information"""
    cuda_info = check_cuda_availability()
    return {
        "device": "Jetson Nano",
        "cuda": cuda_info,
        "software": get_software_version_info(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/system/status")
async def system_status():
    """Get complete system status"""
    status = get_device_status()
    sensor_service = get_sensor_data_service()
    status["sensors"] = await run_in_threadpool(sensor_service.get_latest)
    status["timestamp"] = datetime.now().isoformat()
    return status


@app.get("/api/sensors/latest")
async def sensors_latest():
    """Get latest sensor readings from datalogger abstraction."""
    service = get_sensor_data_service()
    sensors = await run_in_threadpool(service.get_latest)
    return {
        "sensors": sensors,
        "simulation_enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sensors/history")
async def sensors_history(limit: int = 120, interval_minutes: int = 1, hours: int = 24):
    """Get recent sensor reading history for graph plotting."""
    service = get_sensor_data_service()
    history = await run_in_threadpool(
        service.get_history,
        limit,
        interval_minutes,
        hours,
    )
    return {
        "history": history,
        "count": len(history),
        "interval_minutes": interval_minutes,
        "hours": hours,
        "simulation_enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sensors/simulation")
async def sensors_simulation_state():
    """Get current simulation mode for sensor sampling."""
    service = get_sensor_data_service()
    return {
        "enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/sensors/simulation")
async def sensors_simulation_set(payload: dict):
    """Set simulation mode (true: simulated data, false: read from datalogger)."""
    service = get_sensor_data_service()
    enabled = bool(payload.get("enabled", False))
    service.set_simulation_enabled(enabled)
    return {
        "enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


# ==================== CAMERA ENDPOINTS ====================

@app.get("/api/camera/info")
async def camera_info():
    """Get camera information"""
    camera = getattr(camera_module, "camera", None)
    pipeline_info = camera.get_runtime_diagnostics() if camera else {}

    return {
        "is_open": camera.is_open if camera else False,
        "frame_count": camera.get_frame_count() if camera else 0,
        "cuda_enabled": camera.cuda_enabled if camera else False,
        "performance": camera.get_performance_stats() if camera else None,
        "selected_pipeline": pipeline_info.get("selected_pipeline"),
        "selected_pipeline_mode": pipeline_info.get("selected_pipeline_mode"),
        "pipeline_diagnostics": pipeline_info,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/camera/stop")
async def stop_camera(request: dict = None):
    """Request camera release after local client stop; safe for multi-client use."""
    request = request or {}
    stream_session_id = request.get("stream_session_id")

    # Explicitly unregister the caller's MJPEG session for immediate stats update.
    if stream_session_id:
        async with active_mjpeg_lock:
            if stream_session_id in active_mjpeg_sessions:
                active_mjpeg_sessions.discard(stream_session_id)

    # Give stream generators a short moment to observe disconnection and decrement counters.
    await asyncio.sleep(0.35)

    async with active_mjpeg_lock:
        current_mjpeg_clients = len(active_mjpeg_sessions)

    current_webrtc_connections = 0
    if is_webrtc_available():
        try:
            current_webrtc_connections = get_webrtc_manager_safe().get_connection_count()
        except Exception:
            current_webrtc_connections = 0

    camera = getattr(camera_module, "camera", None)
    released = False
    if camera is not None:
        released = camera.maybe_release_if_idle(
            idle_seconds=0,
            active_mjpeg_clients=current_mjpeg_clients,
            webrtc_connections=current_webrtc_connections,
        )
        if released:
            camera_module.camera = None

    return {
        "released": released,
        "stream_session_id": stream_session_id,
        "active_mjpeg_clients": current_mjpeg_clients,
        "webrtc_connections": current_webrtc_connections,
        "camera_open": bool(getattr(camera_module, "camera", None) and camera_module.camera.is_open),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/camera/recover")
async def recover_camera(request: dict = None):
    """Force camera release and reinitialize for manual operator recovery."""
    request = request or {}
    reason = str(request.get("reason") or "manual_operator_recover")

    async with active_mjpeg_lock:
        mjpeg_clients = len(active_mjpeg_sessions)

    webrtc_connections = 0
    if is_webrtc_available():
        try:
            webrtc_connections = get_webrtc_manager_safe().get_connection_count()
        except Exception:
            webrtc_connections = 0

    camera = getattr(camera_module, "camera", None)
    was_open = bool(camera and camera.is_open)
    forced_release = False

    if camera is not None:
        try:
            camera.release()
            forced_release = True
        except Exception:
            forced_release = False
        camera_module.camera = None

    # Create a fresh camera instance.
    new_camera = get_camera()
    recovered = bool(new_camera and new_camera.is_open)
    diagnostics = new_camera.get_runtime_diagnostics() if new_camera else {}

    get_event_logger().log_event(
        source="backend",
        event_type="camera_manual_recover",
        severity="info" if recovered else "warning",
        payload={
            "message": (
                "Manual camera recovery succeeded"
                if recovered
                else "Manual camera recovery failed"
            ),
            "reason": reason,
            "was_open": was_open,
            "forced_release": forced_release,
            "active_mjpeg_clients": mjpeg_clients,
            "active_webrtc_clients": webrtc_connections,
            "selected_source": diagnostics.get("selected_pipeline_source"),
        },
    )

    return {
        "success": recovered,
        "reason": reason,
        "was_open": was_open,
        "forced_release": forced_release,
        "active_mjpeg_clients": mjpeg_clients,
        "active_webrtc_clients": webrtc_connections,
        "camera": {
            "is_open": recovered,
            "selected_source": diagnostics.get("selected_pipeline_source"),
            "selected_pipeline": diagnostics.get("selected_pipeline"),
            "recovery": diagnostics.get("recovery"),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/camera/frame")
async def get_frame():
    """Get single frame as JPEG"""
    camera = get_camera()
    if not camera.is_open:
        raise HTTPException(
            status_code=503,
            detail="Camera is unavailable. Verify camera device mapping and try again."
        )

    success, jpeg_bytes = camera.get_jpeg_frame(quality=80)
    if not success or jpeg_bytes is None:
        raise HTTPException(status_code=503, detail="Failed to capture frame from camera")

    return StreamingResponse(
        iter([jpeg_bytes]),
        media_type="image/jpeg"
    )


@app.get("/api/camera/stream")
async def stream_mjpeg(request: Request):
    """Stream video as MJPEG (fallback for low-latency needs)"""
    startup_camera = get_camera()
    if not startup_camera.is_open:
        raise HTTPException(
            status_code=503,
            detail="Camera is unavailable. Verify camera device mapping and retry stream."
        )

    async def generate():
        stream_session_id = request.query_params.get("sid") or str(uuid.uuid4())
        camera = get_camera()

        async with active_mjpeg_lock:
            active_mjpeg_sessions.add(stream_session_id)
            logger.info(
                "MJPEG client connected sid=%s. Active clients: %s",
                stream_session_id,
                len(active_mjpeg_sessions),
            )
        
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("MJPEG client disconnected")
                    break

                success, jpeg_bytes = camera.get_jpeg_frame(quality=80)
                if not success or jpeg_bytes is None:
                    await asyncio.sleep(0.05)
                    continue

                # Yield MJPEG boundary
                yield b"--frame\r\n"
                yield b"Content-Type: image/jpeg\r\n"
                yield b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                yield jpeg_bytes
                yield b"\r\n"

                # Small delay to limit frame rate
                await asyncio.sleep(0.033)  # ~30 FPS

        except asyncio.CancelledError:
            logger.info("MJPEG stream cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in MJPEG stream: {e}")
        finally:
            async with active_mjpeg_lock:
                active_mjpeg_sessions.discard(stream_session_id)
                remaining_mjpeg_clients = len(active_mjpeg_sessions)
                logger.info(
                    "MJPEG client disconnected sid=%s. Active clients: %s",
                    stream_session_id,
                    remaining_mjpeg_clients,
                )

            # Release camera when no active MJPEG clients and no active WebRTC clients.
            try:
                webrtc_connections = 0
                if is_webrtc_available():
                    try:
                        webrtc_mgr = get_webrtc_manager_safe()
                        webrtc_connections = webrtc_mgr.get_connection_count()
                    except Exception:
                        webrtc_connections = 0

                if remaining_mjpeg_clients == 0 and webrtc_connections == 0:
                    if getattr(camera_module, "camera", None) is not None:
                        camera_module.camera.release()
                        camera_module.camera = None
                        logger.info("Released camera after last stream client disconnected")
            except Exception as e:
                logger.warning(f"Failed to release camera on stream disconnect: {e}")

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
        "gpio": gpio.get_outputs_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/gpio/outputs")
async def gpio_outputs_status():
    """Get all configured GPIO outputs and current states."""
    gpio = get_gpio_controller()
    return {
        "gpio": gpio.get_outputs_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/on")
async def gpio_output_on(output_name: str):
    """Turn a named GPIO output on."""
    gpio = get_gpio_controller()
    result = gpio.turn_output_on(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_on",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' set to ON ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/off")
async def gpio_output_off(output_name: str):
    """Turn a named GPIO output off."""
    gpio = get_gpio_controller()
    result = gpio.turn_output_off(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_off",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' set to OFF ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/toggle")
async def gpio_output_toggle(output_name: str):
    """Toggle a named GPIO output."""
    gpio = get_gpio_controller()
    result = gpio.toggle_output(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_toggle",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' toggled ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/on")
async def gpio_on():
    """Legacy endpoint: maps to Exhaust Blower ON."""
    gpio = get_gpio_controller()
    result = gpio.led_on()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/off")
async def gpio_off():
    """Legacy endpoint: maps to Exhaust Blower OFF."""
    gpio = get_gpio_controller()
    result = gpio.led_off()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/toggle")
async def gpio_toggle():
    """Legacy endpoint: maps to Exhaust Blower toggle."""
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
    camera = getattr(camera_module, "camera", None)
    webrtc_connections = 0
    if is_webrtc_available():
        try:
            webrtc_mgr = get_webrtc_manager_safe()
            webrtc_connections = webrtc_mgr.get_connection_count()
        except Exception:
            webrtc_connections = 0
    
    return {
        "camera_frames": camera.get_frame_count() if camera else 0,
        "camera_performance": camera.get_performance_stats() if camera else None,
        "camera_idle_release_seconds": CAMERA_IDLE_RELEASE_SECONDS,
        "active_mjpeg_clients": len(active_mjpeg_sessions),
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

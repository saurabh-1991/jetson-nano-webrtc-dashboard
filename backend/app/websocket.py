"""WebSocket handlers for real-time communication"""

import logging
import json
import asyncio
from typing import Set, Dict
from fastapi import WebSocket, WebSocketDisconnect
from .camera import check_cuda_availability
from . import camera as camera_module
from .gpio_control import get_gpio_controller

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.connection_data: Dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket):
        """Accept and register a WebSocket connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
        self.connection_data[websocket] = {
            "connected_at": None
        }
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection"""
        self.active_connections.discard(websocket)
        self.connection_data.pop(websocket, None)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def send_to_client(self, websocket: WebSocket, message: dict):
        """Send message to specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending message to client: {e}")
            self.disconnect(websocket)

    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)


# Global WebSocket manager
ws_manager = None


def get_ws_manager() -> WebSocketManager:
    """Get or create WebSocket manager"""
    global ws_manager
    if ws_manager is None:
        ws_manager = WebSocketManager()
    return ws_manager


async def handle_websocket_connection(websocket: WebSocket):
    """Handle WebSocket connection and messages"""
    manager = get_ws_manager()
    await manager.connect(websocket)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            await process_websocket_message(websocket, message)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def process_websocket_message(websocket: WebSocket, message: dict):
    """Process incoming WebSocket message"""
    try:
        message_type = message.get("type")
        manager = get_ws_manager()

        if message_type == "ping":
            await manager.send_to_client(websocket, {"type": "pong"})

        elif message_type == "status_request":
            status = get_device_status()
            await manager.send_to_client(websocket, {
                "type": "device_status",
                "data": status
            })

        elif message_type == "gpio_on":
            gpio = get_gpio_controller()
            gpio.turn_output_on("exhaust_blower")
            state = gpio.get_outputs_state()
            await manager.broadcast({
                "type": "gpio_state_changed",
                "data": state
            })

        elif message_type == "gpio_off":
            gpio = get_gpio_controller()
            gpio.turn_output_off("exhaust_blower")
            state = gpio.get_outputs_state()
            await manager.broadcast({
                "type": "gpio_state_changed",
                "data": state
            })

        else:
            logger.warning(f"Unknown message type: {message_type}")

    except json.JSONDecodeError:
        logger.error("Invalid JSON received")
    except Exception as e:
        logger.error(f"Error processing message: {e}")


def get_device_status() -> dict:
    """Get current device status"""
    cameras_status = {}
    try:
        camera_ids = camera_module.get_camera_ids()
    except Exception:
        camera_ids = ["cam1"]

    for camera_id in camera_ids:
        camera = camera_module.get_existing_camera(camera_id)
        diagnostics = camera.get_runtime_diagnostics() if camera else {}
        recovery = diagnostics.get("recovery", {}) if diagnostics else {}
        selected_source = diagnostics.get("selected_pipeline_source") if diagnostics else None
        selected_pipeline = diagnostics.get("selected_pipeline") if diagnostics else None
        cameras_status[camera_id] = {
            "camera_id": camera_id,
            "is_open": camera.is_open if camera else False,
            "frame_count": camera.get_frame_count() if camera else 0,
            "selected_source": selected_source,
            "selected_pipeline": selected_pipeline,
            "recovery": {
                "attempts": int(recovery.get("attempts", 0)),
                "successes": int(recovery.get("successes", 0)),
                "failures": int(recovery.get("failures", 0)),
                "consecutive_failures": int(recovery.get("consecutive_failures", 0)),
                "next_recovery_allowed_in_seconds": float(recovery.get("next_recovery_allowed_in_seconds", 0.0)),
                "last_recovery_reason": recovery.get("last_recovery_reason"),
            },
        }

    legacy_camera = cameras_status.get("cam1") or next(iter(cameras_status.values()), None)
    gpio = get_gpio_controller()
    cuda_info = check_cuda_availability()
    
    return {
        "camera": {
            "is_open": bool(legacy_camera.get("is_open")) if legacy_camera else False,
            "frame_count": int(legacy_camera.get("frame_count", 0)) if legacy_camera else 0,
            "selected_source": legacy_camera.get("selected_source") if legacy_camera else None,
            "selected_pipeline": legacy_camera.get("selected_pipeline") if legacy_camera else None,
            "recovery": (legacy_camera.get("recovery") if legacy_camera else {}),
        },
        "cameras": cameras_status,
        "gpio": gpio.get_outputs_state(),
        "cuda": cuda_info,
        "websocket_connections": get_ws_manager().get_connection_count(),
        "timestamp": None  # Will be set by the API
    }


async def broadcast_device_status():
    """Periodically broadcast device status to all clients"""
    manager = get_ws_manager()
    
    while True:
        try:
            await asyncio.sleep(5)  # Broadcast every 5 seconds
            
            if manager.get_connection_count() > 0:
                status = get_device_status()
                await manager.broadcast({
                    "type": "device_status",
                    "data": status
                })
        except Exception as e:
            logger.error(f"Error broadcasting status: {e}")

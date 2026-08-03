"""Delta VFD (MS300) control service over Modbus TCP."""

import logging
import threading
import time
from typing import Any, Dict, Optional

from .config import (
    VFD_DEFAULT_SPEED_HZ,
    VFD_ENABLED,
    VFD_HOST,
    VFD_MAX_SPEED_HZ,
    VFD_MIN_SPEED_HZ,
    VFD_MIN_WRITE_INTERVAL_MS,
    VFD_PORT,
    VFD_RUN_COMMAND_REGISTER,
    VFD_RUN_FORWARD_WORD,
    VFD_SLAVE_ID,
    VFD_SPEED_COMMAND_REGISTER,
    VFD_SPEED_SCALE,
    VFD_STOP_WORD,
    VFD_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

try:
    from pymodbus.client.sync import ModbusTcpClient  # type: ignore[reportMissingImports]
    MODBUS_TCP_AVAILABLE = True
except Exception:
    ModbusTcpClient = None
    MODBUS_TCP_AVAILABLE = False


class VFDController:
    """Control VFD run/stop and speed setpoint with guarded writes."""

    def __init__(self):
        self._enabled = bool(VFD_ENABLED)
        self._host = str(VFD_HOST or "").strip()
        self._port = int(VFD_PORT)
        self._slave_id = int(VFD_SLAVE_ID)
        self._timeout_seconds = float(VFD_TIMEOUT_SECONDS)

        self._min_speed_hz = float(min(VFD_MIN_SPEED_HZ, VFD_MAX_SPEED_HZ))
        self._max_speed_hz = float(max(VFD_MIN_SPEED_HZ, VFD_MAX_SPEED_HZ))
        self._speed_scale = int(VFD_SPEED_SCALE)

        self._run_register = int(VFD_RUN_COMMAND_REGISTER)
        self._speed_register = int(VFD_SPEED_COMMAND_REGISTER)
        self._run_word = int(VFD_RUN_FORWARD_WORD)
        self._stop_word = int(VFD_STOP_WORD)

        self._min_write_interval_seconds = max(0.05, float(VFD_MIN_WRITE_INTERVAL_MS) / 1000.0)

        self._state_lock = threading.RLock()
        self._client: Optional[Any] = None
        self._last_write_ts = 0.0
        self._last_error: Optional[str] = None
        self._is_running = False
        self._speed_hz = float(max(self._min_speed_hz, min(self._max_speed_hz, VFD_DEFAULT_SPEED_HZ)))

        if self._enabled and not MODBUS_TCP_AVAILABLE:
            self._last_error = "pymodbus_missing"
            logger.warning("VFD enabled but pymodbus ModbusTcpClient is unavailable")

    def _config_ready(self) -> bool:
        if not self._enabled:
            self._last_error = "vfd_disabled"
            return False
        if not MODBUS_TCP_AVAILABLE:
            self._last_error = "pymodbus_missing"
            return False
        if not self._host:
            self._last_error = "vfd_host_missing"
            return False
        if self._run_register < 0 or self._speed_register < 0:
            self._last_error = "invalid_register_config"
            return False
        return True

    def _ensure_client(self):
        if not self._config_ready():
            return None

        if self._client is None:
            self._client = ModbusTcpClient(host=self._host, port=self._port, timeout=self._timeout_seconds)

        try:
            if not self._client.connect():
                self._last_error = "modbus_connect_failed"
                return None
        except Exception as exc:
            self._last_error = "modbus_connect_exception"
            logger.warning("VFD Modbus TCP connect exception: %s", exc)
            return None

        return self._client

    def _wait_write_interval_if_needed(self):
        elapsed = time.time() - self._last_write_ts
        remaining = self._min_write_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _write_register(self, register: int, value: int) -> bool:
        client = self._ensure_client()
        if client is None:
            return False

        self._wait_write_interval_if_needed()

        try:
            response = client.write_register(address=int(register), value=int(value), unit=self._slave_id)
            if not response or response.isError():
                self._last_error = "modbus_write_error"
                return False
            self._last_write_ts = time.time()
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = "modbus_write_exception"
            logger.warning("VFD write exception register=%s value=%s: %s", register, value, exc)
            return False

    def set_run_state(self, run: bool) -> bool:
        with self._state_lock:
            word = self._run_word if bool(run) else self._stop_word
            ok = self._write_register(self._run_register, word)
            if ok:
                self._is_running = bool(run)
            return ok

    def set_speed_hz(self, speed_hz: float) -> Dict[str, Any]:
        with self._state_lock:
            try:
                requested = float(speed_hz)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error": "invalid_speed_value",
                    "min_speed_hz": self._min_speed_hz,
                    "max_speed_hz": self._max_speed_hz,
                }

            if requested < self._min_speed_hz or requested > self._max_speed_hz:
                return {
                    "success": False,
                    "error": "speed_out_of_range",
                    "requested_speed_hz": requested,
                    "min_speed_hz": self._min_speed_hz,
                    "max_speed_hz": self._max_speed_hz,
                }

            register_value = int(round(requested * self._speed_scale))
            ok = self._write_register(self._speed_register, register_value)
            if ok:
                self._speed_hz = requested
                return {
                    "success": True,
                    "speed_hz": round(self._speed_hz, 2),
                    "register_value": register_value,
                }

            return {
                "success": False,
                "error": self._last_error or "modbus_write_failed",
                "requested_speed_hz": requested,
                "register_value": register_value,
            }

    def force_stop(self, reason: str = "safety") -> bool:
        """Best-effort stop command used by safety logic."""
        ok = self.set_run_state(False)
        logger.warning("VFD force_stop reason=%s success=%s", reason, ok)
        return ok

    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "enabled": bool(self._enabled),
                "library_available": bool(MODBUS_TCP_AVAILABLE),
                "host_configured": bool(self._host),
                "host": self._host,
                "port": int(self._port),
                "slave_id": int(self._slave_id),
                "run_command_register": int(self._run_register),
                "speed_command_register": int(self._speed_register),
                "is_running": bool(self._is_running),
                "speed_hz": round(float(self._speed_hz), 2),
                "min_speed_hz": round(float(self._min_speed_hz), 2),
                "max_speed_hz": round(float(self._max_speed_hz), 2),
                "speed_scale": int(self._speed_scale),
                "last_error": self._last_error,
            }

    def cleanup(self):
        with self._state_lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None


vfd_controller = None


def get_vfd_controller() -> VFDController:
    global vfd_controller
    if vfd_controller is None:
        vfd_controller = VFDController()
    return vfd_controller

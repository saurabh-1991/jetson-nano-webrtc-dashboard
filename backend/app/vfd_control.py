"""Delta VFD (MS300) control service over Modbus TCP."""

import logging
import threading
import time
from typing import Any, Dict, Optional

from .config import (
    VFD_CONFIGS,
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

    def __init__(self, vfd_id: str, cfg: Dict[str, Any]):
        self._vfd_id = str(vfd_id).strip().lower() or "vfd1"

        self._enabled = bool(cfg.get("enabled", False))
        self._host = str(cfg.get("host") or "").strip()
        self._port = int(cfg.get("port", 502))
        self._slave_id = int(cfg.get("slave_id", 1))
        self._timeout_seconds = float(cfg.get("timeout_seconds", 1.0))

        min_speed_hz = float(cfg.get("min_speed_hz", 0.0))
        max_speed_hz = float(cfg.get("max_speed_hz", 50.0))
        self._min_speed_hz = float(min(min_speed_hz, max_speed_hz))
        self._max_speed_hz = float(max(min_speed_hz, max_speed_hz))
        self._speed_scale = int(cfg.get("speed_scale", 100))

        self._address_base = int(cfg.get("address_base", 0))
        self._address_offset = int(cfg.get("address_offset", 0))
        self._run_register_raw = int(cfg.get("run_command_register_raw", 0x2000))
        self._speed_register_raw = int(cfg.get("speed_command_register_raw", 0x2001))
        self._run_register = int(cfg.get("run_command_register", 0x2000))
        self._speed_register = int(cfg.get("speed_command_register", 0x2001))
        self._run_word = int(cfg.get("run_forward_word", 0x0012))
        self._stop_word = int(cfg.get("stop_word", 0x0001))

        min_write_interval_ms = int(cfg.get("min_write_interval_ms", 150))
        self._min_write_interval_seconds = max(0.05, float(min_write_interval_ms) / 1000.0)

        self._state_lock = threading.RLock()
        self._client: Optional[Any] = None
        self._last_write_ts = 0.0
        self._last_error: Optional[str] = None
        self._is_running = False
        default_speed_hz = float(cfg.get("default_speed_hz", 0.0))
        self._speed_hz = float(max(self._min_speed_hz, min(self._max_speed_hz, default_speed_hz)))

        if self._enabled and not MODBUS_TCP_AVAILABLE:
            self._last_error = "pymodbus_missing"
            logger.warning("VFD %s enabled but pymodbus ModbusTcpClient is unavailable", self._vfd_id)

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
        if self._run_word < 0 or self._run_word > 0xFFFF or self._stop_word < 0 or self._stop_word > 0xFFFF:
            self._last_error = "invalid_command_word_config"
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
            logger.warning("VFD %s Modbus TCP connect exception: %s", self._vfd_id, exc)
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
            logger.warning(
                "VFD %s write exception register=%s value=%s: %s",
                self._vfd_id,
                register,
                value,
                exc,
            )
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
        logger.warning("VFD %s force_stop reason=%s success=%s", self._vfd_id, reason, ok)
        return ok

    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "vfd_id": self._vfd_id,
                "enabled": bool(self._enabled),
                "library_available": bool(MODBUS_TCP_AVAILABLE),
                "host_configured": bool(self._host),
                "host": self._host,
                "port": int(self._port),
                "slave_id": int(self._slave_id),
                "address_base": int(self._address_base),
                "address_offset": int(self._address_offset),
                "run_command_register_raw": int(self._run_register_raw),
                "speed_command_register_raw": int(self._speed_register_raw),
                "run_command_register": int(self._run_register),
                "speed_command_register": int(self._speed_register),
                "run_forward_word": int(self._run_word),
                "stop_word": int(self._stop_word),
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


DEFAULT_VFD_ID = "vfd1"
vfd_controller = None
vfd_controllers: Dict[str, VFDController] = {}
_vfd_registry_lock = threading.RLock()


def _normalize_vfd_id(vfd_id: Optional[str]) -> str:
    normalized = str(vfd_id or DEFAULT_VFD_ID).strip().lower()
    return normalized or DEFAULT_VFD_ID


def get_available_vfd_ids() -> list:
    return list(VFD_CONFIGS.keys())


def get_vfd_controller(vfd_id: str = DEFAULT_VFD_ID) -> VFDController:
    global vfd_controller

    normalized_id = _normalize_vfd_id(vfd_id)
    if normalized_id not in VFD_CONFIGS:
        raise ValueError(f"unknown_vfd_id:{normalized_id}")

    with _vfd_registry_lock:
        controller = vfd_controllers.get(normalized_id)
        if controller is None:
            controller = VFDController(normalized_id, VFD_CONFIGS[normalized_id])
            vfd_controllers[normalized_id] = controller

        # Backward compatibility for modules that still reference vfd_controller singleton.
        if normalized_id == DEFAULT_VFD_ID:
            vfd_controller = controller

        return controller


def get_all_vfd_statuses() -> Dict[str, Dict[str, Any]]:
    statuses: Dict[str, Dict[str, Any]] = {}
    for vfd_id in get_available_vfd_ids():
        controller = get_vfd_controller(vfd_id)
        statuses[vfd_id] = controller.get_status()
    return statuses


def force_stop_all_vfds(reason: str = "safety") -> Dict[str, bool]:
    results: Dict[str, bool] = {}
    for vfd_id in get_available_vfd_ids():
        controller = get_vfd_controller(vfd_id)
        status = controller.get_status()
        was_running = bool(status.get("is_running"))
        if was_running:
            results[vfd_id] = bool(controller.force_stop(reason=reason))
        else:
            results[vfd_id] = True
    return results


def cleanup_all_vfds():
    global vfd_controller
    with _vfd_registry_lock:
        for controller in vfd_controllers.values():
            try:
                controller.cleanup()
            except Exception:
                pass
        vfd_controllers.clear()
        vfd_controller = None

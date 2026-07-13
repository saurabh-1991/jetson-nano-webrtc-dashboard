"""Sensor data service backed by Modbus RTU (RS-485) with fallback simulation."""

import logging
import math
import time
from collections import deque
from datetime import datetime, timedelta

from .modbus_sensor_config import MODBUS_CONFIG, SENSOR_REGISTER_MAP

logger = logging.getLogger(__name__)

try:
    from pymodbus.client.sync import ModbusSerialClient
    MODBUS_LIB_AVAILABLE = True
except Exception:
    ModbusSerialClient = None
    MODBUS_LIB_AVAILABLE = False


class SensorDataService:
    """Maintain latest and recent sensor samples for UI display and graphing."""

    def __init__(self):
        self._history = deque(maxlen=86400)  # up to ~48h at 2s sampling
        self._last_sample_ts = 0.0
        self._sample_interval_seconds = 2.0
        self._client = None
        self._modbus_enabled = MODBUS_CONFIG.get("enabled", True) and MODBUS_LIB_AVAILABLE

        if MODBUS_CONFIG.get("enabled", True) and not MODBUS_LIB_AVAILABLE:
            logger.warning("pymodbus not available; sensor service will use fallback generator")

    def _ensure_client(self):
        """Create/connect Modbus serial client if not active."""
        if not self._modbus_enabled:
            return None

        if self._client is None:
            self._client = ModbusSerialClient(
                method="rtu",
                port=MODBUS_CONFIG["port"],
                baudrate=MODBUS_CONFIG["baudrate"],
                bytesize=MODBUS_CONFIG["bytesize"],
                parity=MODBUS_CONFIG["parity"],
                stopbits=MODBUS_CONFIG["stopbits"],
                timeout=MODBUS_CONFIG["timeout"],
            )

        try:
            if not self._client.connect():
                logger.warning("Modbus connect failed on %s", MODBUS_CONFIG["port"])
                return None
        except Exception as e:
            logger.warning("Modbus client connect error: %s", e)
            return None

        return self._client

    @staticmethod
    def _decode_register(raw_value: int, signed: bool, scale: float, offset: float) -> float:
        value = int(raw_value)
        if signed and value >= 32768:
            value = value - 65536

        return round((value * scale) + offset, 2)

    def _read_from_datalogger(self):
        """Read configured sensor registers from Modbus datalogger."""
        client = self._ensure_client()
        if client is None:
            return None

        unit = MODBUS_CONFIG["slave_id"]
        register_type = MODBUS_CONFIG.get("register_type", "holding").lower()

        result = {}

        for key, cfg in SENSOR_REGISTER_MAP.items():
            address = int(cfg["address"])

            try:
                if register_type == "input":
                    response = client.read_input_registers(address=address, count=1, unit=unit)
                else:
                    response = client.read_holding_registers(address=address, count=1, unit=unit)

                if not response or response.isError():
                    logger.warning("Modbus read failed for %s at address %s", key, address)
                    return None

                raw = int(response.registers[0])
                result[key] = self._decode_register(
                    raw_value=raw,
                    signed=bool(cfg.get("signed", False)),
                    scale=float(cfg.get("scale", 1.0)),
                    offset=float(cfg.get("offset", 0.0)),
                )
            except Exception as e:
                logger.warning("Modbus exception for %s (addr %s): %s", key, address, e)
                return None

        return result

    def _fallback_sample(self, now: float) -> dict:
        """Generate smooth fallback values for development/testing."""
        hot = 185.0 + 12.0 * math.sin(now / 14.0)
        cold = 92.0 + 8.0 * math.sin(now / 18.0 + 0.9)
        exhaust = 145.0 + 10.0 * math.sin(now / 16.0 + 1.8)

        return {
            "hot_zone_temperature": round(hot, 1),
            "cold_zone_temperature": round(cold, 1),
            "exhaust_temp": round(exhaust, 1),
            "timestamp": datetime.now().isoformat(),
            "source": "fallback",
        }

    def _sample_once(self) -> dict:
        now = time.time()
        logger_data = self._read_from_datalogger()

        if logger_data is not None:
            sample = {
                "hot_zone_temperature": float(logger_data.get("hot_zone_temperature", 0.0)),
                "cold_zone_temperature": float(logger_data.get("cold_zone_temperature", 0.0)),
                "exhaust_temp": float(logger_data.get("exhaust_temp", 0.0)),
                "timestamp": datetime.now().isoformat(),
                "source": "modbus",
            }
        else:
            sample = self._fallback_sample(now)

        self._history.append(sample)
        self._last_sample_ts = now
        return sample

    def _ensure_recent_sample(self):
        now = time.time()
        if not self._history or (now - self._last_sample_ts) >= self._sample_interval_seconds:
            self._sample_once()

    def get_latest(self) -> dict:
        self._ensure_recent_sample()
        return self._history[-1]

    def get_history(self, limit: int = 120, interval_minutes: int = 1, hours: int = 24):
        self._ensure_recent_sample()

        safe_limit = max(1, min(int(limit), 5000))
        safe_interval_minutes = max(1, min(int(interval_minutes), 240))
        safe_hours = max(1, min(int(hours), 168))

        cutoff = datetime.now() - timedelta(hours=safe_hours)

        filtered = []
        for sample in self._history:
            try:
                ts = datetime.fromisoformat(sample["timestamp"])
            except Exception:
                continue
            if ts >= cutoff:
                filtered.append(sample)

        if not filtered:
            return []

        bucket_seconds = safe_interval_minutes * 60
        bucketed = {}
        for sample in filtered:
            try:
                ts = datetime.fromisoformat(sample["timestamp"])
                bucket_key = int(ts.timestamp()) // bucket_seconds
                bucketed[bucket_key] = sample  # keep latest sample in bucket
            except Exception:
                continue

        history = [bucketed[key] for key in sorted(bucketed.keys())]
        return history[-safe_limit:]


sensor_data_service = None


def get_sensor_data_service() -> SensorDataService:
    global sensor_data_service
    if sensor_data_service is None:
        sensor_data_service = SensorDataService()
    return sensor_data_service

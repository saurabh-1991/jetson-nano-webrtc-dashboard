"""Sensor data service backed by Modbus RTU (RS-485) with fallback simulation."""

import logging
import math
import os
import struct
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from .modbus_sensor_config import FLOW_METER_CONFIG, MODBUS_CONFIG, SENSOR_REGISTER_MAP

logger = logging.getLogger(__name__)

try:
    from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient
    MODBUS_LIB_AVAILABLE = True
except Exception:
    ModbusSerialClient = None
    ModbusTcpClient = None
    MODBUS_LIB_AVAILABLE = False


class SensorDataService:
    """Maintain latest and recent sensor samples for UI display and graphing."""

    def __init__(self):
        self._history = deque(maxlen=86400)  # up to ~48h at 2s sampling
        self._last_sample_ts = 0.0
        self._sample_interval_seconds = 2.0
        self._modbus_failure_backoff_seconds = max(
            0.5, float(os.getenv("MODBUS_FAILURE_BACKOFF_SECONDS", "5.0"))
        )
        self._next_modbus_attempt_ts = 0.0
        self._sample_lock = threading.Lock()
        self._client = None
        self._flow_client = None
        self._modbus_transport = str(MODBUS_CONFIG.get("transport", "serial") or "serial").strip().lower()
        self._flow_transport = str(FLOW_METER_CONFIG.get("transport", "tcp") or "tcp").strip().lower()
        self._last_modbus_cycle_debug = []
        self._simulation_enabled = os.getenv("SENSOR_SIMULATION_ENABLED", "false").lower() in (
            "1", "true", "yes", "on"
        )
        self._sensor_debug_log_enabled = os.getenv("SENSOR_DEBUG_LOG_RAW", "false").lower() in (
            "1", "true", "yes", "on"
        )
        self._sensor_debug_log_interval_seconds = max(
            0.0, float(os.getenv("SENSOR_DEBUG_LOG_INTERVAL_SECONDS", "8.0"))
        )
        self._sensor_debug_log_only_on_change = os.getenv(
            "SENSOR_DEBUG_LOG_ONLY_ON_CHANGE", "true"
        ).lower() in ("1", "true", "yes", "on")
        self._last_sensor_debug_log_ts = 0.0
        self._last_sensor_debug_signature = None
        self._modbus_enabled = MODBUS_CONFIG.get("enabled", True) and MODBUS_LIB_AVAILABLE
        self._flow_meter_enabled = FLOW_METER_CONFIG.get("enabled", False) and MODBUS_LIB_AVAILABLE
        self._flow_failure_backoff_seconds = max(
            0.5,
            float(FLOW_METER_CONFIG.get("failure_backoff_seconds", 5.0)),
        )
        self._next_flow_attempt_ts = 0.0

        if self._modbus_transport == "tcp" and not str(MODBUS_CONFIG.get("host") or "").strip():
            logger.warning("MODBUS_TRANSPORT=tcp but MODBUS_HOST is empty; sensor reads will be unavailable")

        if self._flow_meter_enabled and self._flow_transport == "tcp" and not str(FLOW_METER_CONFIG.get("host") or "").strip():
            logger.warning("FLOW_METER_TRANSPORT=tcp but FLOW_METER_HOST is empty; flow readings will be unavailable")

        if MODBUS_CONFIG.get("enabled", True) and not MODBUS_LIB_AVAILABLE:
            logger.warning("pymodbus not available; sensor service will use fallback generator")

    def _build_modbus_client(self, transport: str, cfg: dict):
        mode = str(transport or "serial").strip().lower()
        if mode == "tcp":
            host = str(cfg.get("host") or "").strip()
            if not host:
                return None
            return ModbusTcpClient(
                host=host,
                port=int(cfg.get("tcp_port", 502)),
                timeout=cfg.get("timeout", 0.8),
            )

        return ModbusSerialClient(
            method="rtu",
            port=cfg.get("port"),
            baudrate=cfg.get("baudrate", 9600),
            bytesize=cfg.get("bytesize", 8),
            parity=cfg.get("parity", "N"),
            stopbits=cfg.get("stopbits", 1),
            timeout=cfg.get("timeout", 0.8),
        )

    def _ensure_client(self):
        """Create/connect primary datalogger client if not active."""
        if not self._modbus_enabled:
            return None

        if self._client is None:
            self._client = self._build_modbus_client(self._modbus_transport, MODBUS_CONFIG)
            if self._client is None:
                return None

        try:
            if not self._client.connect():
                endpoint = MODBUS_CONFIG.get("port")
                if self._modbus_transport == "tcp":
                    endpoint = "{0}:{1}".format(MODBUS_CONFIG.get("host"), MODBUS_CONFIG.get("tcp_port"))
                logger.warning("Modbus connect failed (%s) on %s", self._modbus_transport, endpoint)
                return None
        except Exception as e:
            logger.warning("Modbus client connect error: %s", e)
            return None

        return self._client

    def _ensure_flow_client(self):
        """Create/connect flow meter client if enabled and configured."""
        if not self._flow_meter_enabled:
            return None

        if self._flow_client is None:
            self._flow_client = self._build_modbus_client(self._flow_transport, FLOW_METER_CONFIG)
            if self._flow_client is None:
                return None

        try:
            if not self._flow_client.connect():
                endpoint = FLOW_METER_CONFIG.get("port")
                if self._flow_transport == "tcp":
                    endpoint = "{0}:{1}".format(FLOW_METER_CONFIG.get("host"), FLOW_METER_CONFIG.get("tcp_port"))
                logger.warning("Flow meter connect failed (%s) on %s", self._flow_transport, endpoint)
                return None
        except Exception as e:
            logger.warning("Flow meter client connect error: %s", e)
            return None

        return self._flow_client

    @staticmethod
    def _decode_register(
        raw_value: int,
        signed: bool,
        scale: float,
        offset: float,
        precision: int = 2,
    ) -> float:
        value = int(raw_value)
        if signed and value >= 32768:
            value = value - 65536

        return round((value * scale) + offset, max(0, min(int(precision), 6)))

    @staticmethod
    def _status_text(status_code: int) -> str:
        status_map = {
            0: "in_range",
            1: "under_range",
            2: "over_range",
            3: "open",
        }
        return status_map.get(int(status_code), "unknown")

    @staticmethod
    def _decimal_scale(decimal_pos: int):
        pos = int(decimal_pos)
        if pos < 0 or pos > 4:
            return None
        return 10 ** (-pos)

    @staticmethod
    def _safe_float(value):
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _resolve_register_address(configured_address: int, address_base: int, address_offset: int) -> int:
        return int(configured_address) - int(address_base) + int(address_offset)

    @staticmethod
    def _read_single_register(client, register_type: str, address: int, unit: int):
        if register_type == "input":
            response = client.read_input_registers(address=address, count=1, unit=unit)
        else:
            response = client.read_holding_registers(address=address, count=1, unit=unit)

        if not response or response.isError():
            return None

        return int(response.registers[0])

    @staticmethod
    def _read_register_block(client, register_type: str, address: int, count: int, unit: int):
        if register_type == "input":
            response = client.read_input_registers(address=address, count=count, unit=unit)
        else:
            response = client.read_holding_registers(address=address, count=count, unit=unit)

        if not response or response.isError():
            return None

        registers = list(response.registers or [])
        if len(registers) < int(count):
            return None
        return [int(v) & 0xFFFF for v in registers]

    @staticmethod
    def _decode_float32(registers, word_order: str = "ab", byte_order: str = "big"):
        if not registers or len(registers) < 2:
            return None

        r1 = int(registers[0]) & 0xFFFF
        r2 = int(registers[1]) & 0xFFFF

        mode = str(word_order or "ab").strip().lower()
        if mode == "ba":
            words = (r2, r1)
        elif mode == "byte_swap":
            words = ((((r1 & 0xFF) << 8) | (r1 >> 8)), (((r2 & 0xFF) << 8) | (r2 >> 8)))
        elif mode == "both_swap":
            words = ((((r2 & 0xFF) << 8) | (r2 >> 8)), (((r1 & 0xFF) << 8) | (r1 >> 8)))
        else:
            words = (r1, r2)

        byte_mode = str(byte_order or "big").strip().lower()
        pack_fmt = "<HH" if byte_mode == "little" else ">HH"
        unpack_fmt = "<f" if byte_mode == "little" else ">f"
        return float(struct.unpack(unpack_fmt, struct.pack(pack_fmt, words[0], words[1]))[0])

    @staticmethod
    def _to_log_number(value):
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return value

    def _sensor_debug_signature(self, sample: dict, modbus_debug_rows):
        row_sig = []
        for row in modbus_debug_rows or []:
            row_sig.append(
                (
                    row.get("key"),
                    row.get("value_raw"),
                    row.get("decimal_raw"),
                    row.get("status_raw"),
                    row.get("decoded"),
                    row.get("final"),
                )
            )

        return (
            sample.get("source"),
            sample.get("hot_zone_temperature"),
            sample.get("cold_zone_temperature"),
            sample.get("exhaust_temp"),
            sample.get("flow_rate"),
            sample.get("flow_velocity"),
            sample.get("hot_zone_status"),
            sample.get("cold_zone_status"),
            sample.get("exhaust_status"),
            sample.get("flow_status"),
            sample.get("flow_velocity_status"),
            tuple(row_sig),
        )

    def _log_sensor_debug_if_needed(self, now: float, sample: dict, modbus_debug_rows):
        if not self._sensor_debug_log_enabled:
            return

        signature = self._sensor_debug_signature(sample, modbus_debug_rows)
        changed = signature != self._last_sensor_debug_signature
        interval_elapsed = (now - self._last_sensor_debug_log_ts) >= self._sensor_debug_log_interval_seconds

        should_log = interval_elapsed
        if self._sensor_debug_log_only_on_change and changed:
            should_log = True

        if not should_log:
            return

        self._last_sensor_debug_log_ts = now
        self._last_sensor_debug_signature = signature

        logger.info(
            "Sensor debug | source=%s | hot=%s(%s) cold=%s(%s) exhaust=%s(%s) flow=%s(%s) velocity=%s(%s)",
            sample.get("source"),
            sample.get("hot_zone_temperature"),
            sample.get("hot_zone_status"),
            sample.get("cold_zone_temperature"),
            sample.get("cold_zone_status"),
            sample.get("exhaust_temp"),
            sample.get("exhaust_status"),
            sample.get("flow_rate"),
            sample.get("flow_status"),
            sample.get("flow_velocity"),
            sample.get("flow_velocity_status"),
        )

        if modbus_debug_rows:
            for row in modbus_debug_rows:
                logger.info(
                    "Sensor raw | key=%s reg_type=%s value_addr=%s raw=%s decimal_addr=%s decimal=%s status_addr=%s status_raw=%s status=%s scale=%s decoded=%s final=%s",
                    row.get("key"),
                    row.get("register_type"),
                    row.get("value_address"),
                    row.get("value_raw"),
                    row.get("decimal_address"),
                    row.get("decimal_raw"),
                    row.get("status_address"),
                    row.get("status_raw"),
                    row.get("status_text"),
                    row.get("scale"),
                    row.get("decoded"),
                    row.get("final"),
                )

    def _read_from_datalogger(self):
        """Read configured sensor registers from Modbus datalogger."""
        client = self._ensure_client()
        if client is None:
            self._last_modbus_cycle_debug = []
            return None

        unit = MODBUS_CONFIG["slave_id"]
        default_register_type = MODBUS_CONFIG.get("register_type", "holding").lower()
        address_base = int(MODBUS_CONFIG.get("address_base", 0) or 0)
        address_offset = int(MODBUS_CONFIG.get("address_offset", 0) or 0)

        result = {}
        debug_rows = []

        for key, cfg in SENSOR_REGISTER_MAP.items():
            if not bool(cfg.get("enabled", True)):
                continue

            required = bool(cfg.get("required", True))
            value_address_configured = int(cfg.get("value_address", cfg.get("address")))
            decimal_address_configured = cfg.get("decimal_address")
            status_address_configured = cfg.get("status_address")

            value_address = self._resolve_register_address(
                value_address_configured,
                address_base,
                address_offset,
            )

            decimal_address = None
            if decimal_address_configured is not None:
                decimal_address = self._resolve_register_address(
                    int(decimal_address_configured),
                    address_base,
                    address_offset,
                )

            status_address = None
            if status_address_configured is not None:
                status_address = self._resolve_register_address(
                    int(status_address_configured),
                    address_base,
                    address_offset,
                )

            register_type = (cfg.get("register_type") or default_register_type or "holding").lower()

            if value_address < 0 or (decimal_address is not None and decimal_address < 0) or (status_address is not None and status_address < 0):
                logger.warning(
                    "Computed Modbus address for %s is negative (value=%s, decimal=%s, status=%s, base=%s, offset=%s)",
                    key,
                    value_address,
                    decimal_address,
                    status_address,
                    address_base,
                    address_offset,
                )
                if required:
                    return None
                result[key] = None
                result["%s_status" % key] = "misconfigured"
                debug_rows.append(
                    {
                        "key": key,
                        "register_type": register_type,
                        "value_address": value_address,
                        "value_raw": None,
                        "decimal_address": decimal_address,
                        "decimal_raw": None,
                        "status_address": status_address,
                        "status_raw": None,
                        "status_text": "misconfigured",
                        "scale": None,
                        "decoded": None,
                        "final": None,
                    }
                )
                continue

            try:
                raw_value = self._read_single_register(client, register_type, value_address, unit)
                if raw_value is None:
                    logger.warning("Modbus read failed for %s value at address %s", key, value_address)
                    if required:
                        self._last_modbus_cycle_debug = debug_rows
                        return None
                    result[key] = None
                    result["%s_status" % key] = "unavailable"
                    debug_rows.append(
                        {
                            "key": key,
                            "register_type": register_type,
                            "value_address": value_address,
                            "value_raw": None,
                            "decimal_address": decimal_address,
                            "decimal_raw": None,
                            "status_address": status_address,
                            "status_raw": None,
                            "status_text": "unavailable",
                            "scale": None,
                            "decoded": None,
                            "final": None,
                        }
                    )
                    continue

                decimal_pos = None
                if decimal_address is not None:
                    decimal_pos = self._read_single_register(client, register_type, decimal_address, unit)
                    if decimal_pos is None:
                        logger.warning("Modbus read failed for %s decimal position at address %s", key, decimal_address)
                        if required:
                            self._last_modbus_cycle_debug = debug_rows
                            return None
                        result[key] = None
                        result["%s_status" % key] = "unavailable"
                        continue

                status_code = 0
                if status_address is not None:
                    status_raw = self._read_single_register(client, register_type, status_address, unit)
                    if status_raw is None:
                        logger.warning("Modbus read failed for %s status at address %s", key, status_address)
                        if required:
                            self._last_modbus_cycle_debug = debug_rows
                            return None
                        result[key] = None
                        result["%s_status" % key] = "unavailable"
                        continue
                    status_code = int(status_raw)

                status_text = self._status_text(status_code)
                result["%s_status" % key] = status_text

                # According to Smart Log-04 map: only status=0 means valid in-range value.
                if status_code != 0:
                    result[key] = None
                    debug_rows.append(
                        {
                            "key": key,
                            "register_type": register_type,
                            "value_address": value_address,
                            "value_raw": raw_value,
                            "decimal_address": decimal_address,
                            "decimal_raw": decimal_pos,
                            "status_address": status_address,
                            "status_raw": status_code,
                            "status_text": status_text,
                            "scale": None,
                            "decoded": None,
                            "final": None,
                        }
                    )
                    continue

                scale = float(cfg.get("scale", 1.0))
                precision = int(cfg.get("precision", 2))

                if decimal_pos is not None:
                    derived_scale = self._decimal_scale(decimal_pos)
                    if derived_scale is None:
                        logger.warning(
                            "Invalid decimal position %s for %s; using configured scale %s",
                            decimal_pos,
                            key,
                            scale,
                        )
                    else:
                        scale = float(derived_scale)
                        precision = int(decimal_pos)

                decoded = self._decode_register(
                    raw_value=raw_value,
                    signed=bool(cfg.get("signed", False)),
                    scale=scale,
                    offset=float(cfg.get("offset", 0.0)),
                    precision=precision,
                )

                min_value = cfg.get("min_value", -19999)
                max_value = cfg.get("max_value", 19999)
                if decoded < float(min_value) or decoded > float(max_value):
                    logger.warning(
                        "Decoded value out of expected range for %s: %s (min=%s, max=%s)",
                        key,
                        decoded,
                        min_value,
                        max_value,
                    )

                result[key] = decoded
                debug_rows.append(
                    {
                        "key": key,
                        "register_type": register_type,
                        "value_address": value_address,
                        "value_raw": raw_value,
                        "decimal_address": decimal_address,
                        "decimal_raw": decimal_pos,
                        "status_address": status_address,
                        "status_raw": status_code,
                        "status_text": status_text,
                        "scale": scale,
                        "decoded": self._to_log_number(decoded),
                        "final": self._to_log_number(result.get(key)),
                    }
                )
            except Exception as e:
                logger.warning("Modbus exception for %s: %s", key, e)
                if required:
                    self._last_modbus_cycle_debug = debug_rows
                    return None
                result[key] = None
                result["%s_status" % key] = "unavailable"
                continue

        self._last_modbus_cycle_debug = debug_rows
        return result

    def _read_from_flow_meter(self):
        """Read flow_rate from separate flow meter Modbus device."""
        client = self._ensure_flow_client()
        if client is None:
            return None

        cfg = FLOW_METER_CONFIG
        unit = int(cfg.get("slave_id", 1))
        register_type = str(cfg.get("register_type", "holding") or "holding").strip().lower()
        address_base = int(cfg.get("address_base", 0) or 0)
        address_offset = int(cfg.get("address_offset", 0) or 0)

        value_address = self._resolve_register_address(int(cfg.get("value_address", 0)), address_base, address_offset)
        value_register_count = max(1, int(cfg.get("value_register_count", 1)))
        value_encoding = str(cfg.get("value_encoding", "scaled_int") or "scaled_int").strip().lower()
        word_order = str(cfg.get("word_order", "ab") or "ab").strip().lower()
        byte_order = str(cfg.get("byte_order", "big") or "big").strip().lower()

        velocity_address_cfg = cfg.get("velocity_address")
        velocity_address = (
            self._resolve_register_address(int(velocity_address_cfg), address_base, address_offset)
            if velocity_address_cfg is not None
            else None
        )
        velocity_register_count = max(1, int(cfg.get("velocity_register_count", 2)))
        decimal_address_cfg = cfg.get("decimal_address")
        status_address_cfg = cfg.get("status_address")
        decimal_address = (
            self._resolve_register_address(int(decimal_address_cfg), address_base, address_offset)
            if decimal_address_cfg is not None
            else None
        )
        status_address = (
            self._resolve_register_address(int(status_address_cfg), address_base, address_offset)
            if status_address_cfg is not None
            else None
        )

        if (
            value_address < 0
            or (velocity_address is not None and velocity_address < 0)
            or (decimal_address is not None and decimal_address < 0)
            or (status_address is not None and status_address < 0)
        ):
            logger.warning(
                "Flow meter register config invalid (value=%s velocity=%s decimal=%s status=%s)",
                value_address,
                velocity_address,
                decimal_address,
                status_address,
            )
            return None

        try:
            value_registers = self._read_register_block(
                client,
                register_type,
                value_address,
                value_register_count,
                unit,
            )
            if value_registers is None:
                return None

            decimal_pos = None
            if decimal_address is not None:
                decimal_pos = self._read_single_register(client, register_type, decimal_address, unit)
                if decimal_pos is None:
                    return None

            status_code = 0
            if status_address is not None:
                status_raw = self._read_single_register(client, register_type, status_address, unit)
                if status_raw is None:
                    return None
                status_code = int(status_raw)

            status_text = self._status_text(status_code)
            if status_code != 0:
                return {
                    "flow_rate": None,
                    "flow_status": status_text,
                    "flow_velocity": None,
                    "flow_velocity_status": status_text,
                }

            if value_encoding == "float32":
                decoded = self._decode_float32(value_registers, word_order=word_order, byte_order=byte_order)
                if decoded is None:
                    return None
                decoded = round(decoded, 4)
            else:
                scale = float(cfg.get("scale", 1.0))
                precision = 2
                if decimal_pos is not None:
                    derived_scale = self._decimal_scale(decimal_pos)
                    if derived_scale is not None:
                        scale = float(derived_scale)
                        precision = int(decimal_pos)

                decoded = self._decode_register(
                    raw_value=int(value_registers[0]),
                    signed=bool(cfg.get("signed", False)),
                    scale=scale,
                    offset=float(cfg.get("offset", 0.0)),
                    precision=precision,
                )

            min_value = float(cfg.get("min_value", 0.0))
            max_value = float(cfg.get("max_value", 99999.0))
            if decoded < min_value or decoded > max_value:
                logger.warning(
                    "Flow meter decoded value out of range: %s (min=%s, max=%s)",
                    decoded,
                    min_value,
                    max_value,
                )

            velocity_value = None
            velocity_status = status_text
            if velocity_address is not None:
                velocity_registers = self._read_register_block(
                    client,
                    register_type,
                    velocity_address,
                    velocity_register_count,
                    unit,
                )
                if velocity_registers is not None:
                    if value_encoding == "float32":
                        velocity_value = self._decode_float32(
                            velocity_registers,
                            word_order=word_order,
                            byte_order=byte_order,
                        )
                        if velocity_value is not None:
                            velocity_value = round(float(velocity_value), 4)
                    else:
                        velocity_value = self._decode_register(
                            raw_value=int(velocity_registers[0]),
                            signed=bool(cfg.get("signed", False)),
                            scale=float(cfg.get("velocity_scale", cfg.get("scale", 1.0))),
                            offset=float(cfg.get("velocity_offset", 0.0)),
                            precision=2,
                        )

                    if velocity_value is not None:
                        vel_min = float(cfg.get("velocity_min_value", -99999.0))
                        vel_max = float(cfg.get("velocity_max_value", 99999.0))
                        if velocity_value < vel_min or velocity_value > vel_max:
                            logger.warning(
                                "Flow meter velocity out of range: %s (min=%s, max=%s)",
                                velocity_value,
                                vel_min,
                                vel_max,
                            )

            return {
                "flow_rate": decoded,
                "flow_status": status_text,
                "flow_velocity": velocity_value,
                "flow_velocity_status": velocity_status if velocity_value is not None else "unavailable",
            }
        except Exception as e:
            logger.warning("Flow meter Modbus exception: %s", e)
            return None

    def _fallback_sample(self, now: float) -> dict:
        """Generate smooth fallback values for development/testing."""
        hot = 185.0 + 12.0 * math.sin(now / 14.0)
        cold = 92.0 + 8.0 * math.sin(now / 18.0 + 0.9)
        exhaust = 145.0 + 10.0 * math.sin(now / 16.0 + 1.8)

        return {
            "hot_zone_temperature": round(hot, 1),
            "cold_zone_temperature": round(cold, 1),
            "exhaust_temp": round(exhaust, 1),
            "flow_rate": round(11.5 + 1.8 * math.sin(now / 12.0 + 0.6), 2),
            "flow_velocity": round(9.0 + 0.8 * math.sin(now / 10.0 + 0.25), 3),
            "flow_status": "in_range",
            "flow_velocity_status": "in_range",
            "timestamp": datetime.now().isoformat(),
            "source": "fallback",
        }

    def _sample_once(self) -> dict:
        now = time.time()
        logger_data = None
        flow_data = None
        if not self._simulation_enabled:
            if now >= self._next_modbus_attempt_ts:
                logger_data = self._read_from_datalogger()
                if logger_data is None:
                    self._next_modbus_attempt_ts = now + self._modbus_failure_backoff_seconds
            else:
                logger_data = None

            if self._flow_meter_enabled:
                if now >= self._next_flow_attempt_ts:
                    flow_data = self._read_from_flow_meter()
                    if flow_data is None:
                        self._next_flow_attempt_ts = now + self._flow_failure_backoff_seconds
                else:
                    flow_data = None

        if self._simulation_enabled:
            sample = self._fallback_sample(now)
            sample["source"] = "simulation"
        elif logger_data is not None or flow_data is not None:
            hot_status = logger_data.get("hot_zone_temperature_status", "unknown") if logger_data is not None else "unavailable"
            cold_status = logger_data.get("cold_zone_temperature_status", "unknown") if logger_data is not None else "unavailable"
            exhaust_status = logger_data.get("exhaust_temp_status", "unknown") if logger_data is not None else "unavailable"

            flow_value = None
            flow_velocity_value = None
            flow_status = "disabled" if not self._flow_meter_enabled else "unavailable"
            flow_velocity_status = "disabled" if not self._flow_meter_enabled else "unavailable"
            if flow_data is not None:
                flow_value = self._safe_float(flow_data.get("flow_rate"))
                flow_status = flow_data.get("flow_status", "unknown")
                flow_velocity_value = self._safe_float(flow_data.get("flow_velocity"))
                flow_velocity_status = flow_data.get("flow_velocity_status", "unknown")

            has_logger = logger_data is not None
            has_flow = flow_data is not None
            if has_logger and has_flow:
                source = "modbus"
            elif has_logger:
                source = "modbus_partial"
            else:
                source = "flow_only_modbus"

            sample = {
                "hot_zone_temperature": self._safe_float(logger_data.get("hot_zone_temperature")) if logger_data is not None else None,
                "cold_zone_temperature": self._safe_float(logger_data.get("cold_zone_temperature")) if logger_data is not None else None,
                "exhaust_temp": self._safe_float(logger_data.get("exhaust_temp")) if logger_data is not None else None,
                "flow_rate": flow_value,
                "flow_velocity": flow_velocity_value,
                "hot_zone_status": hot_status,
                "cold_zone_status": cold_status,
                "exhaust_status": exhaust_status,
                "flow_status": flow_status,
                "flow_velocity_status": flow_velocity_status,
                "timestamp": datetime.now().isoformat(),
                "source": source,
            }
        else:
            sample = {
                "hot_zone_temperature": None,
                "cold_zone_temperature": None,
                "exhaust_temp": None,
                "flow_rate": None,
                "flow_velocity": None,
                "hot_zone_status": "unavailable",
                "cold_zone_status": "unavailable",
                "exhaust_status": "unavailable",
                "flow_status": "disabled" if not self._flow_meter_enabled else "unavailable",
                "flow_velocity_status": "disabled" if not self._flow_meter_enabled else "unavailable",
                "timestamp": datetime.now().isoformat(),
                "source": "modbus_unavailable",
            }

        self._log_sensor_debug_if_needed(now, sample, self._last_modbus_cycle_debug)

        self._history.append(sample)
        self._last_sample_ts = now
        return sample

    def set_simulation_enabled(self, enabled: bool):
        self._simulation_enabled = bool(enabled)

    def is_simulation_enabled(self) -> bool:
        return bool(self._simulation_enabled)

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None

        # Python 3.7+ fast path
        if hasattr(datetime, "fromisoformat"):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                pass

        # Python 3.6 fallback
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue

        return None

    def _ensure_recent_sample(self):
        now = time.time()
        should_sample = (not self._history) or ((now - self._last_sample_ts) >= self._sample_interval_seconds)
        if not should_sample:
            return

        if self._sample_lock.acquire(False):
            try:
                current = time.time()
                if not self._history or (current - self._last_sample_ts) >= self._sample_interval_seconds:
                    self._sample_once()
            finally:
                self._sample_lock.release()
            return

        # Sampling already in progress in another request/thread.
        # Keep serving previous value to avoid cascading latency.
        if not self._history:
            self._history.append(
                {
                    "hot_zone_temperature": None,
                    "cold_zone_temperature": None,
                    "exhaust_temp": None,
                    "flow_rate": None,
                    "flow_velocity": None,
                    "hot_zone_status": "sampling_in_progress",
                    "cold_zone_status": "sampling_in_progress",
                    "exhaust_status": "sampling_in_progress",
                    "flow_status": "sampling_in_progress",
                    "flow_velocity_status": "sampling_in_progress",
                    "timestamp": datetime.now().isoformat(),
                    "source": "sampling_in_progress",
                }
            )

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
            ts = self._parse_timestamp(sample.get("timestamp"))
            if ts is None:
                continue
            if ts >= cutoff:
                filtered.append(sample)

        if not filtered:
            return []

        bucket_seconds = safe_interval_minutes * 60
        bucketed = {}
        for sample in filtered:
            ts = self._parse_timestamp(sample.get("timestamp"))
            if ts is None:
                continue
            bucket_key = int(ts.timestamp()) // bucket_seconds
            bucketed[bucket_key] = sample  # keep latest sample in bucket

        history = [bucketed[key] for key in sorted(bucketed.keys())]
        return history[-safe_limit:]


sensor_data_service = None


def get_sensor_data_service() -> SensorDataService:
    global sensor_data_service
    if sensor_data_service is None:
        sensor_data_service = SensorDataService()
    return sensor_data_service

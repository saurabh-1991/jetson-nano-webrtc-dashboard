"""Modbus RTU (RS-485) sensor configuration.

Smart Log-04 default map (from datasheet snippet):
    CH1: value=0010, decimal=0011, status=0012
    CH2: value=0013, decimal=0014, status=0015
    CH3: value=0016, decimal=0017, status=0018
    CH4: value=0019, decimal=0020, status=0021

In this project default wiring/mapping is:
    CH1 -> hot_zone_temperature
    CH2 -> cold_zone_temperature
    CH3 -> exhaust_temp
    CH4 -> spare / not used in UI

Flow meter is modeled as a separate device endpoint (not CH4) and has its own
transport + register settings under FLOW_METER_CONFIG below.

Field tuning notes:
1) If logger manual shows addresses like 30001 / 40001, set MODBUS_ADDRESS_BASE
    (for example 30001 or 40001) and keep per-channel addresses as shown in manual.
2) If values look 10x/100x off, check decimal position register usage and/or scale.
3) If a channel always reports None, inspect status register:
      0=in_range, 1=under_range, 2=over_range, 3=open.
4) If channels are physically wired differently on site, remap by changing only the
    *_VALUE / *_DECIMAL / *_STATUS env vars in .env (no code change required).
"""

import os


def _to_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


def _to_int(name: str, default: str) -> int:
    value = os.getenv(name, default).strip()
    # Allow decimal and prefixed values (e.g. 0x12)
    return int(value, 0)


MODBUS_CONFIG = {
    "enabled": _to_bool("MODBUS_ENABLED", "true"),
    "transport": os.getenv("MODBUS_TRANSPORT", "serial").strip().lower(),  # serial | tcp
    "port": os.getenv("MODBUS_PORT", "/dev/ttyUSB0"),
    "host": os.getenv("MODBUS_HOST", "").strip(),
    "tcp_port": _to_int("MODBUS_TCP_PORT", "502"),
    "slave_id": _to_int("MODBUS_SLAVE_ID", "1"),
    "baudrate": _to_int("MODBUS_BAUDRATE", "9600"),
    "bytesize": _to_int("MODBUS_BYTESIZE", "8"),
    "parity": os.getenv("MODBUS_PARITY", "N"),  # N, E, O
    "stopbits": _to_int("MODBUS_STOPBITS", "1"),
    "timeout": float(os.getenv("MODBUS_TIMEOUT", "0.8")),
    "register_type": os.getenv("MODBUS_REGISTER_TYPE", "holding"),  # holding or input
    # Many datasheets publish logical addresses (30001/40001). Use base/offset to map them
    # to 0-based Modbus wire addresses required by pymodbus.
    "address_base": _to_int("MODBUS_ADDRESS_BASE", "0"),
    "address_offset": _to_int("MODBUS_ADDRESS_OFFSET", "0"),
}

# Address map: update these register addresses to match your datalogger
SENSOR_REGISTER_MAP = {
    "hot_zone_temperature": {
        "label": "Hot Zone Temperature",
        "enabled": _to_bool("MODBUS_SENSOR_HOT_ZONE_ENABLED", "true"),
        "required": True,
        # Smart Log-04 CH1
        "value_address": _to_int("MODBUS_ADDR_HOT_ZONE_VALUE", os.getenv("MODBUS_ADDR_HOT_ZONE", "10")),
        "decimal_address": _to_int("MODBUS_ADDR_HOT_ZONE_DECIMAL", "11"),
        "status_address": _to_int("MODBUS_ADDR_HOT_ZONE_STATUS", "12"),
        "register_type": os.getenv("MODBUS_TYPE_HOT_ZONE", "").strip().lower(),
        "scale": float(os.getenv("MODBUS_SCALE_HOT_ZONE", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_HOT_ZONE", "0.0")),
        "signed": _to_bool("MODBUS_SIGNED_HOT_ZONE", "true"),
    },
    "cold_zone_temperature": {
        "label": "Cold Zone Temperature",
        "enabled": _to_bool("MODBUS_SENSOR_COLD_ZONE_ENABLED", "true"),
        "required": True,
        # Smart Log-04 CH2
        "value_address": _to_int("MODBUS_ADDR_COLD_ZONE_VALUE", os.getenv("MODBUS_ADDR_COLD_ZONE", "13")),
        "decimal_address": _to_int("MODBUS_ADDR_COLD_ZONE_DECIMAL", "14"),
        "status_address": _to_int("MODBUS_ADDR_COLD_ZONE_STATUS", "15"),
        "register_type": os.getenv("MODBUS_TYPE_COLD_ZONE", "").strip().lower(),
        "scale": float(os.getenv("MODBUS_SCALE_COLD_ZONE", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_COLD_ZONE", "0.0")),
        "signed": _to_bool("MODBUS_SIGNED_COLD_ZONE", "true"),
    },
    "exhaust_temp": {
        "label": "Exhaust Temp",
        "enabled": _to_bool("MODBUS_SENSOR_EXHAUST_ENABLED", "true"),
        "required": True,
        # Smart Log-04 CH3
        "value_address": _to_int("MODBUS_ADDR_EXHAUST_VALUE", os.getenv("MODBUS_ADDR_EXHAUST", "16")),
        "decimal_address": _to_int("MODBUS_ADDR_EXHAUST_DECIMAL", "17"),
        "status_address": _to_int("MODBUS_ADDR_EXHAUST_STATUS", "18"),
        "register_type": os.getenv("MODBUS_TYPE_EXHAUST", "").strip().lower(),
        "scale": float(os.getenv("MODBUS_SCALE_EXHAUST", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_EXHAUST", "0.0")),
        "signed": _to_bool("MODBUS_SIGNED_EXHAUST", "true"),
    },
}

if MODBUS_CONFIG.get("transport") not in ("serial", "tcp"):
    MODBUS_CONFIG["transport"] = "serial"


FLOW_METER_CONFIG = {
    "enabled": _to_bool("FLOW_METER_ENABLED", "false"),
    "transport": os.getenv("FLOW_METER_TRANSPORT", "tcp").strip().lower(),  # serial | tcp
    "port": os.getenv("FLOW_METER_PORT", "/dev/ttyUSB1"),
    "host": os.getenv("FLOW_METER_HOST", "").strip(),
    "tcp_port": _to_int("FLOW_METER_TCP_PORT", "502"),
    "slave_id": _to_int("FLOW_METER_SLAVE_ID", "1"),
    "baudrate": _to_int("FLOW_METER_BAUDRATE", "9600"),
    "bytesize": _to_int("FLOW_METER_BYTESIZE", "8"),
    "parity": os.getenv("FLOW_METER_PARITY", "N"),
    "stopbits": _to_int("FLOW_METER_STOPBITS", "1"),
    "timeout": float(os.getenv("FLOW_METER_TIMEOUT", "0.8")),
    "register_type": os.getenv("FLOW_METER_REGISTER_TYPE", "holding").strip().lower(),
    "address_base": _to_int("FLOW_METER_ADDRESS_BASE", "0"),
    "address_offset": _to_int("FLOW_METER_ADDRESS_OFFSET", "0"),
    "value_address": _to_int("FLOW_METER_VALUE_ADDRESS", "0"),
    "decimal_address": os.getenv("FLOW_METER_DECIMAL_ADDRESS", "").strip(),
    "status_address": os.getenv("FLOW_METER_STATUS_ADDRESS", "").strip(),
    "scale": float(os.getenv("FLOW_METER_SCALE", "0.1")),
    "offset": float(os.getenv("FLOW_METER_OFFSET", "0.0")),
    "signed": _to_bool("FLOW_METER_SIGNED", "false"),
    "min_value": float(os.getenv("FLOW_METER_MIN_VALUE", "0.0")),
    "max_value": float(os.getenv("FLOW_METER_MAX_VALUE", "99999.0")),
    "failure_backoff_seconds": max(0.5, float(os.getenv("FLOW_METER_FAILURE_BACKOFF_SECONDS", "5.0"))),
}


if FLOW_METER_CONFIG.get("transport") not in ("serial", "tcp"):
    FLOW_METER_CONFIG["transport"] = "tcp"


def _optional_int(raw_value: str):
    text = str(raw_value or "").strip()
    if text == "":
        return None
    return int(text, 0)


FLOW_METER_CONFIG["decimal_address"] = _optional_int(FLOW_METER_CONFIG.get("decimal_address"))
FLOW_METER_CONFIG["status_address"] = _optional_int(FLOW_METER_CONFIG.get("status_address"))

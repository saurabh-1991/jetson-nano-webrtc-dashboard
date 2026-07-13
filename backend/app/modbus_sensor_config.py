"""Modbus RTU (RS-485) sensor configuration.

Update register addresses here (or via env vars) to map datalogger values.
"""

import os


MODBUS_CONFIG = {
    "enabled": os.getenv("MODBUS_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "port": os.getenv("MODBUS_PORT", "/dev/ttyUSB0"),
    "slave_id": int(os.getenv("MODBUS_SLAVE_ID", "1")),
    "baudrate": int(os.getenv("MODBUS_BAUDRATE", "9600")),
    "bytesize": int(os.getenv("MODBUS_BYTESIZE", "8")),
    "parity": os.getenv("MODBUS_PARITY", "N"),  # N, E, O
    "stopbits": int(os.getenv("MODBUS_STOPBITS", "1")),
    "timeout": float(os.getenv("MODBUS_TIMEOUT", "0.8")),
    "register_type": os.getenv("MODBUS_REGISTER_TYPE", "holding"),  # holding or input
}

# Address map: update these register addresses to match your datalogger
SENSOR_REGISTER_MAP = {
    "hot_zone_temperature": {
        "label": "Hot Zone Temperature",
        "address": int(os.getenv("MODBUS_ADDR_HOT_ZONE", "300")),
        "scale": float(os.getenv("MODBUS_SCALE_HOT_ZONE", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_HOT_ZONE", "0.0")),
        "signed": os.getenv("MODBUS_SIGNED_HOT_ZONE", "false").lower() in ("1", "true", "yes", "on"),
    },
    "cold_zone_temperature": {
        "label": "Cold Zone Temperature",
        "address": int(os.getenv("MODBUS_ADDR_COLD_ZONE", "301")),
        "scale": float(os.getenv("MODBUS_SCALE_COLD_ZONE", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_COLD_ZONE", "0.0")),
        "signed": os.getenv("MODBUS_SIGNED_COLD_ZONE", "false").lower() in ("1", "true", "yes", "on"),
    },
    "exhaust_temp": {
        "label": "Exaust Temp",
        "address": int(os.getenv("MODBUS_ADDR_EXHAUST", "302")),
        "scale": float(os.getenv("MODBUS_SCALE_EXHAUST", "0.1")),
        "offset": float(os.getenv("MODBUS_OFFSET_EXHAUST", "0.0")),
        "signed": os.getenv("MODBUS_SIGNED_EXHAUST", "false").lower() in ("1", "true", "yes", "on"),
    },
}

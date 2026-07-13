"""Sensor data service (datalogger-ready with simulated fallback).

This module provides a simple abstraction so future datalogger integration can plug in
without changing API contracts used by the frontend.
"""

import math
import time
from collections import deque
from datetime import datetime


class SensorDataService:
    """Maintain latest and recent sensor samples for UI display and graphing."""

    def __init__(self):
        self._history = deque(maxlen=600)
        self._last_sample_ts = 0.0
        self._sample_interval_seconds = 2.0

    def _read_from_datalogger(self):
        """Placeholder for real datalogger integration.

        Return dict with keys below when datalogger is connected, else None.
        {
            "hot_zone_temperature": float,
            "cold_zone_temperature": float,
            "exhaust_temp": float,
        }
        """
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
            "timestamp": datetime.now().isoformat(),
        }

    def _sample_once(self) -> dict:
        now = time.time()
        logger_data = self._read_from_datalogger()

        if logger_data:
            sample = {
                "hot_zone_temperature": float(logger_data.get("hot_zone_temperature", 0.0)),
                "cold_zone_temperature": float(logger_data.get("cold_zone_temperature", 0.0)),
                "exhaust_temp": float(logger_data.get("exhaust_temp", 0.0)),
                "timestamp": datetime.now().isoformat(),
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

    def get_history(self, limit: int = 120):
        self._ensure_recent_sample()
        safe_limit = max(1, min(int(limit), 600))
        return list(self._history)[-safe_limit:]


sensor_data_service = None


def get_sensor_data_service() -> SensorDataService:
    global sensor_data_service
    if sensor_data_service is None:
        sensor_data_service = SensorDataService()
    return sensor_data_service

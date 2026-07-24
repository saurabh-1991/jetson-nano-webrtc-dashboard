"""Rolling event logger with 2-minute retention and file compaction."""

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class EventLogger:
    """Store recent events in memory and on disk with fixed retention window."""

    def __init__(self):
        self._retention_seconds = max(30, int(os.getenv("EVENT_LOG_RETENTION_SECONDS", "120")))
        self._max_entries = max(200, int(os.getenv("EVENT_LOG_MAX_ENTRIES", "5000")))
        self._file_path = os.getenv("EVENT_LOG_FILE", "/tmp/jetson_dashboard_events.ndjson")
        self._compact_every = max(1, int(os.getenv("EVENT_LOG_COMPACT_EVERY", "25")))

        self._events = deque(maxlen=self._max_entries)
        self._lock = threading.Lock()
        self._writes_since_compact = 0

        self._ensure_parent_dir()

    def _ensure_parent_dir(self):
        try:
            directory = os.path.dirname(self._file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            logger.warning("Failed to ensure event log directory: %s", exc)

    def _now(self) -> float:
        return time.time()

    def _prune_locked(self, now_ts: float):
        cutoff = now_ts - self._retention_seconds
        while self._events and self._events[0].get("ts", 0.0) < cutoff:
            self._events.popleft()

    def _compact_file_locked(self):
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                for event in self._events:
                    f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
            self._writes_since_compact = 0
        except Exception as exc:
            logger.warning("Failed to compact event log file: %s", exc)

    def log_event(self, source: str, event_type: str, severity: str = "info", payload: Dict[str, Any] = None):
        payload = payload or {}
        now_ts = self._now()
        event = {
            "ts": now_ts,
            "iso": datetime.utcnow().isoformat() + "Z",
            "source": source,
            "type": event_type,
            "severity": severity,
            "payload": payload,
        }

        with self._lock:
            self._events.append(event)
            self._prune_locked(now_ts)

            # Lightweight append first for durability.
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
                self._writes_since_compact += 1
            except Exception as exc:
                logger.warning("Failed to append event log entry: %s", exc)

            # Periodically compact file to keep only retention window.
            if self._writes_since_compact >= self._compact_every:
                self._compact_file_locked()

    def compact_now(self):
        with self._lock:
            self._prune_locked(self._now())
            self._compact_file_locked()

    def get_recent_events(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._prune_locked(self._now())
            return list(self._events)

    def get_meta(self) -> Dict[str, Any]:
        with self._lock:
            self._prune_locked(self._now())
            return {
                "retention_seconds": self._retention_seconds,
                "in_memory_events": len(self._events),
                "max_entries": self._max_entries,
                "file_path": self._file_path,
            }


event_logger = None


def get_event_logger() -> EventLogger:
    global event_logger
    if event_logger is None:
        event_logger = EventLogger()
    return event_logger

"""Experiment recording manager (Slice A: control-plane + manifest + sensor CSV)."""

import csv
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import cv2

from .config import (
    EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS,
    EXPERIMENTS_MANIFEST_FLUSH_SECONDS,
    EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS,
    EXPERIMENTS_MAX_HISTORY,
    EXPERIMENTS_ROOT_DIR,
    EXPERIMENTS_SENSOR_INTERVAL_SECONDS,
    EXPERIMENTS_STORAGE_FALLBACK_DIR,
    EXPERIMENTS_STORAGE_PREFERRED_DIR,
    EXPERIMENTS_VIDEO_CODEC,
    EXPERIMENTS_VIDEO_ENABLED,
    EXPERIMENTS_VIDEO_FPS,
    EXPERIMENTS_VIDEO_SEGMENT_SECONDS,
    EXPERIMENTS_VIDEO_USE_SHARED_FRAME_CACHE,
)

logger = logging.getLogger(__name__)


def _iso_utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_iso_timestamp(value: str) -> float:
    if not value:
        return 0.0
    try:
        normalized = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


class ExperimentManager:
    """Manage experiment run lifecycle and disk artifacts."""

    def __init__(self, sensor_latest_provider: Callable[[], Dict[str, Any]]):
        self._sensor_latest_provider = sensor_latest_provider
        self._lock = threading.RLock()
        self._active_run = None
        self._worker_thread = None
        self._worker_stop_event = None

    @staticmethod
    def _ensure_dir(path: str) -> str:
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _is_mounted(path: str) -> bool:
        try:
            target = os.path.realpath(path)
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and os.path.realpath(parts[1]) == target:
                        return True
        except Exception:
            return False
        return False

    @staticmethod
    def _is_writable(path: str, strict_probe: bool = True) -> bool:
        try:
            os.makedirs(path, exist_ok=True)
            if not strict_probe:
                return bool(os.path.isdir(path) and os.access(path, os.W_OK))

            probe_file = os.path.join(path, ".write_probe")
            with open(probe_file, "w") as f:
                f.write("ok")
                f.flush()
                os.fsync(f.fileno())
            os.remove(probe_file)
            return True
        except Exception:
            return False

    def resolve_storage(self, strict_probe: bool = True) -> Dict[str, Any]:
        preferred = self._ensure_dir(EXPERIMENTS_STORAGE_PREFERRED_DIR)
        fallback = self._ensure_dir(EXPERIMENTS_STORAGE_FALLBACK_DIR)

        preferred_mounted = self._is_mounted(preferred)
        preferred_writable = self._is_writable(preferred, strict_probe=strict_probe)
        fallback_writable = self._is_writable(fallback, strict_probe=strict_probe)

        if preferred_mounted and preferred_writable:
            selected = preferred
            selected_tier = "preferred"
        elif fallback_writable:
            selected = fallback
            selected_tier = "fallback"
        else:
            raise RuntimeError("No writable storage path available (preferred/fallback)")

        runs_root = os.path.join(selected, "runs")
        self._ensure_dir(runs_root)

        return {
            "preferred_path": preferred,
            "preferred_mounted": preferred_mounted,
            "preferred_writable": preferred_writable,
            "fallback_path": fallback,
            "fallback_writable": fallback_writable,
            "selected_path": selected,
            "selected_tier": selected_tier,
            "runs_root": runs_root,
        }

    @staticmethod
    def _atomic_write_json(path: str, payload: Dict[str, Any]):
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def _new_run_id(self) -> str:
        day = datetime.utcnow().strftime("%Y%m%d")
        clock = datetime.utcnow().strftime("%H%M%S")
        counter = 1
        prefix = "EXP-{0}-".format(day)

        for runs_root in self._candidate_runs_roots():
            if not os.path.isdir(runs_root):
                continue
            try:
                for name in os.listdir(runs_root):
                    if not str(name).startswith(prefix):
                        continue
                    suffix = str(name)[len(prefix):]
                    if suffix.isdigit():
                        counter = max(counter, int(suffix) + 1)
            except Exception:
                continue

        return "EXP-{0}-{1}-{2:03d}".format(day, clock, counter)

    @staticmethod
    def _safe_video_segment_filename(camera_id: str, segment_index: int) -> str:
        ts = datetime.utcnow().strftime("%H%M%S")
        return "{0}_{1}_seg{2:05d}.mp4".format(camera_id, ts, max(1, int(segment_index)))

    @staticmethod
    def _fourcc_from_codec(codec: str):
        text = str(codec or "mp4v").strip()
        if len(text) != 4:
            text = "mp4v"
        return cv2.VideoWriter_fourcc(*text)

    def _video_worker(self, run_id: str, camera_id: str):
        stop_event = self._worker_stop_event
        if stop_event is None:
            return

        writer = None
        camera = None
        frame_count = 0
        segment_frame_count = 0
        segment_index = 0
        segment_started_epoch = None
        segment_rel_path = None
        video_path = None
        segment_target_seconds = int(max(0, int(EXPERIMENTS_VIDEO_SEGMENT_SECONDS)))
        started_epoch = time.time()
        last_direct_pull_ts = 0.0

        try:
            from .camera import get_camera
            camera = get_camera(camera_id)
        except Exception as e:
            logger.warning("Video worker camera init failed for %s: %s", camera_id, e)
            return

        if camera is None:
            logger.warning("Video worker camera missing for %s", camera_id)
            return

        with self._lock:
            run = self._active_run
            if run is None:
                return
            cam_dir = os.path.join(run["run_dir"], camera_id)
            self._ensure_dir(cam_dir)
            run["manifest"].setdefault("video", {})[camera_id] = {
                "path": None,
                "latest_path": None,
                "state": "starting",
                "codec": str(EXPERIMENTS_VIDEO_CODEC),
                "fps": int(EXPERIMENTS_VIDEO_FPS),
                "frames": 0,
                "segment_count": 0,
                "segment_duration_seconds_target": segment_target_seconds if segment_target_seconds > 0 else None,
                "segments": [],
                "started_at": _iso_utc_now(),
                "stopped_at": None,
                "duration_seconds": 0.0,
                "error": None,
            }

        def _finalize_segment(state: str = "completed", error: Optional[str] = None):
            nonlocal writer, segment_started_epoch, segment_frame_count, segment_rel_path, video_path

            if writer is None:
                return

            try:
                writer.release()
            except Exception:
                pass

            writer = None
            segment_stopped_epoch = time.time()
            duration_seconds = (
                round(segment_stopped_epoch - segment_started_epoch, 3)
                if segment_started_epoch is not None
                else 0.0
            )

            with self._lock:
                if self._active_run is None:
                    segment_started_epoch = None
                    segment_frame_count = 0
                    segment_rel_path = None
                    video_path = None
                    return

                v = self._active_run["manifest"]["video"][camera_id]
                if segment_rel_path:
                    v.setdefault("segments", []).append(
                        {
                            "index": int(segment_index),
                            "path": segment_rel_path,
                            "state": state,
                            "started_at": datetime.utcfromtimestamp(segment_started_epoch).replace(microsecond=0).isoformat() + "Z"
                            if segment_started_epoch is not None
                            else None,
                            "stopped_at": _iso_utc_now(),
                            "frames": int(segment_frame_count),
                            "duration_seconds": duration_seconds,
                            "error": error,
                        }
                    )
                    v["segment_count"] = len(v.get("segments", []))
                    if not v.get("path"):
                        v["path"] = segment_rel_path
                    v["latest_path"] = segment_rel_path

                v["frames"] = int(frame_count)
                v["duration_seconds"] = round(segment_stopped_epoch - started_epoch, 3)
                if state == "error":
                    v["state"] = "error"
                    v["error"] = error

            segment_started_epoch = None
            segment_frame_count = 0
            segment_rel_path = None
            video_path = None

        def _start_segment(frame):
            nonlocal writer, segment_started_epoch, segment_frame_count, segment_index, segment_rel_path, video_path

            h, w = frame.shape[:2]
            with self._lock:
                if self._active_run is None:
                    return False
                cam_dir = os.path.join(self._active_run["run_dir"], camera_id)
                self._ensure_dir(cam_dir)
                segment_index += 1
                video_path = os.path.join(cam_dir, self._safe_video_segment_filename(camera_id, segment_index))
                segment_rel_path = os.path.relpath(video_path, self._active_run["run_dir"])

            writer = cv2.VideoWriter(
                video_path,
                self._fourcc_from_codec(EXPERIMENTS_VIDEO_CODEC),
                float(max(1, int(EXPERIMENTS_VIDEO_FPS))),
                (int(w), int(h)),
                True,
            )
            if not writer.isOpened():
                writer = None
                raise RuntimeError("Failed to open VideoWriter for {0}".format(video_path))

            segment_started_epoch = time.time()
            segment_frame_count = 0

            with self._lock:
                if self._active_run is not None:
                    v = self._active_run["manifest"]["video"][camera_id]
                    v["state"] = "recording"
                    v["width"] = int(w)
                    v["height"] = int(h)
                    if not v.get("path"):
                        v["path"] = segment_rel_path
                    v["latest_path"] = segment_rel_path
            return True

        frame_interval = 1.0 / float(max(1, int(EXPERIMENTS_VIDEO_FPS)))
        next_tick = time.time()

        while not stop_event.is_set():
            try:
                ok, frame = False, None
                now_ts = time.time()

                if EXPERIMENTS_VIDEO_USE_SHARED_FRAME_CACHE and hasattr(camera, "get_cached_frame"):
                    ok, frame = camera.get_cached_frame(max_age_seconds=EXPERIMENTS_VIDEO_CACHE_MAX_AGE_SECONDS)

                # Fallback: pull directly at a throttled cadence only when cache is stale/missing.
                if (not ok or frame is None) and (now_ts - last_direct_pull_ts) >= float(EXPERIMENTS_VIDEO_DIRECT_PULL_INTERVAL_SECONDS):
                    ok, frame = camera.get_frame()
                    last_direct_pull_ts = now_ts

                if not ok or frame is None:
                    time.sleep(0.02)
                    continue

                if writer is None:
                    _start_segment(frame)

                writer.write(frame)
                frame_count += 1
                segment_frame_count += 1

                with self._lock:
                    if self._active_run is not None:
                        v = self._active_run["manifest"]["video"][camera_id]
                        v["frames"] = int(frame_count)
                        v["duration_seconds"] = round(time.time() - started_epoch, 3)

                if (
                    segment_target_seconds > 0
                    and segment_started_epoch is not None
                    and (time.time() - segment_started_epoch) >= segment_target_seconds
                ):
                    _finalize_segment(state="completed")

            except Exception as e:
                logger.warning("Video worker error for %s: %s", camera_id, e)
                _finalize_segment(state="error", error=str(e))
                with self._lock:
                    if self._active_run is not None and camera_id in self._active_run["manifest"].get("video", {}):
                        v = self._active_run["manifest"]["video"][camera_id]
                        v["state"] = "error"
                        v["error"] = str(e)
                break

            next_tick += frame_interval
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                stop_event.wait(sleep_for)

        _finalize_segment(state="completed")

        with self._lock:
            if self._active_run is not None and camera_id in self._active_run["manifest"].get("video", {}):
                v = self._active_run["manifest"]["video"][camera_id]
                if v.get("state") != "error":
                    v["state"] = "completed"
                v["stopped_at"] = _iso_utc_now()
                v["frames"] = int(frame_count)
                v["duration_seconds"] = round(time.time() - started_epoch, 3)

    def _build_manifest(self, run_id: str, run_dir: str, payload: Dict[str, Any], storage: Dict[str, Any]) -> Dict[str, Any]:
        now_iso = _iso_utc_now()
        return {
            "run_id": run_id,
            "state": "active",
            "created_at": now_iso,
            "updated_at": now_iso,
            "started_at": now_iso,
            "stopped_at": None,
            "duration_seconds": 0.0,
            "run_name": payload.get("run_name") or run_id,
            "tags": payload.get("tags") or [],
            "operator": payload.get("operator"),
            "site": payload.get("site"),
            "notes": payload.get("notes"),
            "software": payload.get("software") or {},
            "camera_mapping": payload.get("camera_mapping") or {},
            "storage": {
                "selected_tier": storage.get("selected_tier"),
                "selected_path": storage.get("selected_path"),
                "preferred_mounted": bool(storage.get("preferred_mounted")),
                "preferred_writable": bool(storage.get("preferred_writable")),
                "fallback_writable": bool(storage.get("fallback_writable")),
            },
            "artifacts": {
                "run_dir": run_dir,
                "manifest": os.path.join(run_dir, "manifest.json"),
                "sensors_csv": os.path.join(run_dir, "sensors.csv"),
                "cam1_dir": os.path.join(run_dir, "cam1"),
                "cam2_dir": os.path.join(run_dir, "cam2"),
            },
            "sensor": {
                "sampling_interval_seconds": float(EXPERIMENTS_SENSOR_INTERVAL_SECONDS),
                "sample_count": 0,
                "latest_source": None,
                "latest_timestamp": None,
            },
            "video": {},
        }

    def _sensor_worker(self):
        flush_period = float(EXPERIMENTS_MANIFEST_FLUSH_SECONDS)
        last_manifest_flush = 0.0

        while not self._worker_stop_event.is_set():
            try:
                with self._lock:
                    run = self._active_run
                    if run is None:
                        break
                    csv_writer = run["csv_writer"]
                    csv_file = run["csv_file"]
                    manifest = run["manifest"]

                now_epoch = time.time()
                monotonic_offset = round(now_epoch - run["started_epoch"], 3)
                sample = self._sensor_latest_provider() or {}

                row = {
                    "wall_time_utc": _iso_utc_now(),
                    "monotonic_offset_seconds": monotonic_offset,
                    "hot_zone_temperature": sample.get("hot_zone_temperature"),
                    "cold_zone_temperature": sample.get("cold_zone_temperature"),
                    "exhaust_temp": sample.get("exhaust_temp"),
                    "source": sample.get("source"),
                    "sensor_timestamp": sample.get("timestamp"),
                }

                with self._lock:
                    if self._active_run is None:
                        break
                    csv_writer.writerow(row)
                    csv_file.flush()
                    os.fsync(csv_file.fileno())

                    manifest["sensor"]["sample_count"] += 1
                    manifest["sensor"]["latest_source"] = row.get("source")
                    manifest["sensor"]["latest_timestamp"] = row.get("sensor_timestamp")
                    manifest["updated_at"] = _iso_utc_now()
                    manifest["duration_seconds"] = round(now_epoch - run["started_epoch"], 3)

                    if (now_epoch - last_manifest_flush) >= flush_period:
                        self._atomic_write_json(run["manifest_path"], manifest)
                        last_manifest_flush = now_epoch

            except Exception as e:
                logger.warning("Experiment sensor worker iteration failed: %s", e)

            self._worker_stop_event.wait(float(EXPERIMENTS_SENSOR_INTERVAL_SECONDS))

    def start_run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        with self._lock:
            if self._active_run is not None:
                raise RuntimeError("An experiment run is already active")

            storage = self.resolve_storage()
            run_id = self._new_run_id()
            run_dir = self._ensure_dir(os.path.join(storage["runs_root"], run_id))
            self._ensure_dir(os.path.join(run_dir, "cam1"))
            self._ensure_dir(os.path.join(run_dir, "cam2"))

            manifest = self._build_manifest(run_id, run_dir, payload, storage)
            manifest_path = os.path.join(run_dir, "manifest.json")
            csv_path = os.path.join(run_dir, "sensors.csv")

            csv_file = open(csv_path, "a", newline="")
            csv_writer = csv.DictWriter(
                csv_file,
                fieldnames=[
                    "wall_time_utc",
                    "monotonic_offset_seconds",
                    "hot_zone_temperature",
                    "cold_zone_temperature",
                    "exhaust_temp",
                    "source",
                    "sensor_timestamp",
                ],
            )
            if csv_file.tell() == 0:
                csv_writer.writeheader()
                csv_file.flush()
                os.fsync(csv_file.fileno())

            self._atomic_write_json(manifest_path, manifest)

            self._worker_stop_event = threading.Event()
            video_threads = []

            self._active_run = {
                "run_id": run_id,
                "run_dir": run_dir,
                "started_epoch": time.time(),
                "manifest": manifest,
                "manifest_path": manifest_path,
                "csv_path": csv_path,
                "csv_file": csv_file,
                "csv_writer": csv_writer,
                "storage": storage,
                "video_threads": video_threads,
            }

            self._worker_thread = threading.Thread(
                target=self._sensor_worker,
                name="experiment-sensor-worker",
                daemon=True,
            )
            self._worker_thread.start()

            if EXPERIMENTS_VIDEO_ENABLED:
                try:
                    from .camera import get_camera_ids
                    camera_ids = list(get_camera_ids() or [])
                except Exception:
                    camera_ids = ["cam1", "cam2"]

                for camera_id in camera_ids:
                    t = threading.Thread(
                        target=self._video_worker,
                        args=(run_id, camera_id),
                        name="experiment-video-{0}".format(camera_id),
                        daemon=True,
                    )
                    video_threads.append(t)
                    t.start()

            logger.info("Experiment run started: %s (%s)", run_id, run_dir)
            return self.get_active_run()

    def stop_run(self, reason: str = "manual_stop") -> Dict[str, Any]:
        with self._lock:
            if self._active_run is None:
                raise RuntimeError("No active experiment run")
            run = self._active_run

        if self._worker_stop_event is not None:
            self._worker_stop_event.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)

        with self._lock:
            video_threads = list((self._active_run or {}).get("video_threads") or [])

        for t in video_threads:
            if t is not None and t.is_alive():
                t.join(timeout=3.0)

        with self._lock:
            ended_epoch = time.time()
            run = self._active_run
            if run is None:
                raise RuntimeError("Run already stopped")

            manifest = run["manifest"]
            manifest["state"] = "completed"
            manifest["stop_reason"] = reason
            manifest["updated_at"] = _iso_utc_now()
            manifest["stopped_at"] = _iso_utc_now()
            manifest["duration_seconds"] = round(ended_epoch - run["started_epoch"], 3)

            self._atomic_write_json(run["manifest_path"], manifest)

            try:
                run["csv_file"].flush()
                os.fsync(run["csv_file"].fileno())
            except Exception:
                pass
            try:
                run["csv_file"].close()
            except Exception:
                pass

            summary = {
                "run_id": run["run_id"],
                "run_dir": run["run_dir"],
                "manifest_path": run["manifest_path"],
                "csv_path": run["csv_path"],
                "state": manifest["state"],
                "sample_count": int(manifest["sensor"]["sample_count"]),
                "duration_seconds": manifest["duration_seconds"],
                "stop_reason": reason,
                "video": manifest.get("video", {}),
            }

            self._active_run = None
            self._worker_thread = None
            self._worker_stop_event = None

            logger.info("Experiment run stopped: %s", summary["run_id"])
            return summary

    def stop_if_active(self, reason: str = "shutdown"):
        with self._lock:
            has_active = self._active_run is not None
        if has_active:
            try:
                self.stop_run(reason=reason)
            except Exception as e:
                logger.warning("Failed to stop active run during shutdown: %s", e)

    def get_active_run(self) -> Dict[str, Any]:
        with self._lock:
            if self._active_run is None:
                return {"active": False, "run": None}

            run = self._active_run
            manifest = run["manifest"]
            return {
                "active": True,
                "run": {
                    "run_id": run["run_id"],
                    "run_dir": run["run_dir"],
                    "started_at": manifest.get("started_at"),
                    "run_name": manifest.get("run_name"),
                    "state": manifest.get("state"),
                    "sample_count": manifest.get("sensor", {}).get("sample_count", 0),
                    "storage": manifest.get("storage", {}),
                    "artifacts": manifest.get("artifacts", {}),
                },
            }

    @staticmethod
    def _run_summary_from_manifest(manifest: Dict[str, Any], run_dir: str) -> Dict[str, Any]:
        sensor = manifest.get("sensor", {})
        return {
            "run_id": manifest.get("run_id"),
            "run_name": manifest.get("run_name"),
            "state": manifest.get("state"),
            "started_at": manifest.get("started_at"),
            "stopped_at": manifest.get("stopped_at"),
            "duration_seconds": manifest.get("duration_seconds", 0.0),
            "sample_count": sensor.get("sample_count", 0),
            "storage_tier": manifest.get("storage", {}).get("selected_tier"),
            "run_dir": run_dir,
        }

    def _candidate_runs_roots(self) -> List[str]:
        roots = [
            os.path.join(EXPERIMENTS_STORAGE_PREFERRED_DIR, "runs"),
            os.path.join(EXPERIMENTS_STORAGE_FALLBACK_DIR, "runs"),
            os.path.join(EXPERIMENTS_ROOT_DIR, "runs"),
        ]
        uniq = []
        seen = set()
        for r in roots:
            key = os.path.realpath(r)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        return uniq

    @staticmethod
    def _run_dir_size_bytes(run_dir: str) -> int:
        total = 0
        for root, _, files in os.walk(run_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    total += int(os.path.getsize(path))
                except Exception:
                    continue
        return int(total)

    def _scan_run_dirs(self, runs_root: str) -> List[Dict[str, Any]]:
        items = []
        if not os.path.isdir(runs_root):
            return items

        active_run_id = None
        with self._lock:
            if self._active_run is not None:
                active_run_id = self._active_run.get("run_id")

        try:
            for run_id in os.listdir(runs_root):
                run_dir = os.path.join(runs_root, run_id)
                if not os.path.isdir(run_dir):
                    continue

                manifest_path = os.path.join(run_dir, "manifest.json")
                manifest = {}
                if os.path.isfile(manifest_path):
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                    except Exception:
                        manifest = {}

                started_at = str(manifest.get("started_at") or "")
                sort_ts = _parse_iso_timestamp(started_at)
                if sort_ts <= 0:
                    try:
                        sort_ts = float(os.path.getmtime(run_dir))
                    except Exception:
                        sort_ts = 0.0

                size_bytes = self._run_dir_size_bytes(run_dir)
                items.append(
                    {
                        "run_id": str(run_id),
                        "run_dir": run_dir,
                        "manifest_path": manifest_path,
                        "started_at": started_at,
                        "sort_ts": sort_ts,
                        "size_bytes": int(size_bytes),
                        "is_active": str(run_id) == str(active_run_id),
                    }
                )
        except Exception:
            return items

        items.sort(key=lambda item: item.get("sort_ts", 0.0))
        return items

    def get_storage_health(self) -> Dict[str, Any]:
        health_error = None
        try:
            # Health polling path should be fast and non-disruptive.
            storage = self.resolve_storage(strict_probe=False)
        except Exception as e:
            health_error = str(e)
            preferred = str(EXPERIMENTS_STORAGE_PREFERRED_DIR)
            fallback = str(EXPERIMENTS_STORAGE_FALLBACK_DIR)
            storage = {
                "preferred_path": preferred,
                "preferred_mounted": self._is_mounted(preferred),
                "preferred_writable": self._is_writable(preferred, strict_probe=False),
                "fallback_path": fallback,
                "fallback_writable": self._is_writable(fallback, strict_probe=False),
                "selected_path": fallback,
                "selected_tier": "fallback",
                "runs_root": os.path.join(fallback, "runs"),
            }

        selected_path = storage.get("selected_path") or str(EXPERIMENTS_STORAGE_FALLBACK_DIR)
        runs_root = storage.get("runs_root") or os.path.join(str(EXPERIMENTS_STORAGE_FALLBACK_DIR), "runs")
        run_items = self._scan_run_dirs(runs_root)

        try:
            disk = shutil.disk_usage(selected_path)
            total_bytes = int(disk.total)
            used_bytes = int(disk.used)
            free_bytes = int(disk.free)
        except Exception:
            total_bytes = 0
            used_bytes = 0
            free_bytes = 0

        runs_total_bytes = int(sum(int(item.get("size_bytes", 0)) for item in run_items))
        active_run_id = None
        with self._lock:
            if self._active_run is not None:
                active_run_id = self._active_run.get("run_id")

        return {
            "healthy": health_error is None,
            "error": health_error,
            "storage": storage,
            "disk": {
                "total_bytes": total_bytes,
                "used_bytes": used_bytes,
                "free_bytes": free_bytes,
            },
            "runs": {
                "count": len(run_items),
                "total_size_bytes": runs_total_bytes,
                "active_run_id": active_run_id,
            },
        }

    def cleanup_storage(self, retention_days: float, max_total_gb: float, low_watermark_gb: float) -> Dict[str, Any]:
        storage = self.resolve_storage()
        selected_path = storage["selected_path"]
        runs_root = storage["runs_root"]

        retention_days = max(0.0, float(retention_days or 0.0))
        max_total_bytes = int(max(0.0, float(max_total_gb or 0.0)) * 1024 * 1024 * 1024)
        low_watermark_bytes = int(max(0.0, float(low_watermark_gb or 0.0)) * 1024 * 1024 * 1024)

        now = time.time()
        cutoff_ts = now - (retention_days * 86400.0) if retention_days > 0 else None
        run_items = self._scan_run_dirs(runs_root)

        removed = []
        reclaimed_bytes = 0

        # Pass 1: age-based retention cleanup
        if cutoff_ts is not None:
            for item in run_items:
                if item.get("is_active"):
                    continue
                if float(item.get("sort_ts") or 0.0) <= cutoff_ts:
                    run_dir = item.get("run_dir")
                    size_bytes = int(item.get("size_bytes") or 0)
                    try:
                        shutil.rmtree(run_dir, ignore_errors=False)
                        removed.append(
                            {
                                "run_id": item.get("run_id"),
                                "run_dir": run_dir,
                                "reason": "retention_days",
                                "size_bytes": size_bytes,
                            }
                        )
                        reclaimed_bytes += size_bytes
                    except Exception as e:
                        logger.warning("Failed to delete old run %s: %s", run_dir, e)

        # Re-scan before capacity-based pass.
        run_items = self._scan_run_dirs(runs_root)

        def _current_runs_total_bytes() -> int:
            return int(sum(int(item.get("size_bytes", 0)) for item in run_items if not item.get("is_active")))

        def _current_free_bytes() -> int:
            try:
                return int(shutil.disk_usage(selected_path).free)
            except Exception:
                return 0

        runs_total_bytes = _current_runs_total_bytes()
        free_bytes = _current_free_bytes()

        # Pass 2: cap and low-watermark cleanup (oldest first)
        for item in run_items:
            if item.get("is_active"):
                continue

            cap_violated = max_total_bytes > 0 and runs_total_bytes > max_total_bytes
            low_space = low_watermark_bytes > 0 and free_bytes < low_watermark_bytes
            if not cap_violated and not low_space:
                break

            run_dir = item.get("run_dir")
            size_bytes = int(item.get("size_bytes") or 0)
            try:
                shutil.rmtree(run_dir, ignore_errors=False)
                reason = "capacity_cap" if cap_violated else "low_watermark"
                removed.append(
                    {
                        "run_id": item.get("run_id"),
                        "run_dir": run_dir,
                        "reason": reason,
                        "size_bytes": size_bytes,
                    }
                )
                reclaimed_bytes += size_bytes
                runs_total_bytes = max(0, runs_total_bytes - size_bytes)
                free_bytes = _current_free_bytes()
            except Exception as e:
                logger.warning("Failed to delete run %s during capacity cleanup: %s", run_dir, e)

        health = self.get_storage_health()
        return {
            "removed_count": len(removed),
            "removed": removed,
            "reclaimed_bytes": int(reclaimed_bytes),
            "retention_days": retention_days,
            "max_total_gb": float(max_total_gb or 0.0),
            "low_watermark_gb": float(low_watermark_gb or 0.0),
            "health": health,
        }

    def list_history(self, limit: int = EXPERIMENTS_MAX_HISTORY) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 500))
        summaries = []

        for runs_root in self._candidate_runs_roots():
            if not os.path.isdir(runs_root):
                continue
            try:
                for run_id in os.listdir(runs_root):
                    run_dir = os.path.join(runs_root, run_id)
                    if not os.path.isdir(run_dir):
                        continue
                    manifest_path = os.path.join(run_dir, "manifest.json")
                    if not os.path.isfile(manifest_path):
                        continue
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                        summaries.append(self._run_summary_from_manifest(manifest, run_dir))
                    except Exception:
                        continue
            except Exception:
                continue

        summaries.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return {
            "count": len(summaries[:safe_limit]),
            "runs": summaries[:safe_limit],
        }

    def get_artifacts(self, run_id: str) -> Dict[str, Any]:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise RuntimeError("run_id is required")

        for runs_root in self._candidate_runs_roots():
            run_dir = os.path.join(runs_root, run_id)
            manifest_path = os.path.join(run_dir, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue

            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            files = []
            total_size = 0
            for root, _, names in os.walk(run_dir):
                for name in names:
                    p = os.path.join(root, name)
                    try:
                        size = int(os.path.getsize(p))
                    except Exception:
                        size = 0
                    total_size += size
                    files.append(
                        {
                            "path": p,
                            "relative_path": os.path.relpath(p, run_dir),
                            "size_bytes": size,
                        }
                    )

            files.sort(key=lambda item: item["relative_path"])
            return {
                "run_id": run_id,
                "run_dir": run_dir,
                "manifest": manifest,
                "files": files,
                "total_size_bytes": total_size,
            }

        raise RuntimeError("Run not found: {0}".format(run_id))

    def resolve_run_dir(self, run_id: str) -> str:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise RuntimeError("run_id is required")

        for runs_root in self._candidate_runs_roots():
            run_dir = os.path.join(runs_root, run_id)
            manifest_path = os.path.join(run_dir, "manifest.json")
            if os.path.isfile(manifest_path):
                return run_dir

        raise RuntimeError("Run not found: {0}".format(run_id))

    def resolve_run_file(self, run_id: str, relative_path: str) -> str:
        run_dir = self.resolve_run_dir(run_id)
        rel = str(relative_path or "").strip()
        if not rel:
            raise RuntimeError("relative_path is required")

        normalized = os.path.normpath(rel).replace("\\", "/")
        if normalized.startswith("../") or normalized.startswith("/") or normalized == "..":
            raise RuntimeError("Invalid file path")

        full = os.path.realpath(os.path.join(run_dir, normalized))
        run_real = os.path.realpath(run_dir)
        if not full.startswith(run_real + os.sep) and full != run_real:
            raise RuntimeError("Invalid file path")

        if not os.path.isfile(full):
            raise RuntimeError("File not found: {0}".format(relative_path))

        return full

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise RuntimeError("run_id is required")

        with self._lock:
            if self._active_run is not None and str(self._active_run.get("run_id")) == run_id:
                raise RuntimeError("Cannot delete active run")

        run_dir = self.resolve_run_dir(run_id)
        reclaimed_bytes = self._run_dir_size_bytes(run_dir)

        shutil.rmtree(run_dir, ignore_errors=False)

        health = self.get_storage_health()
        return {
            "run_id": run_id,
            "run_dir": run_dir,
            "deleted": True,
            "reclaimed_bytes": int(reclaimed_bytes),
            "health": health,
        }


experiment_manager = None


def get_experiment_manager(sensor_latest_provider: Callable[[], Dict[str, Any]]) -> ExperimentManager:
    global experiment_manager
    if experiment_manager is None:
        experiment_manager = ExperimentManager(sensor_latest_provider=sensor_latest_provider)
    return experiment_manager

"""FastAPI Backend for Jetson Nano Dashboard"""

import atexit
import logging
import asyncio
import signal
import sys
import os
import time
import uuid
import subprocess
import tempfile
import shutil
import mimetypes
import hashlib
import re
from functools import lru_cache
from datetime import datetime
from typing import Any, Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .config import (
    API_DEBUG,
    LOG_LEVEL,
    LOG_FORMAT,
    CAMERA_DEFAULT_ID,
    CAMERA_PROFILES,
    CAMERA_STRICT_CAMERA_IDS,
    WEBRTC_ENABLED_CAMERA_IDS,
    WEBRTC_MAX_CONNECTIONS,
    MEDIA_WEBRTC_GATEWAY_ENABLED,
    MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE,
    MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL,
    MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL,
    CAMERA_H264_STREAM_ENABLED,
    CAMERA_H264_STREAM_BITRATE,
    CAMERA_H264_STREAM_ENCODER_PREFERENCE,
    CAMERA_H264_STREAM_USE_GSTREAMER,
    CAMERA_H264_STREAM_PROFILES,
    CAMERA_H264_FAIL_COOLDOWN_THRESHOLD,
    CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS,
    CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS,
    CAMERA_H264_FAIL_EARLY_SECONDS,
    CAMERA_H264_INPUT_MODE,
    CAMERA_H264_RTSP_URL,
    CAMERA_H264_RTSP_LATENCY_MS,
    CAMERA_H264_RTSP_PROTOCOLS,
    CAMERA_H264_FILE_PATH,
    CAMERA_H264_GST_INPUT_FORMAT,
    CAMERA_H264_GST_FRAGMENT_MS,
    CAMERA_H264_GST_MAXPERF_ENABLE,
    CAMERA_H264_STREAM_GOP,
    CAMERA_H264_STREAM_MAX_FPS,
    EXPERIMENTS_CLEANUP_INTERVAL_SECONDS,
    EXPERIMENTS_LOW_WATERMARK_GB,
    EXPERIMENTS_MAX_TOTAL_GB,
    EXPERIMENTS_PLAYABLE_CACHE_DIR,
    EXPERIMENTS_PLAYABLE_CACHE_MAX_GB,
    EXPERIMENTS_PLAYABLE_CACHE_TTL_HOURS,
    EXPERIMENTS_RETENTION_DAYS,
    EXPERIMENTS_DOWNLOAD_MAX_CONCURRENT,
    EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_ACTIVE_RUN,
    EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_LIVE_STREAMING,
    EXPERIMENTS_DOWNLOAD_ARCHIVE_DIR,
)
from .camera import (
    get_camera,
    check_cuda_availability,
    get_camera_ids,
    release_camera,
    release_all_cameras,
    probe_camera_devices_gstreamer,
)
from .gpio_control import get_gpio_controller
from . import gpio_control as gpio_module
from .vfd_control import get_vfd_controller
from . import vfd_control as vfd_module
from .sensor_data import get_sensor_data_service
from .event_logger import get_event_logger
from .experiments import get_experiment_manager
from .websocket import (
    handle_websocket_connection,
    get_device_status,
    broadcast_device_status
)


WEBRTC_ENABLED_CAMERA_IDS_SET = set(WEBRTC_ENABLED_CAMERA_IDS)


@lru_cache(maxsize=1)
def is_webrtc_available() -> bool:
    """Check whether WebRTC dependencies are available at runtime."""
    try:
        import aiortc  # noqa: F401
        from .webrtc import get_webrtc_manager as _get_webrtc_manager  # noqa: F401
        return True
    except Exception:
        return False


def get_webrtc_manager_safe():
    """Lazy import WebRTC manager to avoid hard startup dependency."""
    from .webrtc import get_webrtc_manager
    return get_webrtc_manager()


def _current_webrtc_connections() -> int:
    if not is_webrtc_available():
        return 0
    try:
        return get_webrtc_manager_safe().get_connection_count()
    except Exception:
        return 0


def _is_webrtc_allowed_for_camera(camera_id: str) -> bool:
    return camera_id in WEBRTC_ENABLED_CAMERA_IDS_SET


def _resolve_media_gateway_whep_url(camera_id: str) -> str:
    camera_key = str(camera_id or "").strip().lower()
    per_camera = {
        "cam1": MEDIA_WEBRTC_GATEWAY_CAM1_WHEP_URL,
        "cam2": MEDIA_WEBRTC_GATEWAY_CAM2_WHEP_URL,
    }
    direct_url = str(per_camera.get(camera_key) or "").strip()
    if direct_url:
        return direct_url

    template = str(MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE or "").strip()
    if not template:
        return ""

    return (
        template
        .replace("{camera_id}", camera_key)
        .replace("{cameraId}", camera_key)
    )


def _media_gateway_info(camera_id: str = None) -> Dict[str, Any]:
    if camera_id:
        whep_url = _resolve_media_gateway_whep_url(camera_id)
        return {
            "enabled": bool(MEDIA_WEBRTC_GATEWAY_ENABLED),
            "camera_id": camera_id,
            "whep_url_configured": bool(whep_url),
            "whep_url": whep_url,
        }

    per_camera = {}
    for cid in get_camera_ids():
        per_camera[cid] = {
            "whep_url_configured": bool(_resolve_media_gateway_whep_url(cid)),
        }

    return {
        "enabled": bool(MEDIA_WEBRTC_GATEWAY_ENABLED),
        "whep_template_configured": bool(str(MEDIA_WEBRTC_GATEWAY_WHEP_TEMPLATE or "").strip()),
        "per_camera": per_camera,
    }

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)


def _run_git_command(path: str, args: List[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except Exception:
        return ""
    return ""


def get_software_version_info() -> Dict[str, str]:
    """Return software version metadata for operator visibility in UI footer."""
    env_branch = (os.getenv("APP_GIT_BRANCH") or "").strip()
    env_commit = (os.getenv("APP_GIT_COMMIT") or "").strip()

    candidate_paths = [
        "/workspace",
        "/workspace/backend",
        "/app",
    ]

    branch = env_branch
    commit = env_commit

    if not branch:
        for path in candidate_paths:
            branch = _run_git_command(path, ["rev-parse", "--abbrev-ref", "HEAD"])
            if branch:
                break

    if not commit:
        for path in candidate_paths:
            commit = _run_git_command(path, ["rev-parse", "--short", "HEAD"])
            if commit:
                break

    if not branch:
        branch = "unknown"
    if not commit:
        commit = "unknown"

    return {
        "branch": branch,
        "commit": commit,
        "label": f"{branch}@{commit}",
    }

# Status tracking
status_broadcast_task = None
camera_idle_watchdog_task = None
safety_watchdog_task = None
experiment_cleanup_task = None
experiment_manager = None
active_mjpeg_sessions = {}
active_h264_sessions = {}
active_mjpeg_lock = asyncio.Lock()
CAMERA_IDLE_RELEASE_SECONDS = max(3, int(os.getenv("CAMERA_IDLE_RELEASE_SECONDS", "6")))
download_archive_semaphore = asyncio.Semaphore(max(1, int(EXPERIMENTS_DOWNLOAD_MAX_CONCURRENT)))

h264_failure_state = {}

CONTROL_HEARTBEAT_TIMEOUT_SECONDS = max(
    5, int(os.getenv("CONTROL_HEARTBEAT_TIMEOUT_SECONDS", "20"))
)
EVENT_LOG_COMPACT_SECONDS = max(5, int(os.getenv("EVENT_LOG_COMPACT_SECONDS", "10")))

last_frontend_heartbeat_ts = 0.0
frontend_heartbeat_seen = False
last_control_activity_ts = time.time()
safety_reset_count = 0
next_event_compact_ts = 0.0


def _get_experiment_manager():
    """Lazily ensure experiment manager is available for API handlers."""
    global experiment_manager
    if experiment_manager is None:
        sensor_service = get_sensor_data_service()
        experiment_manager = get_experiment_manager(sensor_service.get_latest)
    return experiment_manager


def _ensure_playable_h264_mp4(source_path: str) -> str:
    """Transcode source video to browser-friendly H264 MP4 and cache by file fingerprint.

    If transcoding fails on device-specific FFmpeg/OpenCV combinations, return the original
    source path so playback can still proceed using the raw artifact.
    """
    cache_dir = EXPERIMENTS_PLAYABLE_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    st = os.stat(source_path)
    # Version the cache key so older pre-fix artifacts are ignored.
    fingerprint = "v2h264|{0}|{1}|{2}".format(source_path, int(st.st_size), int(st.st_mtime_ns))
    cache_key = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24]
    playable_path = os.path.join(cache_dir, "{0}.mp4".format(cache_key))

    def _probe_codec(path: str) -> str:
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=nokey=1:noprint_wrappers=1",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=20,
                check=False,
            )
            return (probe.stdout or "").strip().lower()
        except Exception:
            return ""

    if os.path.isfile(playable_path) and os.path.getsize(playable_path) > 0:
        cached_codec = _probe_codec(playable_path)
        # Keep only browser-friendly H264 cache artifacts.
        if cached_codec == "h264":
            return playable_path
        try:
            os.remove(playable_path)
        except Exception:
            pass

    tmp_path = playable_path + ".tmp.mp4"

    # Primary path: libx264 for broad browser compatibility.
    cmd_h264 = [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        tmp_path,
    ]

    # Jetson-oriented fallback: hardware OMX H264 encoder when available.
    cmd_h264_omx = [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
        "-an",
        "-c:v",
        "h264_omx",
        "-b:v",
        "2M",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        tmp_path,
    ]

    def _run_ffmpeg(cmd):
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=240,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "ffmpeg transcode failed (rc=%s): %s | stderr_tail=%s",
                    result.returncode,
                    " ".join(cmd),
                    (result.stderr or "")[-1200:],
                )
                return False

            if not (os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0):
                return False

            # Encoder is explicitly set to H264 (`libx264` or `h264_omx`), so a
            # successful ffmpeg return code plus non-empty output is sufficient.
            return True
        except Exception as e:
            logger.warning("ffmpeg transcode exception: %s", e)
            return False

    ok = _run_ffmpeg(cmd_h264)
    if not ok:
        ok = _run_ffmpeg(cmd_h264_omx)

    if not ok:
        return source_path

    os.replace(tmp_path, playable_path)
    return playable_path


def _resolve_camera_id(camera_id: str = None) -> str:
    requested = (camera_id or CAMERA_DEFAULT_ID or "cam1").lower()
    available_ids = get_camera_ids()
    available = set(available_ids)

    if requested in available:
        return requested

    if camera_id and CAMERA_STRICT_CAMERA_IDS:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "camera_not_enabled",
                "requested_camera_id": requested,
                "enabled_camera_ids": available_ids,
            },
        )

    if "cam1" in available:
        return "cam1"
    if available_ids:
        return available_ids[0]

    raise HTTPException(status_code=503, detail="No cameras are configured/enabled")


def _cleanup_playable_cache() -> Dict[str, Any]:
    cache_dir = EXPERIMENTS_PLAYABLE_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    ttl_seconds = float(max(0.0, EXPERIMENTS_PLAYABLE_CACHE_TTL_HOURS) * 3600.0)
    max_total_bytes = int(max(0.0, EXPERIMENTS_PLAYABLE_CACHE_MAX_GB) * 1024 * 1024 * 1024)
    now_ts = time.time()

    items = []
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except Exception:
            continue
        items.append(
            {
                "path": path,
                "name": name,
                "mtime": float(st.st_mtime),
                "size": int(st.st_size),
            }
        )

    removed = []
    reclaimed_bytes = 0

    # Pass 1: TTL expiration
    if ttl_seconds > 0:
        for item in list(items):
            if (now_ts - item["mtime"]) >= ttl_seconds:
                try:
                    os.remove(item["path"])
                    removed.append({"name": item["name"], "reason": "ttl", "size_bytes": item["size"]})
                    reclaimed_bytes += int(item["size"])
                    items.remove(item)
                except Exception:
                    continue

    # Pass 2: size cap (oldest first)
    if max_total_bytes > 0:
        items.sort(key=lambda x: x["mtime"])
        total_bytes = int(sum(item["size"] for item in items))
        for item in items:
            if total_bytes <= max_total_bytes:
                break
            try:
                os.remove(item["path"])
                removed.append({"name": item["name"], "reason": "size_cap", "size_bytes": item["size"]})
                reclaimed_bytes += int(item["size"])
                total_bytes = max(0, total_bytes - int(item["size"]))
            except Exception:
                continue

    try:
        final_total_bytes = int(
            sum(
                int(os.path.getsize(os.path.join(cache_dir, n)))
                for n in os.listdir(cache_dir)
                if os.path.isfile(os.path.join(cache_dir, n))
            )
        )
    except Exception:
        final_total_bytes = 0

    return {
        "cache_dir": cache_dir,
        "removed_count": len(removed),
        "removed": removed,
        "reclaimed_bytes": int(reclaimed_bytes),
        "total_bytes": final_total_bytes,
        "ttl_hours": float(EXPERIMENTS_PLAYABLE_CACHE_TTL_HOURS),
        "max_gb": float(EXPERIMENTS_PLAYABLE_CACHE_MAX_GB),
    }


async def experiment_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(float(EXPERIMENTS_CLEANUP_INTERVAL_SECONDS))
            manager = _get_experiment_manager()

            storage_result = await run_in_threadpool(
                manager.cleanup_storage,
                EXPERIMENTS_RETENTION_DAYS,
                EXPERIMENTS_MAX_TOTAL_GB,
                EXPERIMENTS_LOW_WATERMARK_GB,
            )
            cache_result = await run_in_threadpool(_cleanup_playable_cache)

            if int(storage_result.get("removed_count", 0)) > 0 or int(cache_result.get("removed_count", 0)) > 0:
                get_event_logger().log_event(
                    source="backend",
                    event_type="storage_cleanup",
                    severity="info",
                    payload={
                        "removed_runs": int(storage_result.get("removed_count", 0)),
                        "reclaimed_run_bytes": int(storage_result.get("reclaimed_bytes", 0)),
                        "removed_cache_files": int(cache_result.get("removed_count", 0)),
                        "reclaimed_cache_bytes": int(cache_result.get("reclaimed_bytes", 0)),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Experiment cleanup loop error: %s", e)


def _ensure_camera_session_bucket(camera_id: str):
    if camera_id not in active_mjpeg_sessions:
        active_mjpeg_sessions[camera_id] = set()


def _ensure_h264_session_bucket(camera_id: str):
    if camera_id not in active_h264_sessions:
        active_h264_sessions[camera_id] = set()


def _get_h264_stream_profile(camera_id: str) -> Dict[str, Any]:
    camera_key = str(camera_id or "").strip().lower()
    profile = CAMERA_H264_STREAM_PROFILES.get(camera_key)
    if isinstance(profile, dict):
        return dict(profile)
    return {
        "enabled": bool(CAMERA_H264_STREAM_ENABLED),
        "bitrate": int(CAMERA_H264_STREAM_BITRATE),
        "gop": int(CAMERA_H264_STREAM_GOP),
        "max_fps": int(CAMERA_H264_STREAM_MAX_FPS),
        "use_gstreamer": bool(CAMERA_H264_STREAM_USE_GSTREAMER),
    }


def _ensure_h264_failure_bucket(camera_id: str) -> Dict[str, Any]:
    camera_key = str(camera_id or "").strip().lower()
    bucket = h264_failure_state.get(camera_key)
    if bucket is None:
        bucket = {
            "consecutive_failures": 0,
            "cooldown_until_ts": 0.0,
            "last_failure_ts": 0.0,
            "last_success_ts": 0.0,
            "last_failure_reason": None,
        }
        h264_failure_state[camera_key] = bucket
    return bucket


def _h264_cooldown_remaining_ms(camera_id: str) -> int:
    bucket = _ensure_h264_failure_bucket(camera_id)
    remaining_seconds = max(0.0, float(bucket.get("cooldown_until_ts", 0.0)) - time.time())
    return int(remaining_seconds * 1000.0)


def _h264_record_success(camera_id: str):
    bucket = _ensure_h264_failure_bucket(camera_id)
    bucket["consecutive_failures"] = 0
    bucket["cooldown_until_ts"] = 0.0
    bucket["last_success_ts"] = float(time.time())
    bucket["last_failure_reason"] = None


def _h264_record_failure(camera_id: str, reason: str = "stream_failed"):
    bucket = _ensure_h264_failure_bucket(camera_id)
    bucket["consecutive_failures"] = int(bucket.get("consecutive_failures", 0)) + 1
    bucket["last_failure_ts"] = float(time.time())
    bucket["last_failure_reason"] = str(reason or "stream_failed")

    threshold = int(CAMERA_H264_FAIL_COOLDOWN_THRESHOLD)
    failures = int(bucket["consecutive_failures"])
    if failures >= threshold:
        exponent = max(0, failures - threshold)
        cooldown_seconds = min(
            int(CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS),
            int(CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS) * (2 ** exponent),
        )
        bucket["cooldown_until_ts"] = time.time() + float(cooldown_seconds)


def _h264_stream_hint(camera_id: str) -> Dict[str, Any]:
    bucket = _ensure_h264_failure_bucket(camera_id)
    profile = _get_h264_stream_profile(camera_id)
    remaining_ms = _h264_cooldown_remaining_ms(camera_id)
    return {
        "enabled": bool(profile.get("enabled", CAMERA_H264_STREAM_ENABLED)),
        "cooldown_active": remaining_ms > 0,
        "cooldown_remaining_ms": remaining_ms,
        "consecutive_failures": int(bucket.get("consecutive_failures", 0)),
        "failure_threshold": int(CAMERA_H264_FAIL_COOLDOWN_THRESHOLD),
        "failure_cooldown_base_ms": int(CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS) * 1000,
        "failure_cooldown_max_ms": int(CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS) * 1000,
        "profile": {
            "bitrate": int(profile.get("bitrate", CAMERA_H264_STREAM_BITRATE)),
            "gop": int(profile.get("gop", CAMERA_H264_STREAM_GOP)),
            "max_fps": int(profile.get("max_fps", CAMERA_H264_STREAM_MAX_FPS)),
            "use_gstreamer": bool(profile.get("use_gstreamer", CAMERA_H264_STREAM_USE_GSTREAMER)),
        },
    }


def _download_live_stream_activity() -> Dict[str, int]:
    """Return best-effort active stream counters for download load shedding."""
    total_mjpeg = 0
    try:
        total_mjpeg = int(sum(len(sids) for sids in active_mjpeg_sessions.values()))
    except Exception:
        total_mjpeg = 0

    total_h264 = 0
    try:
        total_h264 = int(sum(len(sids) for sids in active_h264_sessions.values()))
    except Exception:
        total_h264 = 0

    return {
        "mjpeg": max(0, total_mjpeg),
        "h264": max(0, total_h264),
        "webrtc": max(0, int(_current_webrtc_connections())),
    }


@lru_cache(maxsize=1)
def _ffmpeg_encoders_cache_blob() -> str:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=2.5,
            check=False,
        )
        return (result.stdout or "").lower()
    except Exception:
        return ""


def _ffmpeg_encoder_available(encoder_name: str) -> bool:
    blob = _ffmpeg_encoders_cache_blob()
    if not blob:
        return False
    return (" " + str(encoder_name).strip().lower()) in blob


@lru_cache(maxsize=64)
def _gst_element_available(element_name: str) -> bool:
    name = str(element_name or "").strip()
    if not name:
        return False
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _pick_h264_stream_encoder(encoder_preference: str = None) -> str:
    preferred = [
        token.strip().lower()
        for token in str(encoder_preference or CAMERA_H264_STREAM_ENCODER_PREFERENCE or "").split(",")
        if token.strip()
    ]
    if not preferred:
        preferred = ["h264_nvmpi", "h264_omx", "h264_v4l2m2m", "libx264"]

    for encoder in preferred:
        if _ffmpeg_encoder_available(encoder):
            return encoder

    return "libx264"


def _build_h264_stream_ffmpeg_command(camera_id: str, h264_profile: Dict[str, Any]):
    input_mode = str(CAMERA_H264_INPUT_MODE or "usb").strip().lower()
    profile = CAMERA_PROFILES.get(camera_id) or {}
    camera_device = str(profile.get("device") or "/dev/video0")
    width = max(160, int(profile.get("width") or 640))
    height = max(120, int(profile.get("height") or 480))
    profile_max_fps = max(1, int(h264_profile.get("max_fps", CAMERA_H264_STREAM_MAX_FPS)))
    profile_bitrate = max(200000, int(h264_profile.get("bitrate", CAMERA_H264_STREAM_BITRATE)))
    profile_gop = max(5, int(h264_profile.get("gop", CAMERA_H264_STREAM_GOP)))
    fps = max(1, min(int(profile.get("fps") or 15), profile_max_fps))

    # Prefer NVIDIA encoder stack first for Jetson; fallback to libx264.
    encoder = _pick_h264_stream_encoder(CAMERA_H264_STREAM_ENCODER_PREFERENCE)
    if encoder == "libx264":
        encoder_args = [
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-b:v",
            str(int(profile_bitrate)),
            "-maxrate",
            str(int(profile_bitrate)),
            "-bufsize",
            str(int(profile_bitrate)),
        ]
    elif encoder in ("h264_nvmpi", "h264_omx"):
        encoder_args = [
            "-b:v",
            str(int(profile_bitrate)),
            "-maxrate",
            str(int(profile_bitrate)),
            "-bufsize",
            str(int(profile_bitrate)),
        ]
    elif encoder == "h264_v4l2m2m":
        encoder_args = [
            "-b:v",
            str(int(profile_bitrate)),
            "-maxrate",
            str(int(profile_bitrate)),
            "-bufsize",
            str(int(profile_bitrate)),
        ]
    else:
        encoder_args = [
            "-b:v",
            str(int(profile_bitrate)),
        ]

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
    ]

    if input_mode == "rtsp" and CAMERA_H264_RTSP_URL:
        cmd.extend(
            [
                "-rtsp_transport",
                "tcp" if CAMERA_H264_RTSP_PROTOCOLS not in ("udp", "tcp") else CAMERA_H264_RTSP_PROTOCOLS,
                "-flags",
                "low_delay",
                "-thread_queue_size",
                "64",
                "-i",
                CAMERA_H264_RTSP_URL,
            ]
        )
    elif input_mode == "file" and CAMERA_H264_FILE_PATH:
        cmd.extend(
            [
                "-re",
                "-stream_loop",
                "-1",
                "-i",
                CAMERA_H264_FILE_PATH,
            ]
        )
    else:
        cmd.extend(
            [
                "-f",
                "v4l2",
                "-thread_queue_size",
                "64",
                "-input_format",
                "mjpeg",
                "-framerate",
                str(int(fps)),
                "-video_size",
                "{0}x{1}".format(width, height),
                "-i",
                camera_device,
            ]
        )

    cmd.extend(
        [
        "-an",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(int(profile_gop)),
        "-c:v",
        encoder,
        ]
    )

    cmd.extend(encoder_args)
    cmd.extend(
        [
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            "pipe:1",
        ]
    )

    return cmd, encoder


def _build_h264_stream_gst_command(camera_id: str, h264_profile: Dict[str, Any]):
    input_mode = str(CAMERA_H264_INPUT_MODE or "usb").strip().lower()
    profile = CAMERA_PROFILES.get(camera_id) or {}
    camera_device = str(profile.get("device") or "/dev/video0")
    width = max(160, int(profile.get("width") or 640))
    height = max(120, int(profile.get("height") or 480))
    profile_max_fps = max(1, int(h264_profile.get("max_fps", CAMERA_H264_STREAM_MAX_FPS)))
    profile_bitrate = max(200000, int(h264_profile.get("bitrate", CAMERA_H264_STREAM_BITRATE)))
    profile_gop = max(5, int(h264_profile.get("gop", CAMERA_H264_STREAM_GOP)))
    fps = max(1, min(int(profile.get("fps") or 15), profile_max_fps))
    input_format = str(CAMERA_H264_GST_INPUT_FORMAT or "YUY2").upper()
    supported_fps = _query_v4l2_max_fps_for_mode(camera_device, input_format, width, height)
    if supported_fps and supported_fps > 0:
        fps = max(1, min(int(fps), int(supported_fps)))
    bitrate = int(profile_bitrate)
    gop = int(profile_gop)

    maxperf_value = "true" if CAMERA_H264_GST_MAXPERF_ENABLE else "false"

    if input_mode == "rtsp" and CAMERA_H264_RTSP_URL:
        source_chain = [
            "rtspsrc",
            "location={0}".format(CAMERA_H264_RTSP_URL),
            "latency={0}".format(int(CAMERA_H264_RTSP_LATENCY_MS)),
            "protocols=tcp" if CAMERA_H264_RTSP_PROTOCOLS != "udp" else "protocols=udp",
            "!",
            "rtph264depay",
            "!",
            "h264parse",
            "!",
            "nvv4l2decoder",
            "!",
        ]
    elif input_mode == "file" and CAMERA_H264_FILE_PATH:
        source_chain = [
            "filesrc",
            "location={0}".format(CAMERA_H264_FILE_PATH),
            "!",
            "qtdemux",
            "!",
            "h264parse",
            "!",
            "nvv4l2decoder",
            "!",
        ]
    else:
        source_chain = [
            "v4l2src",
            "device={0}".format(camera_device),
            "io-mode=2",
            "do-timestamp=true",
            "!",
            "video/x-raw,format={0},width={1},height={2},framerate={3}/1".format(
                input_format,
                int(width),
                int(height),
                int(fps),
            ),
            "!",
        ]

    cmd = [
        "gst-launch-1.0",
        "-q",
    ]
    cmd.extend(source_chain)
    cmd.extend([
        "nvvidconv",
        "!",
        "video/x-raw(memory:NVMM),format=NV12",
        "!",
        "nvv4l2h264enc",
        "bitrate={0}".format(bitrate),
        "iframeinterval={0}".format(gop),
        "idrinterval={0}".format(gop),
        "insert-sps-pps=true",
        "maxperf-enable={0}".format(maxperf_value),
        "!",
        "h264parse",
        "config-interval=1",
        "!",
        "mp4mux",
        "streamable=true",
        "fragment-duration={0}".format(int(CAMERA_H264_GST_FRAGMENT_MS)),
        "!",
        "fdsink",
        "fd=1",
        "sync=false",
    ])
    return cmd, "nvv4l2h264enc"


def _query_v4l2_max_fps_for_mode(camera_device: str, pixel_format: str, width: int, height: int):
    # Best-effort parser for `v4l2-ctl --list-formats-ext` to avoid invalid caps.
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", str(camera_device), "--list-formats-ext"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=2.5,
            check=False,
        )
        text = result.stdout or ""
    except Exception:
        return None

    desired = str(pixel_format or "").strip().upper()
    if desired == "YUY2":
        desired_fourcc = {"YUY2", "YUYV"}
    else:
        desired_fourcc = {desired}

    current_fourcc = ""
    current_size = None
    fps_values = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        pf_match = re.search(r"Pixel Format:\s*'([^']+)'", line)
        if pf_match:
            current_fourcc = str(pf_match.group(1) or "").strip().upper()
            current_size = None
            continue

        size_match = re.search(r"Size:\s*Discrete\s*(\d+)x(\d+)", line)
        if size_match:
            current_size = (int(size_match.group(1)), int(size_match.group(2)))
            continue

        fps_match = re.search(r"\(([0-9.]+)\s*fps\)", line)
        if fps_match and current_fourcc in desired_fourcc and current_size == (int(width), int(height)):
            try:
                fps_values.append(float(fps_match.group(1)))
            except Exception:
                continue

    if not fps_values:
        return None
    return int(max(fps_values))


def _can_use_h264_gst_pipeline(h264_profile: Dict[str, Any]) -> bool:
    if not bool(h264_profile.get("use_gstreamer", CAMERA_H264_STREAM_USE_GSTREAMER)):
        return False

    input_mode = str(CAMERA_H264_INPUT_MODE or "usb").strip().lower()
    required = ["nvvidconv", "nvv4l2h264enc", "h264parse", "mp4mux", "fdsink"]

    if input_mode == "rtsp" and CAMERA_H264_RTSP_URL:
        required.extend(["rtspsrc", "rtph264depay", "nvv4l2decoder"])
    elif input_mode == "file" and CAMERA_H264_FILE_PATH:
        required.extend(["filesrc", "qtdemux", "nvv4l2decoder"])
    else:
        required.append("v4l2src")

    return all(_gst_element_available(name) for name in required)


async def camera_idle_watchdog():
    """Release camera automatically after inactivity when no viewers remain."""
    while True:
        try:
            await asyncio.sleep(1.0)

            camera_ids = get_camera_ids()
            for camera_id in camera_ids:
                camera = get_camera(camera_id, create_if_missing=False)
                if camera is None:
                    continue

                async with active_mjpeg_lock:
                    _ensure_camera_session_bucket(camera_id)
                    current_mjpeg_clients = len(active_mjpeg_sessions[camera_id])

                current_webrtc_connections = 0
                if is_webrtc_available():
                    try:
                        current_webrtc_connections = get_webrtc_manager_safe().get_connection_count()
                    except Exception:
                        current_webrtc_connections = 0

                released = camera.maybe_release_if_idle(
                    idle_seconds=CAMERA_IDLE_RELEASE_SECONDS,
                    active_mjpeg_clients=current_mjpeg_clients,
                    webrtc_connections=current_webrtc_connections,
                )
                if released:
                    release_camera(camera_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Camera idle watchdog error: {e}")


def _get_or_recover_camera(camera_id: str):
    """Get camera instance and attempt one-shot recovery when closed."""
    camera = get_camera(camera_id)
    if camera is not None and camera.is_open:
        return camera

    # One-shot force refresh only when an existing instance is present but closed.
    # Avoid release/recreate churn for already-missing instances.
    if camera is not None:
        release_camera(camera_id)
        camera = get_camera(camera_id)
    return camera


def _prewarm_camera_sync(camera_id: str, attempts: int = 5, delay_seconds: float = 0.18) -> Dict[str, Any]:
    """Best-effort warmup to reduce first-frame latency for live MJPEG clients."""
    safe_attempts = max(1, int(attempts))
    safe_delay = max(0.05, float(delay_seconds))

    for attempt in range(1, safe_attempts + 1):
        camera = _get_or_recover_camera(camera_id)
        if camera is not None and camera.is_open:
            ok, jpeg_bytes = camera.get_jpeg_frame(quality=80)
            if ok and jpeg_bytes:
                return {
                    "camera_id": camera_id,
                    "success": True,
                    "attempt": attempt,
                    "bytes": int(len(jpeg_bytes)),
                }
        time.sleep(safe_delay)

    return {
        "camera_id": camera_id,
        "success": False,
        "attempt": safe_attempts,
        "bytes": 0,
    }


async def safety_watchdog_loop():
    """Apply fail-safe GPIO OFF when heartbeat/control path appears unhealthy."""
    global safety_reset_count, next_event_compact_ts

    event_log = get_event_logger()
    while True:
        try:
            await asyncio.sleep(1.0)
            now_ts = time.time()

            # Keep on-disk event file compacted to retention window.
            if now_ts >= next_event_compact_ts:
                event_log.compact_now()
                next_event_compact_ts = now_ts + EVENT_LOG_COMPACT_SECONDS

            if not frontend_heartbeat_seen:
                continue

            stale_frontend = (now_ts - last_frontend_heartbeat_ts) > CONTROL_HEARTBEAT_TIMEOUT_SECONDS
            stale_control = (now_ts - last_control_activity_ts) > CONTROL_HEARTBEAT_TIMEOUT_SECONDS

            if stale_frontend and stale_control:
                vfd = get_vfd_controller()
                vfd_status = vfd.get_status()
                vfd_was_running = bool(vfd_status.get("is_running"))
                vfd_stopped = True
                if vfd_was_running:
                    vfd_stopped = vfd.force_stop(reason="safety_watchdog_timeout")

                gpio = get_gpio_controller()
                gpio_was_on = gpio.any_output_on()
                if gpio_was_on:
                    success = gpio.force_all_outputs_off(reason="safety_watchdog_timeout")
                else:
                    success = True

                if gpio_was_on or vfd_was_running:
                    safety_reset_count += 1
                    event_log.log_event(
                        source="backend",
                        event_type="safety_watchdog_reset",
                        severity="warning",
                        payload={
                            "success": bool(success and vfd_stopped),
                            "gpio_success": bool(success),
                            "vfd_success": bool(vfd_stopped),
                            "timeout_seconds": CONTROL_HEARTBEAT_TIMEOUT_SECONDS,
                            "safety_reset_count": safety_reset_count,
                        },
                    )
                    logger.warning(
                        "Safety watchdog triggered fail-safe reset. gpio_success=%s vfd_success=%s count=%s",
                        success,
                        vfd_stopped,
                        safety_reset_count,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Safety watchdog loop error: %s", e)


def cleanup_resources():
    """Cleanup resources on interpreter exit."""
    try:
        release_all_cameras()
    except Exception as e:
        logger.warning(f"Camera cleanup failed at exit: {e}")
    try:
        if getattr(gpio_module, 'gpio_controller', None) is not None:
            gpio_module.gpio_controller.cleanup()
    except Exception as e:
        logger.warning(f"GPIO cleanup failed at exit: {e}")
    try:
        if getattr(vfd_module, 'vfd_controller', None) is not None:
            vfd_module.vfd_controller.cleanup()
    except Exception as e:
        logger.warning(f"VFD cleanup failed at exit: {e}")


atexit.register(cleanup_resources)


def handle_exit(signal_number, frame):
    """Handle process exit signals."""
    logger.info(f"Received signal {signal_number}, cleaning up resources...")
    if status_broadcast_task:
        try:
            status_broadcast_task.cancel()
        except Exception as e:
            logger.warning(f"Failed to cancel status broadcast task: {e}")
    cleanup_resources()
    sys.exit(0)

for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, handle_exit)


# Create FastAPI app
app = FastAPI(
    title="Jetson Nano Dashboard API",
    description="Real-time video streaming and GPIO control",
    version="1.0.0"
)

# Startup and shutdown handlers (compatible with Python 3.6)
@app.on_event("startup")
async def on_startup():
    global status_broadcast_task, camera_idle_watchdog_task, safety_watchdog_task, experiment_cleanup_task, experiment_manager
    logger.info("Starting Jetson Nano Dashboard backend")
    status_broadcast_task = asyncio.ensure_future(broadcast_device_status())
    camera_idle_watchdog_task = asyncio.ensure_future(camera_idle_watchdog())
    safety_watchdog_task = asyncio.ensure_future(safety_watchdog_loop())
    experiment_cleanup_task = asyncio.ensure_future(experiment_cleanup_loop())
    sensor_service = get_sensor_data_service()
    experiment_manager = get_experiment_manager(sensor_service.get_latest)
    get_event_logger().log_event("backend", "startup", "info", {"version": "1.0.0"})


@app.on_event("shutdown")
async def on_shutdown():
    global status_broadcast_task, camera_idle_watchdog_task, safety_watchdog_task, experiment_cleanup_task, experiment_manager
    logger.info("Shutting down Jetson Nano Dashboard backend")
    get_event_logger().log_event("backend", "shutdown", "info", {})
    if status_broadcast_task:
        status_broadcast_task.cancel()
        try:
            await status_broadcast_task
        except asyncio.CancelledError:
            pass
    if camera_idle_watchdog_task:
        camera_idle_watchdog_task.cancel()
        try:
            await camera_idle_watchdog_task
        except asyncio.CancelledError:
            pass
    if safety_watchdog_task:
        safety_watchdog_task.cancel()
        try:
            await safety_watchdog_task
        except asyncio.CancelledError:
            pass
    if experiment_cleanup_task:
        experiment_cleanup_task.cancel()
        try:
            await experiment_cleanup_task
        except asyncio.CancelledError:
            pass

    if experiment_manager is not None:
        await run_in_threadpool(experiment_manager.stop_if_active, "backend_shutdown")

    # Clean up resources
    release_all_cameras()
    if getattr(gpio_module, 'gpio_controller', None) is not None:
        gpio_module.gpio_controller.cleanup()
    if getattr(vfd_module, 'vfd_controller', None) is not None:
        vfd_module.vfd_controller.cleanup()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_control_path(path: str) -> bool:
    return path.startswith("/api/gpio") or path.startswith("/api/vfd") or path.startswith("/api/system/status")


@app.middleware("http")
async def request_event_middleware(request: Request, call_next):
    """Log backend request telemetry and track control path liveness."""
    global last_control_activity_ts

    started = time.time()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
        duration_ms = round((time.time() - started) * 1000.0, 2)
        client_host = request.client.host if request.client else None

        if _is_control_path(path) and response.status_code < 500:
            last_control_activity_ts = time.time()

        if path.startswith("/api"):
            if response.status_code >= 500:
                severity = "error"
            elif response.status_code >= 400:
                severity = "warning"
            else:
                severity = "info"

            get_event_logger().log_event(
                source="backend",
                event_type="api_request",
                severity=severity,
                payload={
                    "message": f"{method} {path} -> {int(response.status_code)} in {duration_ms} ms",
                    "method": method,
                    "path": path,
                    "status": int(response.status_code),
                    "duration_ms": duration_ms,
                    "client_host": client_host,
                },
            )
        return response
    except Exception as exc:
        duration_ms = round((time.time() - started) * 1000.0, 2)
        client_host = request.client.host if request.client else None
        get_event_logger().log_event(
            source="backend",
            event_type="api_exception",
            severity="error",
            payload={
                "message": f"{method} {path} failed in {duration_ms} ms: {exc}",
                "method": method,
                "path": path,
                "duration_ms": duration_ms,
                "error": str(exc),
                "client_host": client_host,
            },
        )
        raise


# ==================== ROOT ENDPOINTS ====================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "service": "Jetson Nano Dashboard",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    cameras_health = {}
    for camera_id in get_camera_ids():
        camera = get_camera(camera_id, create_if_missing=False)
        cameras_health[camera_id] = {
            "is_open": camera.is_open if camera else False,
            "frame_count": camera.get_frame_count() if camera else 0,
        }

    return {
        "status": "healthy",
        "cameras": cameras_health,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/safety/heartbeat")
async def safety_heartbeat(payload: Dict[str, Any] = None):
    """Heartbeat from frontend to prove control UI loop is alive."""
    global last_frontend_heartbeat_ts, frontend_heartbeat_seen

    payload = payload or {}
    frontend_heartbeat_seen = True
    last_frontend_heartbeat_ts = time.time()

    get_event_logger().log_event(
        source="frontend",
        event_type="heartbeat",
        severity="info",
        payload={
            "message": "Frontend heartbeat received",
            "session_id": payload.get("session_id"),
            "connection_state": payload.get("connection_state"),
        },
    )
    return {"ok": True, "timestamp": datetime.now().isoformat()}


@app.post("/api/events/frontend")
async def ingest_frontend_events(payload: Dict[str, Any]):
    """Ingest frontend event batch for 2-minute rolling diagnostics."""
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events must be an array")

    event_log = get_event_logger()
    accepted = 0
    for item in events[:300]:
        if not isinstance(item, dict):
            continue
        event_log.log_event(
            source="frontend",
            event_type=str(item.get("type", "frontend_event")),
            severity=str(item.get("severity", "info")),
            payload={
                "message": item.get("message"),
                "meta": item.get("meta", {}),
                "at": item.get("at"),
                "session_id": payload.get("session_id"),
            },
        )
        accepted += 1

    return {
        "accepted": accepted,
        "retention_seconds": get_event_logger().get_meta().get("retention_seconds", 120),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/events/recent")
async def get_recent_events():
    """Get recent backend/frontend events retained in rolling 2-minute window."""
    event_log = get_event_logger()
    return {
        "meta": event_log.get_meta(),
        "events": event_log.get_recent_events(),
        "safety": {
            "frontend_heartbeat_seen": frontend_heartbeat_seen,
            "last_frontend_heartbeat_age_seconds": round(max(0.0, time.time() - last_frontend_heartbeat_ts), 2)
            if last_frontend_heartbeat_ts > 0
            else None,
            "last_control_activity_age_seconds": round(max(0.0, time.time() - last_control_activity_ts), 2),
            "watchdog_timeout_seconds": CONTROL_HEARTBEAT_TIMEOUT_SECONDS,
            "safety_reset_count": safety_reset_count,
        },
        "timestamp": datetime.now().isoformat(),
    }


# ==================== SYSTEM INFO ENDPOINTS ====================

@app.get("/api/system/info")
async def system_info():
    """Get system information"""
    cuda_info = check_cuda_availability()
    enabled_camera_ids = get_camera_ids()
    return {
        "device": "Jetson Nano",
        "cuda": cuda_info,
        "camera": {
            "enabled_camera_ids": enabled_camera_ids,
            "default_camera_id": _resolve_camera_id(CAMERA_DEFAULT_ID),
            "strict_camera_ids": bool(CAMERA_STRICT_CAMERA_IDS),
        },
        "media_gateway": _media_gateway_info(),
        "software": get_software_version_info(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/system/status")
async def system_status():
    """Get complete system status"""
    status = get_device_status()
    sensor_service = get_sensor_data_service()
    status["sensors"] = await run_in_threadpool(sensor_service.get_latest)
    status["timestamp"] = datetime.now().isoformat()
    return status


@app.get("/api/sensors/latest")
async def sensors_latest():
    """Get latest sensor readings from datalogger abstraction."""
    service = get_sensor_data_service()
    sensors = await run_in_threadpool(service.get_latest)
    return {
        "sensors": sensors,
        "simulation_enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sensors/history")
async def sensors_history(limit: int = 120, interval_minutes: int = 1, hours: int = 24):
    """Get recent sensor reading history for graph plotting."""
    service = get_sensor_data_service()
    history = await run_in_threadpool(
        service.get_history,
        limit,
        interval_minutes,
        hours,
    )
    return {
        "history": history,
        "count": len(history),
        "interval_minutes": interval_minutes,
        "hours": hours,
        "simulation_enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sensors/simulation")
async def sensors_simulation_state():
    """Get current simulation mode for sensor sampling."""
    service = get_sensor_data_service()
    return {
        "enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/sensors/simulation")
async def sensors_simulation_set(payload: dict):
    """Set simulation mode (true: simulated data, false: read from datalogger)."""
    service = get_sensor_data_service()
    enabled = bool(payload.get("enabled", False))
    service.set_simulation_enabled(enabled)
    return {
        "enabled": service.is_simulation_enabled(),
        "timestamp": datetime.now().isoformat()
    }


# ==================== EXPERIMENT ENDPOINTS (SLICE A) ====================

@app.get("/api/experiments/storage")
async def experiments_storage_info():
    """Show current storage resolution status (preferred USB path + fallback path)."""
    manager = _get_experiment_manager()

    try:
        info = await run_in_threadpool(manager.resolve_storage)
        return {
            **info,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/storage/health")
async def experiments_storage_health():
    """Get detailed experiment storage and disk utilization health."""
    manager = _get_experiment_manager()

    try:
        health = await run_in_threadpool(manager.get_storage_health)
        health["timestamp"] = datetime.now().isoformat()
        return health
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/experiments/storage/cleanup")
async def experiments_storage_cleanup(payload: Dict[str, Any] = None):
    """Trigger retention cleanup immediately (manual operator action)."""
    manager = _get_experiment_manager()
    payload = payload or {}

    retention_days = float(payload.get("retention_days", EXPERIMENTS_RETENTION_DAYS))
    max_total_gb = float(payload.get("max_total_gb", EXPERIMENTS_MAX_TOTAL_GB))
    low_watermark_gb = float(payload.get("low_watermark_gb", EXPERIMENTS_LOW_WATERMARK_GB))

    try:
        storage_result = await run_in_threadpool(
            manager.cleanup_storage,
            retention_days,
            max_total_gb,
            low_watermark_gb,
        )
        cache_result = await run_in_threadpool(_cleanup_playable_cache)
        return {
            "ok": True,
            "storage": storage_result,
            "playable_cache": cache_result,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/experiments/start")
async def experiments_start(payload: Dict[str, Any] = None):
    """Start an experiment run and begin per-run sensor CSV capture."""
    manager = _get_experiment_manager()

    payload = payload or {}
    payload["software"] = get_software_version_info()
    payload["camera_mapping"] = {
        camera_id: dict(CAMERA_PROFILES.get(camera_id, {})) for camera_id in get_camera_ids()
    }

    try:
        run = await run_in_threadpool(manager.start_run, payload)
        get_event_logger().log_event(
            source="backend",
            event_type="experiment_started",
            severity="info",
            payload={
                "run_id": run.get("run", {}).get("run_id"),
                "run_name": run.get("run", {}).get("run_name"),
            },
        )
        return {
            "ok": True,
            "active": run,
            "timestamp": datetime.now().isoformat(),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/experiments/stop")
async def experiments_stop(payload: Dict[str, Any] = None):
    """Stop active experiment run and finalize manifest."""
    manager = _get_experiment_manager()

    payload = payload or {}
    reason = str(payload.get("reason") or "manual_stop")

    try:
        summary = await run_in_threadpool(manager.stop_run, reason)
        get_event_logger().log_event(
            source="backend",
            event_type="experiment_stopped",
            severity="info",
            payload={
                "run_id": summary.get("run_id"),
                "sample_count": summary.get("sample_count"),
                "duration_seconds": summary.get("duration_seconds"),
                "stop_reason": reason,
            },
        )
        return {
            "ok": True,
            "summary": summary,
            "timestamp": datetime.now().isoformat(),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/active")
async def experiments_active():
    """Get current active experiment status."""
    manager = _get_experiment_manager()
    active = await run_in_threadpool(manager.get_active_run)
    return {
        **active,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/experiments/history")
async def experiments_history(limit: int = 50):
    """List recent experiment runs from preferred/fallback storage roots."""
    manager = _get_experiment_manager()

    try:
        history = await run_in_threadpool(manager.list_history, limit)
        return {
            **history,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/{run_id}/artifacts")
async def experiments_artifacts(run_id: str):
    """Get run artifacts and file inventory for a specific run id."""
    manager = _get_experiment_manager()

    try:
        artifacts = await run_in_threadpool(manager.get_artifacts, run_id)
        artifacts["timestamp"] = datetime.now().isoformat()
        return artifacts
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/experiments/{run_id}")
async def experiments_delete_run(run_id: str):
    """Delete an experiment run and reclaim disk space."""
    manager = _get_experiment_manager()

    try:
        result = await run_in_threadpool(manager.delete_run, run_id)
        get_event_logger().log_event(
            source="backend",
            event_type="experiment_deleted",
            severity="warning",
            payload={
                "run_id": run_id,
                "reclaimed_bytes": int(result.get("reclaimed_bytes", 0)),
            },
        )
        return {
            "ok": True,
            **result,
            "timestamp": datetime.now().isoformat(),
        }
    except RuntimeError as e:
        text = str(e)
        if "active run" in text.lower():
            raise HTTPException(status_code=409, detail=text)
        raise HTTPException(status_code=404, detail=text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/{run_id}/download")
async def experiments_download(run_id: str):
    """Download all run artifacts as a ZIP archive."""
    manager = _get_experiment_manager()

    try:
        if bool(EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_ACTIVE_RUN):
            active = await run_in_threadpool(manager.get_active_run)
            if bool((active or {}).get("active")):
                raise HTTPException(
                    status_code=409,
                    detail="Download is blocked while a run is active to reduce power/load spikes.",
                )

        if bool(EXPERIMENTS_DOWNLOAD_BLOCK_WHEN_LIVE_STREAMING):
            stream_activity = _download_live_stream_activity()
            stream_clients = int(stream_activity.get("mjpeg", 0)) + int(stream_activity.get("h264", 0)) + int(stream_activity.get("webrtc", 0))
            if stream_clients > 0:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Download is temporarily blocked while live streaming is active "
                        "(stop streams first to reduce power/load spikes)."
                    ),
                )

        acquired = False
        try:
            await asyncio.wait_for(download_archive_semaphore.acquire(), timeout=0.25)
            acquired = True
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=429,
                detail="Another archive is already being prepared. Please retry shortly.",
            )

        run_dir = await run_in_threadpool(manager.resolve_run_dir, run_id)

        os.makedirs(EXPERIMENTS_DOWNLOAD_ARCHIVE_DIR, exist_ok=True)
        temp_root = tempfile.mkdtemp(prefix="exp-download-", dir=EXPERIMENTS_DOWNLOAD_ARCHIVE_DIR)
        archive_base = os.path.join(temp_root, run_id)
        archive_path = await run_in_threadpool(shutil.make_archive, archive_base, "zip", run_dir)

        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="{0}.zip".format(run_id),
            background=BackgroundTask(shutil.rmtree, temp_root, True),
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'acquired' in locals() and acquired:
            download_archive_semaphore.release()


@app.get("/api/experiments/{run_id}/media")
async def experiments_media(run_id: str, path: str):
    """Serve a run artifact file for playback (e.g. MP4)."""
    manager = _get_experiment_manager()

    try:
        file_path = await run_in_threadpool(manager.resolve_run_file, run_id, path)
        mime, _ = mimetypes.guess_type(file_path)
        media_type = mime or "application/octet-stream"
        filename = os.path.basename(file_path)
        return FileResponse(file_path, media_type=media_type, filename=filename)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/{run_id}/media-playable")
async def experiments_media_playable(run_id: str, path: str):
    """Serve a browser-friendly playback file (H264 MP4 cache) for a run artifact."""
    manager = _get_experiment_manager()

    try:
        source_path = await run_in_threadpool(manager.resolve_run_file, run_id, path)
        playable_path = await run_in_threadpool(_ensure_playable_h264_mp4, source_path)
        return FileResponse(
            playable_path,
            media_type="video/mp4",
            filename=os.path.basename(playable_path),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CAMERA ENDPOINTS ====================

@app.get("/api/camera/info")
async def camera_info(camera_id: str = CAMERA_DEFAULT_ID, create_if_missing: bool = False):
    """Get camera information"""
    camera_id = _resolve_camera_id(camera_id)
    camera = get_camera(camera_id, create_if_missing=bool(create_if_missing))
    pipeline_info = camera.get_runtime_diagnostics() if camera else {}

    return {
        "camera_id": camera_id,
        "is_open": camera.is_open if camera else False,
        "frame_count": camera.get_frame_count() if camera else 0,
        "cuda_enabled": camera.cuda_enabled if camera else False,
        "performance": camera.get_performance_stats() if camera else None,
        "selected_pipeline": pipeline_info.get("selected_pipeline"),
        "selected_pipeline_mode": pipeline_info.get("selected_pipeline_mode"),
        "webrtc": {
            "available": is_webrtc_available(),
            "allowed_for_camera": _is_webrtc_allowed_for_camera(camera_id),
            "enabled_camera_ids": WEBRTC_ENABLED_CAMERA_IDS,
            "max_connections": WEBRTC_MAX_CONNECTIONS,
            "current_connections": _current_webrtc_connections(),
        },
        "h264_stream": _h264_stream_hint(camera_id),
        "media_gateway": _media_gateway_info(camera_id),
        "pipeline_diagnostics": pipeline_info,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/camera/devices/probe")
async def camera_devices_probe():
    """Probe connected camera devices and supported formats (GStreamer + V4L2 view)."""
    return {
        **probe_camera_devices_gstreamer(),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/camera/enabled")
async def camera_enabled():
    """Return enabled logical camera IDs and strict camera routing policy."""
    enabled_camera_ids = get_camera_ids()
    return {
        "enabled_camera_ids": enabled_camera_ids,
        "default_camera_id": _resolve_camera_id(CAMERA_DEFAULT_ID),
        "strict_camera_ids": bool(CAMERA_STRICT_CAMERA_IDS),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/camera/stop")
async def stop_camera(request: dict = None):
    """Request camera release after local client stop; safe for multi-client use."""
    request = request or {}
    camera_id = _resolve_camera_id(request.get("camera_id") or CAMERA_DEFAULT_ID)
    stream_session_id = request.get("stream_session_id")
    force = bool(request.get("force", False))
    cleared_sessions = 0

    # Explicitly unregister the caller's MJPEG session for immediate stats update.
    if stream_session_id:
        async with active_mjpeg_lock:
            _ensure_camera_session_bucket(camera_id)
            if stream_session_id in active_mjpeg_sessions[camera_id]:
                active_mjpeg_sessions[camera_id].discard(stream_session_id)

    if force:
        async with active_mjpeg_lock:
            _ensure_camera_session_bucket(camera_id)
            cleared_sessions = len(active_mjpeg_sessions[camera_id])
            active_mjpeg_sessions[camera_id].clear()

    # Give stream generators a short moment to observe disconnection and decrement counters.
    await asyncio.sleep(0.35)

    async with active_mjpeg_lock:
        _ensure_camera_session_bucket(camera_id)
        current_mjpeg_clients = len(active_mjpeg_sessions[camera_id])

    current_webrtc_connections = 0
    if is_webrtc_available():
        try:
            current_webrtc_connections = get_webrtc_manager_safe().get_connection_count()
        except Exception:
            current_webrtc_connections = 0

    camera = get_camera(camera_id)
    released = False
    if force:
        release_camera(camera_id)
        released = True
        camera = get_camera(camera_id, create_if_missing=False)
    elif camera is not None:
        released = camera.maybe_release_if_idle(
            idle_seconds=0,
            active_mjpeg_clients=current_mjpeg_clients,
            webrtc_connections=current_webrtc_connections,
        )
        if released:
            release_camera(camera_id)

    return {
        "camera_id": camera_id,
        "released": released,
        "stream_session_id": stream_session_id,
        "force": force,
        "cleared_sessions": int(cleared_sessions),
        "active_mjpeg_clients": current_mjpeg_clients,
        "webrtc_connections": current_webrtc_connections,
        "camera_open": bool(camera and camera.is_open),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/camera/recover")
async def recover_camera(request: dict = None):
    """Force camera release and reinitialize for manual operator recovery."""
    request = request or {}
    camera_id = _resolve_camera_id(request.get("camera_id") or CAMERA_DEFAULT_ID)
    reason = str(request.get("reason") or "manual_operator_recover")

    async with active_mjpeg_lock:
        _ensure_camera_session_bucket(camera_id)
        mjpeg_clients = len(active_mjpeg_sessions[camera_id])

    webrtc_connections = 0
    if is_webrtc_available():
        try:
            webrtc_connections = get_webrtc_manager_safe().get_connection_count()
        except Exception:
            webrtc_connections = 0

    camera = get_camera(camera_id)
    was_open = bool(camera and camera.is_open)
    forced_release = False

    if camera is not None:
        try:
            camera.release()
            forced_release = True
        except Exception:
            forced_release = False
        release_camera(camera_id)

    # Create a fresh camera instance.
    new_camera = get_camera(camera_id)
    recovered = bool(new_camera and new_camera.is_open)
    diagnostics = new_camera.get_runtime_diagnostics() if new_camera else {}

    get_event_logger().log_event(
        source="backend",
        event_type="camera_manual_recover",
        severity="info" if recovered else "warning",
        payload={
            "message": (
                "Manual camera recovery succeeded"
                if recovered
                else "Manual camera recovery failed"
            ),
            "reason": reason,
            "was_open": was_open,
            "forced_release": forced_release,
            "active_mjpeg_clients": mjpeg_clients,
            "active_webrtc_clients": webrtc_connections,
            "selected_source": diagnostics.get("selected_pipeline_source"),
        },
    )

    return {
        "camera_id": camera_id,
        "success": recovered,
        "reason": reason,
        "was_open": was_open,
        "forced_release": forced_release,
        "active_mjpeg_clients": mjpeg_clients,
        "active_webrtc_clients": webrtc_connections,
        "camera": {
            "is_open": recovered,
            "selected_source": diagnostics.get("selected_pipeline_source"),
            "selected_pipeline": diagnostics.get("selected_pipeline"),
            "recovery": diagnostics.get("recovery"),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/camera/prewarm")
async def prewarm_cameras(request: dict = None):
    """Prewarm selected cameras so Start Run can bring live view up faster."""
    request = request or {}
    requested_ids = request.get("camera_ids")

    if isinstance(requested_ids, list) and requested_ids:
        camera_ids = []
        for item in requested_ids:
            try:
                resolved = _resolve_camera_id(str(item))
            except Exception:
                continue
            if resolved not in camera_ids:
                camera_ids.append(resolved)
    else:
        camera_ids = list(get_camera_ids() or [_resolve_camera_id(CAMERA_DEFAULT_ID)])

    results = []
    started_at = time.time()
    for camera_id in camera_ids:
        async with active_mjpeg_lock:
            _ensure_camera_session_bucket(camera_id)
            active_clients = len(active_mjpeg_sessions[camera_id])

        if active_clients > 0:
            results.append(
                {
                    "camera_id": camera_id,
                    "success": True,
                    "skipped": True,
                    "reason": "active_mjpeg_clients",
                    "active_mjpeg_clients": active_clients,
                    "attempt": 0,
                    "bytes": 0,
                }
            )
            continue

        result = await run_in_threadpool(_prewarm_camera_sync, camera_id)
        result["active_mjpeg_clients"] = active_clients
        results.append(result)

    return {
        "ok": all(bool(item.get("success")) for item in results) if results else False,
        "results": results,
        "duration_ms": round((time.time() - started_at) * 1000.0, 2),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/camera/frame")
async def get_frame(camera_id: str = CAMERA_DEFAULT_ID):
    """Get single frame as JPEG"""
    camera_id = _resolve_camera_id(camera_id)
    camera = _get_or_recover_camera(camera_id)
    if not camera.is_open:
        raise HTTPException(
            status_code=503,
            detail="Camera is unavailable. Verify camera device mapping and try again."
        )

    success, jpeg_bytes = camera.get_jpeg_frame(quality=80)
    if not success or jpeg_bytes is None:
        raise HTTPException(status_code=503, detail="Failed to capture frame from camera")

    return StreamingResponse(
        iter([jpeg_bytes]),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/camera/stream")
async def stream_mjpeg(request: Request):
    """Stream video as MJPEG (fallback for low-latency needs)"""
    camera_id = _resolve_camera_id(request.query_params.get("camera_id") or CAMERA_DEFAULT_ID)
    startup_camera = _get_or_recover_camera(camera_id)
    if not startup_camera.is_open:
        raise HTTPException(
            status_code=503,
            detail="Camera is unavailable. Verify camera device mapping and retry stream."
        )

    async def generate():
        stream_session_id = request.query_params.get("sid") or str(uuid.uuid4())
        camera = get_camera(camera_id)
        profile = CAMERA_PROFILES.get(camera_id, {})
        jpeg_quality = int(profile.get("jpeg_quality") or getattr(camera, "jpeg_quality", 80) or 80)
        frame_interval = max(0.005, 1.0 / max(1, int(getattr(camera, "target_fps", 20))))
        consecutive_failures = 0
        last_success_ts = time.perf_counter()
        last_rebind_ts = 0.0
        rebind_cooldown_seconds = 1.5
        rebind_failure_threshold = 8

        async with active_mjpeg_lock:
            _ensure_camera_session_bucket(camera_id)
            active_mjpeg_sessions[camera_id].add(stream_session_id)
            logger.info(
                "MJPEG client connected sid=%s camera=%s. Active clients: %s",
                stream_session_id,
                camera_id,
                len(active_mjpeg_sessions[camera_id]),
            )
        
        try:
            while True:
                loop_started = time.perf_counter()
                if await request.is_disconnected():
                    logger.info("MJPEG client disconnected")
                    break

                success, jpeg_bytes = camera.get_jpeg_frame(quality=jpeg_quality)
                if not success or jpeg_bytes is None:
                    consecutive_failures += 1

                    # Self-heal camera binding when stream has been starved for too long.
                    now_ts = time.perf_counter()
                    if (
                        consecutive_failures >= rebind_failure_threshold
                        and (now_ts - last_rebind_ts) >= rebind_cooldown_seconds
                    ):
                        logger.warning(
                            "MJPEG stream recovery: rebinding camera=%s sid=%s failures=%s",
                            camera_id,
                            stream_session_id,
                            consecutive_failures,
                        )
                        last_rebind_ts = now_ts
                        release_camera(camera_id)
                        camera = get_camera(camera_id)

                    # Keep connection alive while recovering to reduce black-screen churn.
                    if (now_ts - last_success_ts) > 1.0:
                        yield b": keepalive\r\n\r\n"

                    await asyncio.sleep(0.05)
                    continue

                consecutive_failures = 0
                last_success_ts = time.perf_counter()

                # Yield MJPEG boundary
                yield b"--frame\r\n"
                yield b"Content-Type: image/jpeg\r\n"
                yield b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                yield jpeg_bytes
                yield b"\r\n"

                # Pace stream relative to target FPS while minimizing added latency.
                elapsed = time.perf_counter() - loop_started
                sleep_for = frame_interval - elapsed
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

        except asyncio.CancelledError:
            logger.info("MJPEG stream cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in MJPEG stream: {e}")
        finally:
            async with active_mjpeg_lock:
                _ensure_camera_session_bucket(camera_id)
                active_mjpeg_sessions[camera_id].discard(stream_session_id)
                remaining_mjpeg_clients = len(active_mjpeg_sessions[camera_id])
                logger.info(
                    "MJPEG client disconnected sid=%s camera=%s. Active clients: %s",
                    stream_session_id,
                    camera_id,
                    remaining_mjpeg_clients,
                )

            # Do not hard-release camera immediately on disconnect. Brief browser/network
            # reconnects can otherwise cause visible black-screen churn. Camera lifecycle
            # is handled by explicit `/api/camera/stop` and the idle watchdog.
            if remaining_mjpeg_clients == 0:
                logger.info(
                    "No active MJPEG clients for %s; keeping camera warm for fast reconnect.",
                    camera_id,
                )

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/camera/stream_h264")
async def stream_h264(request: Request):
    """Experimental H.264 fragmented MP4 live stream (Phase 2 trial path)."""
    if not CAMERA_H264_STREAM_ENABLED:
        raise HTTPException(status_code=503, detail="H.264 live stream mode is disabled")

    input_mode = str(CAMERA_H264_INPUT_MODE or "usb").strip().lower()
    if input_mode == "rtsp" and not CAMERA_H264_RTSP_URL:
        raise HTTPException(
            status_code=400,
            detail="CAMERA_H264_INPUT_MODE=rtsp requires CAMERA_H264_RTSP_URL",
        )
    if input_mode == "file":
        if not CAMERA_H264_FILE_PATH:
            raise HTTPException(
                status_code=400,
                detail="CAMERA_H264_INPUT_MODE=file requires CAMERA_H264_FILE_PATH",
            )
        if not os.path.exists(CAMERA_H264_FILE_PATH):
            raise HTTPException(
                status_code=400,
                detail="CAMERA_H264_FILE_PATH does not exist: {0}".format(CAMERA_H264_FILE_PATH),
            )

    camera_id = _resolve_camera_id(request.query_params.get("camera_id") or CAMERA_DEFAULT_ID)
    h264_profile = _get_h264_stream_profile(camera_id)

    if not bool(h264_profile.get("enabled", CAMERA_H264_STREAM_ENABLED)):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "h264_disabled_for_camera",
                "camera_id": camera_id,
                "message": "H.264 stream disabled for this camera",
            },
        )

    cooldown_remaining_ms = _h264_cooldown_remaining_ms(camera_id)
    if cooldown_remaining_ms > 0:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "h264_temporarily_cooled_down",
                "camera_id": camera_id,
                "retry_after_ms": cooldown_remaining_ms,
                "message": "H.264 temporarily cooled down after repeated failures. Retry later.",
            },
        )

    async def generate_h264():
        stream_session_id = request.query_params.get("sid") or str(uuid.uuid4())
        if _can_use_h264_gst_pipeline(h264_profile):
            cmd, encoder = _build_h264_stream_gst_command(camera_id, h264_profile)
            stream_backend = "gstreamer"
        else:
            cmd, encoder = _build_h264_stream_ffmpeg_command(camera_id, h264_profile)
            stream_backend = "ffmpeg"
        proc = None
        bytes_streamed = 0
        started_at = time.time()

        async with active_mjpeg_lock:
            _ensure_h264_session_bucket(camera_id)
            active_h264_sessions[camera_id].add(stream_session_id)
            logger.info(
                "H264 client connected sid=%s camera=%s mode=%s backend=%s encoder=%s. Active H264 clients: %s",
                stream_session_id,
                camera_id,
                input_mode,
                stream_backend,
                encoder,
                len(active_h264_sessions[camera_id]),
            )

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )

            while True:
                if await request.is_disconnected():
                    break

                chunk = await run_in_threadpool(proc.stdout.read, 64 * 1024)
                if chunk:
                    bytes_streamed += len(chunk)
                    yield chunk
                    continue

                poll_rc = proc.poll()
                if poll_rc is not None:
                    break

                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("H264 stream error (camera=%s): %s", camera_id, e)
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            async with active_mjpeg_lock:
                _ensure_h264_session_bucket(camera_id)
                active_h264_sessions[camera_id].discard(stream_session_id)
                logger.info(
                    "H264 client disconnected sid=%s camera=%s. Active H264 clients: %s",
                    stream_session_id,
                    camera_id,
                    len(active_h264_sessions[camera_id]),
                )

            elapsed = max(0.0, time.time() - started_at)
            if bytes_streamed > 0:
                _h264_record_success(camera_id)
            elif elapsed <= float(CAMERA_H264_FAIL_EARLY_SECONDS):
                _h264_record_failure(camera_id, reason="h264_early_disconnect")
            else:
                _h264_record_failure(camera_id, reason="h264_no_bytes_streamed")

    return StreamingResponse(
        generate_h264(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== GPIO ENDPOINTS ====================

@app.get("/api/gpio/status")
async def gpio_status():
    """Get GPIO status"""
    gpio = get_gpio_controller()
    return {
        "gpio": gpio.get_outputs_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/gpio/outputs")
async def gpio_outputs_status():
    """Get all configured GPIO outputs and current states."""
    gpio = get_gpio_controller()
    return {
        "gpio": gpio.get_outputs_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/on")
async def gpio_output_on(output_name: str):
    """Turn a named GPIO output on."""
    gpio = get_gpio_controller()
    result = gpio.turn_output_on(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_on",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' set to ON ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/off")
async def gpio_output_off(output_name: str):
    """Turn a named GPIO output off."""
    gpio = get_gpio_controller()
    result = gpio.turn_output_off(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_off",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' set to OFF ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/outputs/{output_name}/toggle")
async def gpio_output_toggle(output_name: str):
    """Toggle a named GPIO output."""
    gpio = get_gpio_controller()
    result = gpio.toggle_output(output_name)
    state = gpio.get_outputs_state()

    get_event_logger().log_event(
        source="backend",
        event_type="gpio_output_toggle",
        severity="info" if result else "warning",
        payload={
            "message": f"GPIO output '{output_name}' toggled ({'success' if result else 'failed'})",
            "output": output_name,
            "result": bool(result),
            "state": state.get("outputs", {}).get(output_name),
        },
    )

    return {
        "success": result,
        "output": output_name,
        "gpio": state,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/on")
async def gpio_on():
    """Legacy endpoint: maps to Exhaust Blower ON."""
    gpio = get_gpio_controller()
    result = gpio.led_on()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/off")
async def gpio_off():
    """Legacy endpoint: maps to Exhaust Blower OFF."""
    gpio = get_gpio_controller()
    result = gpio.led_off()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/gpio/toggle")
async def gpio_toggle():
    """Legacy endpoint: maps to Exhaust Blower toggle."""
    gpio = get_gpio_controller()
    result = gpio.toggle_led()
    
    return {
        "success": result,
        "gpio": gpio.get_led_state(),
        "timestamp": datetime.now().isoformat()
    }


# ==================== VFD ENDPOINTS ====================

@app.get("/api/vfd/status")
async def vfd_status():
    """Get VFD control availability and cached runtime state."""
    vfd = get_vfd_controller()
    return {
        "success": True,
        "vfd": vfd.get_status(),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/vfd/run")
async def vfd_run(payload: Dict[str, Any]):
    """Set VFD run state (true=start, false=stop)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    run = payload.get("run")
    if not isinstance(run, bool):
        raise HTTPException(status_code=400, detail="'run' must be boolean")

    vfd = get_vfd_controller()
    result = await run_in_threadpool(vfd.set_run_state, run)
    state = vfd.get_status()

    get_event_logger().log_event(
        source="backend",
        event_type="vfd_run_state_set",
        severity="info" if result else "warning",
        payload={
            "message": f"VFD run state set to {'RUN' if run else 'STOP'} ({'success' if result else 'failed'})",
            "run": bool(run),
            "result": bool(result),
            "vfd_state": state,
        },
    )

    return {
        "success": bool(result),
        "vfd": state,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/vfd/speed")
async def vfd_speed(payload: Dict[str, Any]):
    """Set VFD speed setpoint in Hz."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    speed_hz = payload.get("speed_hz")

    vfd = get_vfd_controller()
    result = await run_in_threadpool(vfd.set_speed_hz, speed_hz)
    state = vfd.get_status()
    ok = bool(result.get("success"))

    severity = "info" if ok else "warning"
    get_event_logger().log_event(
        source="backend",
        event_type="vfd_speed_set",
        severity=severity,
        payload={
            "message": (
                f"VFD speed set to {result.get('speed_hz')} Hz"
                if ok
                else f"VFD speed set failed: {result.get('error')}"
            ),
            "result": result,
            "vfd_state": state,
        },
    )

    if not ok and result.get("error") == "speed_out_of_range":
        raise HTTPException(status_code=400, detail=result)

    return {
        "success": ok,
        "result": result,
        "vfd": state,
        "timestamp": datetime.now().isoformat(),
    }


# ==================== WEBRTC ENDPOINTS ====================

@app.post("/api/webrtc/offer")
async def webrtc_offer(request: dict):
    """Handle WebRTC offer"""
    if not is_webrtc_available():
        raise HTTPException(
            status_code=503,
            detail="WebRTC is unavailable on this target build. Use /api/camera/stream (MJPEG) instead."
        )

    camera_id = _resolve_camera_id((request or {}).get("camera_id") or CAMERA_DEFAULT_ID)
    if not _is_webrtc_allowed_for_camera(camera_id):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "webrtc_disabled_for_camera",
                "camera_id": camera_id,
                "enabled_camera_ids": WEBRTC_ENABLED_CAMERA_IDS,
                "message": "WebRTC disabled for this camera. Use MJPEG streaming instead.",
            },
        )

    current_connections = _current_webrtc_connections()
    if WEBRTC_MAX_CONNECTIONS > 0 and current_connections >= WEBRTC_MAX_CONNECTIONS:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "webrtc_capacity_reached",
                "camera_id": camera_id,
                "max_connections": WEBRTC_MAX_CONNECTIONS,
                "current_connections": current_connections,
                "message": "WebRTC capacity reached. Use MJPEG streaming or retry later.",
            },
        )

    try:
        from aiortc import RTCSessionDescription
        from .webrtc import CameraVideoTrack
        
        manager = get_webrtc_manager_safe()
        pc = manager.create_peer_connection()
        
        # Handle the offer
        offer = RTCSessionDescription(
            sdp=request["sdp"],
            type=request["type"]
        )
        
        await pc.setRemoteDescription(offer)

        # Add the camera track after setting the remote description
        pc.addTrack(CameraVideoTrack(camera_id=camera_id))
        
        # Create answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
    except Exception as e:
        logger.exception("WebRTC error")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication"""
    await handle_websocket_connection(websocket)


# ==================== STATUS ENDPOINTS ====================

@app.get("/api/stats")
async def get_stats():
    """Get application statistics"""
    per_camera = {}
    total_mjpeg = 0
    total_h264 = 0
    for camera_id in get_camera_ids():
        cam = get_camera(camera_id, create_if_missing=False)
        async with active_mjpeg_lock:
            _ensure_camera_session_bucket(camera_id)
            mjpeg_clients = len(active_mjpeg_sessions[camera_id])
            _ensure_h264_session_bucket(camera_id)
            h264_clients = len(active_h264_sessions[camera_id])
            total_mjpeg += mjpeg_clients
            total_h264 += h264_clients
        per_camera[camera_id] = {
            "camera_frames": cam.get_frame_count() if cam else 0,
            "camera_performance": cam.get_performance_stats() if cam else None,
            "active_mjpeg_clients": mjpeg_clients,
            "active_h264_clients": h264_clients,
            "h264_stream": _h264_stream_hint(camera_id),
        }

    default_camera = get_camera(_resolve_camera_id(CAMERA_DEFAULT_ID), create_if_missing=False)
    webrtc_connections = 0
    if is_webrtc_available():
        try:
            webrtc_mgr = get_webrtc_manager_safe()
            webrtc_connections = webrtc_mgr.get_connection_count()
        except Exception:
            webrtc_connections = 0
    
    return {
            "camera_frames": default_camera.get_frame_count() if default_camera else 0,
            "camera_performance": default_camera.get_performance_stats() if default_camera else None,
        "camera_idle_release_seconds": CAMERA_IDLE_RELEASE_SECONDS,
            "active_mjpeg_clients": total_mjpeg,
            "active_h264_clients": total_h264,
        "experiment_video_runtime": _get_experiment_manager().get_video_runtime_metrics(),
        "h264_stream_profile": {
            "enabled": bool(CAMERA_H264_STREAM_ENABLED),
            "input_mode": str(CAMERA_H264_INPUT_MODE or "usb"),
            "use_gstreamer": bool(CAMERA_H264_STREAM_USE_GSTREAMER),
            "rtsp_configured": bool(CAMERA_H264_RTSP_URL),
            "file_configured": bool(CAMERA_H264_FILE_PATH),
            "failure_threshold": int(CAMERA_H264_FAIL_COOLDOWN_THRESHOLD),
            "failure_cooldown_base_ms": int(CAMERA_H264_FAIL_COOLDOWN_BASE_SECONDS) * 1000,
            "failure_cooldown_max_ms": int(CAMERA_H264_FAIL_COOLDOWN_MAX_SECONDS) * 1000,
            "per_camera": {
                camera_id: _h264_stream_hint(camera_id).get("profile", {})
                for camera_id in get_camera_ids()
            },
        },
        "media_gateway_profile": _media_gateway_info(),
        "webrtc_connections": webrtc_connections,
            "cameras": per_camera,
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=API_DEBUG,
        log_level=LOG_LEVEL.lower()
    )

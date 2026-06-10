# Jetson Nano WebRTC Dashboard — Deployment (JetPack 4.6)

This document consolidates the old and current deployment notes into one practical runbook.
It is focused on Jetson Nano with JetPack 4.6 (L4T r32.7.1 / Python 3.6).

## 1) Executive summary (current reality)

### Verified working

- Docker compose stack starts on older Jetson compose versions.
- Frontend is served by Nginx at `http://<JETSON_IP>/`.
- API proxy works via frontend (`/api/system/status`).
- Backend health endpoint works (`/health`).
- Native setup script installs apt + pip dependencies successfully for JP4.6.

### Known blocker in current test environment

- Camera capture still fails in both native and docker runs:
    - `GET /api/camera/frame` returns `500`
    - `GET /api/camera/stream` may connect but return no bytes before timeout
- Observed error:
    - `VIDEOIO ERROR: V4L2: Pixel format of incoming image is unsupported by OpenCV`

So UI + API integration is healthy, while camera format/runtime compatibility remains the open issue.

---

## 2) Prerequisites

- Jetson Nano with JetPack 4.6
- USB camera visible as `/dev/video*` (usually `/dev/video0`)
- Docker + docker-compose installed on Jetson
- Project cloned on Jetson host

Example path used during validation:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
```

---

## 3) Dependency model for JP4.6

JP4.6 dependencies are centralized in:

- `backend/requirements.jetpack46.txt`

This file contains:

- apt packages as commented `# apt: ...` lines (OpenCV/GStreamer/v4l2/etc.)
- pip packages as normal requirement lines (FastAPI/Uvicorn/etc.)

`backend/scripts/setup_jetpack46_native.sh` parses `# apt:` entries for system install and then installs pip dependencies from the same file.

---

## 4) Native backend deployment (recommended for JP4.6 debugging)

### Step A — Setup native environment

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard/backend
chmod +x scripts/setup_jetpack46_native.sh scripts/run_jetpack46_native.sh
./scripts/setup_jetpack46_native.sh
```

What it does:

- installs apt deps from `requirements.jetpack46.txt` (`# apt:` lines)
- creates `.venv-jp46` with `--system-site-packages` (so apt `cv2` is visible)
- installs pip deps from `requirements.jetpack46.txt`

### Step B — Run backend natively

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard/backend
./scripts/run_jetpack46_native.sh
```

Important built-in behavior:

- kills stale `/dev/video0` lock holders before start
- kills stale uvicorn process before start
- verifies `cv2` exists in active venv
- releases camera handle on read/exception failure paths

### Optional runtime tuning before launch

```bash
export CAMERA_SOURCE=usb
export CAMERA_ACCELERATION=auto
export CAMERA_USB_STARTUP_PROBE=true
export CAMERA_CSI_SENSOR_ID=0
# export GST_PIPELINE_OVERRIDE='v4l2src device=/dev/video0 ! ... ! appsink'
```

### Step C — Validate native backend

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/system/status
curl -sS http://127.0.0.1:8000/api/system/info
curl -sS -o /tmp/native_frame.jpg -w "http=%{http_code} size=%{size_download}\n" http://127.0.0.1:8000/api/camera/frame
curl -sS --max-time 4 http://127.0.0.1:8000/api/camera/stream | head -c 120 | xxd -g 1
```

---

## 5) Docker full-stack deployment (frontend + backend)

### Step A — Build and run

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d --build
docker-compose ps
```

### Step B — Validate stack

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS -I http://127.0.0.1/
curl -sS http://127.0.0.1/api/system/status
curl -sS -o /tmp/docker_frame.jpg -w "http=%{http_code} size=%{size_download}\n" http://127.0.0.1/api/camera/frame
curl -sS --max-time 4 http://127.0.0.1/api/camera/stream | head -c 120 | xxd -g 1
```

### Docker log commands (service names matter)

```bash
docker-compose config --services
docker-compose logs --tail=200 jetson-backend
docker-compose logs --tail=200 jetson-frontend
```

---

## 6) Frontend behavior and WebRTC fallback

- Frontend tries WebRTC first.
- On JP4.6 core profile (without aiortc stack), `POST /api/webrtc/offer` may return `503`.
- In that case frontend should fallback to MJPEG (`/api/camera/stream`).

Quick check:

```bash
curl -X POST http://127.0.0.1:8000/api/webrtc/offer \
    -H "Content-Type: application/json" \
    -d '{"sdp":"test","type":"offer"}'
```

---

## 7) Camera lock cleanup (when webcam LED stays ON)

Run on Jetson host:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans || true
ids=$(docker ps -aq --filter name=jetson-nano); [ -n "$ids" ] && docker rm -f $ids || true
pkill -f 'uvicorn app.main:app' || true
pkill -f 'gst-launch' || true
pkill -f 'python.*camera' || true
pkill -f 'ffmpeg' || true
fuser -k /dev/video0 || true
fuser -v /dev/video0 || true
```

If `fuser -v /dev/video0` shows nothing, the device is released.

---

## 8) Troubleshooting playbook

### A) Camera fails (`/api/camera/frame` = 500)

```bash
ls -l /dev/video*
v4l2-ctl --list-formats-ext -d /dev/video0
sudo fuser -v /dev/video0
tail -n 200 /tmp/native_backend.log
docker-compose logs --tail=200 jetson-backend
```

### B) Frontend works but API fails

- Verify Nginx proxy in `frontend/nginx.conf`
    - `/api` should be plain HTTP proxy (no forced upgrade)
    - `/ws` should keep websocket upgrade headers

### C) CUDA appears unavailable

```bash
python3 - <<'PY'
import cv2
print('opencv:', cv2.__version__)
print('has cv2.cuda:', hasattr(cv2, 'cuda'))
if hasattr(cv2, 'cuda'):
        print('cuda devices:', cv2.cuda.getCudaEnabledDeviceCount())
PY
```

Note: On JP4.6, CPU fallback is expected on many builds.

---

## 9) Compose compatibility notes for old Jetson setups

- Compose file intentionally uses legacy-compatible schema (`version: '3.3'`).
- Avoid unsupported keys on very old compose versions (for example `runtime` and some extended healthcheck options).

---

## 10) Smoke checklist

- [ ] Native setup completes
- [ ] Native backend starts
- [ ] Docker stack starts
- [ ] Frontend root (`/`) returns 200
- [ ] Frontend proxy (`/api/system/status`) returns JSON
- [ ] `/health` returns healthy
- [ ] Camera frame endpoint returns JPEG (currently blocked in latest validation)
- [ ] MJPEG stream returns bytes (currently blocked in latest validation)

---

## 11) Deployment-relevant files

- `docker-compose.yml`
- `backend/Dockerfile.jetpack46`
- `backend/requirements.jetpack46.txt`
- `backend/scripts/setup_jetpack46_native.sh`
- `backend/scripts/run_jetpack46_native.sh`
- `backend/app/camera.py`
- `frontend/nginx.conf`

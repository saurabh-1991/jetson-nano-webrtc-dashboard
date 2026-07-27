# Jetson Nano WebRTC Dashboard — Deployment (JetPack 4.6)

This document consolidates the old and current deployment notes into one practical runbook.
It is focused on Jetson Nano with JetPack 4.6 (L4T r32.7.1 / Python 3.6).

## Beginner quick-start for a new local network

If you are deploying this project in a **new LAN/router** for the first time, start here:

- [Doc/new-local-network-deployment.md](Doc/new-local-network-deployment.md)

That guide includes screenshots, copyable commands, and fallback steps for `.local` vs numeric IP access.

## 1) Executive summary (current reality)

### Verified working

- Docker compose stack starts on older Jetson compose versions.
- Frontend is served by Nginx at `http://<JETSON_IP>/`.
- API proxy works via frontend (`/api/system/status`).
- Backend health endpoint works (`/health`).
- Native setup script installs apt + pip dependencies successfully for JP4.6.
- Camera endpoints are working in latest validation:
- `GET /api/camera/frame` returns `200` with JPEG bytes
- `GET /api/camera/stream` returns `200` with MJPEG stream bytes
- Remote access from another laptop on LAN is working:
- `http://<JETSON_IP>/`
- `http://<JETSON_IP>/api/camera/frame`
- `http://<JETSON_IP>/api/camera/stream`

### Current caveats

- On JP4.6 core profile, WebRTC may be unavailable and `POST /api/webrtc/offer` may return `503`.
- This is expected when `aiortc` path is not active; frontend should fallback to MJPEG automatically.
- OpenCV CUDA may be unavailable on some JP4.6 builds (`cv2.cuda` missing); CPU fallback is expected.

So UI + API + camera streaming is healthy with MJPEG fallback, even when WebRTC/CUDA are unavailable.

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

### Branch for power-run automation

Power-run automation (autologin + boot autostart + static IP scripts) is maintained on branch:

- `poc_demo_v1.1.0`

Pull that branch on Jetson:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
git fetch origin
git checkout -B poc_demo_v1.1.0 origin/poc_demo_v1.1.0
git reset --hard origin/poc_demo_v1.1.0
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

### Step A — First-time build (or after Dockerfile/dependency changes)

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d --build
docker-compose ps
```

### Step A.1 — Regular start/stop (no rebuild, recommended for day-to-day use)

Use this path for normal restart cycles. It reuses already-built images and avoids creating new dangling image layers.

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d
docker-compose ps
```

### Step A.1b — Dual-camera + NVIDIA runtime backend (compose-compatible workaround)

If your Jetson `docker-compose` version does not support `runtime: nvidia` in YAML,
use the helper script below after normal compose startup.

It keeps frontend/services in compose, but recreates backend with `--runtime nvidia`
while preserving dual-camera env settings.

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/run_backend_with_nvidia_runtime.sh
./scripts/run_backend_with_nvidia_runtime.sh
```

Validation expected:

- backend runtime prints `runtime=nvidia`
- plugin probe shows `nvjpegdec=OK` and `nvvidconv=OK`
- `/health` and `/api/camera/enabled` return healthy with both cameras enabled

### Step A.1c — Optional HW-accel trial backend image (safe, non-default)

Use this only when you want to test a different backend base image for potential
OpenCV GStreamer/CUDA availability, while keeping the regular deployment path untouched.

This script builds `backend/Dockerfile.jetpack46.hwtrial` and runs backend with
`--runtime nvidia` as a drop-in replacement.

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/run_backend_with_nvidia_runtime_hwtrial.sh
./scripts/run_backend_with_nvidia_runtime_hwtrial.sh
```

Validation expected from script output:

- `runtime=nvidia`
- OpenCV probe should report: `gstreamer_declared_yes True` (desired).
- OpenCV probe should report: `has_cuda_mod True` and `cuda_devices > 0` (desired).
- `/api/camera/info` should trend to `hardware_accel.opencv_gstreamer_enabled=true`.
- `/api/camera/info` should trend to `hardware_accel.hardware_pipeline_eligible=true`.

### Step A.2 — Cleanup dangling images (when `<none>` images accumulate)

If you previously ran many `--build` cycles, old untagged layers will accumulate. Clean them safely with:

```bash
# Remove dangling images only (safe)
docker image prune -f

# Optional: remove build cache as well
docker builder prune -f

# Optional: preview disk usage
docker system df
```

Automation note:

- `docker-compose.yml` now includes a `docker-prune` service.
- It automatically runs `docker image prune -f` and `docker builder prune -f`.
- Default interval is every `3600` seconds.
- To tune interval, set env before running compose:

```bash
export AUTO_PRUNE_INTERVAL_SECONDS=7200
docker-compose up -d
```

- To stop auto-prune temporarily:

```bash
docker-compose stop docker-prune
```

### Step A0 — One-command plug-and-play setup (autologin + boot start + static IP)

This applies the power-run automation scripts introduced in `poc_demo_v1.1.0`.

Before running, edit `scripts/powerrun.config` with your custom network values
(`ETH_IP`, `ETH_GATEWAY`, `ETH_DNS`, optional Wi-Fi values, and mDNS hostname keys).

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/powerrun_apply_all.sh scripts/setup_powerrun_jetson.sh scripts/configure_static_ip_nmcli.sh

# 1) Edit once
nano scripts/powerrun.config

# 2) Apply config-driven automation
sudo ./scripts/powerrun_apply_all.sh

# Example: root autologin + fixed Ethernet IP
sudo ./scripts/powerrun_apply_all.sh \
    --project-dir /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
    --autologin-user root --enable-root-account --root-password 'ChangeMeNow!' \
    --eth-device eth0 --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8

# Optional: add Wi-Fi fixed IP in same run
sudo ./scripts/powerrun_apply_all.sh \
    --project-dir /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
    --autologin-user root --enable-root-account --root-password 'ChangeMeNow!' \
    --eth-device eth0 --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8 \
    --wifi-device wlan0 --wifi-ssid "YourRouterSSID" --wifi-password "YourRouterPassword" \
    --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8
```

After setup, reboot once and use fixed URL:

- `http://192.168.1.50/` (Ethernet example)
- `http://192.168.1.60/` (Wi-Fi example)
- `http://jetson-dashboard.local/` (mDNS hostname, recommended for DHCP-changing networks)

### Step A0.1 — Config file key reference (`scripts/powerrun.config`)

| Key | Purpose | Example |
| --- | --- | --- |
| `AUTOLOGIN_USER` | Desktop autologin user | `root` / `saurabh` |
| `ENABLE_AUTOLOGIN` | Enable LightDM autologin | `true` |
| `ENABLE_ROOT_ACCOUNT` | If `true`, script sets root password | `false` |
| `ROOT_PASSWORD` | Root password (required when enabling root account) | `ChangeMeNow!` |
| `START_ON_BOOT` | Enable systemd service at boot | `true` |
| `START_NOW` | Start service immediately during setup | `true` |
| `ENABLE_MDNS` | Enable Avahi/mDNS LAN discovery | `true` |
| `MDNS_HOSTNAME` | Hostname exposed as `http://<name>.local/` | `jetson-dashboard` |
| `ETH_DEVICE` | Ethernet interface | `eth0` |
| `ETH_IP` | Static Ethernet IPv4 CIDR | `192.168.1.50/24` |
| `ETH_GATEWAY` | Ethernet gateway | `192.168.1.1` |
| `ETH_DNS` | Ethernet DNS list | `192.168.1.1,8.8.8.8` |
| `WIFI_DEVICE` | Wi-Fi interface | `wlan0` |
| `WIFI_SSID` | Wi-Fi SSID | `MyRouter` |
| `WIFI_PASSWORD` | Wi-Fi password | `MyPass123` |
| `WIFI_IP` | Static Wi-Fi IPv4 CIDR | `192.168.1.60/24` |
| `WIFI_GATEWAY` | Wi-Fi gateway | `192.168.1.1` |
| `WIFI_DNS` | Wi-Fi DNS list | `192.168.1.1,8.8.8.8` |

### Step A0.2 — Post-reboot verification checklist

Run on Jetson host:

```bash
systemctl status jetson-dashboard.service --no-pager
docker-compose ps
nmcli -p -f GENERAL.DEVICE,IP4.ADDRESS,IP4.GATEWAY device show eth0
nmcli -p -f GENERAL.DEVICE,IP4.ADDRESS,IP4.GATEWAY device show wlan0
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/stats
systemctl status avahi-daemon --no-pager
hostnamectl status --static
bash ./scripts/check_lan_access.sh
```

Run from laptop/phone on same LAN:

```bash
curl -sS http://<STATIC_IP>/api/system/status
curl -sS -o /tmp/frame.jpg -w "http=%{http_code} size=%{size_download}\n" http://<STATIC_IP>/api/camera/frame
# If mDNS is enabled
curl -sS http://jetson-dashboard.local/api/system/status
```

### Step A0.4 — LAN discovery strategy for remote/no-serial deployments

When board IP may change after reboot (DHCP), use mDNS as the primary access method:

1. Keep `ENABLE_MDNS="true"` in `scripts/powerrun.config`
2. Set a stable `MDNS_HOSTNAME` (for example `jetson-dashboard`)
3. Re-apply once: `sudo ./scripts/powerrun_apply_all.sh`
4. Access from LAN using `http://<MDNS_HOSTNAME>.local/`

This removes day-to-day dependency on knowing the numeric IP.

Windows note: if `.local` does not resolve, install Bonjour services, or use static IP fallback.

Safety note: static-IP script now skips interface updates when the target NIC is unavailable
(for example `eth0` unplugged while using Wi-Fi), so one-command remote setup won't fail
just because an unused interface is down.

### Step A0.5 — Remote connection steps in local environment (Jetson ↔ Laptop)

Follow this exact flow for local-LAN remote access after power-on.

On Jetson (one-time prep):

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
nano scripts/powerrun.config
sudo ./scripts/powerrun_apply_all.sh
sudo reboot
```

On Jetson (after reboot, local check):

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
bash ./scripts/check_lan_access.sh
```

On laptop/phone (same router/LAN):

```bash
# Preferred hostname access
curl -sS http://jetson-dashboard.local/api/system/status

# IPv4 fallback if .local resolution is unavailable
curl -sS http://<JETSON_IPV4>/api/system/status
```

Open dashboard in browser:

- `http://jetson-dashboard.local/` (preferred)
- `http://<JETSON_IPV4>/` (fallback)

Remote shell note:

- If SSH to `.local` times out in your LAN stack, use IPv4 for SSH.
- Keep `.local` for operator browser access.

### Step A0.6 — Power-cycle simulation checklist (validated)

Use this when you want to verify plug-and-play behavior before field deployment.

On Jetson (simulate restart behavior):

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d
docker-compose ps
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1/api/system/status
```

From laptop/phone on same LAN (operator view):

```bash
curl -sS http://jetson-dashboard.local/
curl -sS http://jetson-dashboard.local/api/system/status
```

Pass criteria:

- backend health returns `{"status":"healthy",...}`
- frontend and API proxy are reachable on `.local`
- containers are `Up` in `docker-compose ps`

### Step A0.3 — Rollback to DHCP (if needed)

If static IP causes connectivity problems:

```bash
# Replace with actual active connection names if different
nmcli connection show
sudo nmcli connection modify "jetson-eth0-static" ipv4.method auto
sudo nmcli connection up "jetson-eth0-static"

# Optional Wi-Fi rollback
sudo nmcli connection modify "jetson-wlan0-<SSID>" ipv4.method auto
sudo nmcli connection up "jetson-wlan0-<SSID>"
```

If you need to stop boot auto-start temporarily:

```bash
sudo systemctl disable jetson-dashboard.service
sudo systemctl stop jetson-dashboard.service
```

### Step A (fast path) — Run existing images without rebuild

Use this when images are already built on the Jetson and you only want to start/recreate containers.

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d
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

## 7) How to close/stop deployment cleanly

Use one of the following depending on how you started the app.

### A) If running via Docker Compose (recommended)

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker ps --filter name=jetson-nano
```

Expected: no `jetson-nano-*` containers are running.

### B) If running native dashboard script

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/stop_native_dashboard.sh
./scripts/stop_native_dashboard.sh
```

This stops native backend/frontend processes and removes fallback frontend dev container if used.

### C) Verify camera is released before unplug/redeploy

```bash
fuser -v /dev/video0 || true
```

If no PID is shown, camera device is released.

---

## 8) Camera lock cleanup (when webcam LED stays ON)

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

## 9) Troubleshooting playbook

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

## 10) Compose compatibility notes for old Jetson setups

- Compose file intentionally uses legacy-compatible schema (`version: '3.3'`).
- Avoid unsupported keys on very old compose versions (for example `runtime` and some extended healthcheck options).
- Very old Jetson `docker-compose` (Python2 era) may appear to hang in startup checks; wait for command completion and confirm final state with `docker-compose ps`.

---

## 11) Smoke checklist

- [x] Native setup completes
- [x] Native backend starts
- [x] Docker stack starts
- [x] Frontend root (`/`) returns 200
- [x] Frontend proxy (`/api/system/status`) returns JSON
- [x] `/health` returns healthy
- [x] Camera frame endpoint returns JPEG
- [x] MJPEG stream returns bytes

---

## 12) Deployment-relevant files

- `docker-compose.yml`
- `backend/Dockerfile.jetpack46`
- `backend/requirements.jetpack46.txt`
- `backend/scripts/setup_jetpack46_native.sh`
- `backend/scripts/run_jetpack46_native.sh`
- `backend/app/camera.py`
- `frontend/nginx.conf`

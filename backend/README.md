# Jetson Nano Dashboard Backend

FastAPI backend for real-time video streaming, GPIO control, and device monitoring on a Jetson Nano.

## Overview

This backend provides:

- WebRTC streaming from the Jetson Nano camera (when `aiortc` stack is available)
- MJPEG fallback camera streaming
- GPIO REST API for LED control
- WebSocket real-time status updates
- System and application status endpoints
- CUDA-aware OpenCV processing
- JetPack 4.6 (Python 3.6) compatibility profile

It is designed to support the dashboard frontend at `frontend/` via `/api/*` endpoints.

## Architecture

```text
USB Webcam
    ↓
GStreamer Pipeline (NVJPEG decoder)
    ↓
OpenCV CUDA Processing
    ↓
FastAPI Backend
    ├─ WebRTC Video Stream (aiortc)
    ├─ GPIO REST APIs (Jetson.GPIO)
    ├─ WebSocket Events
    └─ MJPEG Fallback Stream
    ↓
React Frontend Dashboard
```

## Features

- **Real-time Video Streaming** via WebRTC (optional on JP4.6 profile)
- **MJPEG fallback stream** for browser compatibility or lower complexity
- **GPIO control** for LED on/off/toggle via REST
- **System status APIs** for camera, CUDA, GPIO, and WebSocket status
- **WebSocket support** for real-time updates and command events
- **CUDA-aware processing** with GPU acceleration if available
- **Hardware integration** through GStreamer and OpenCV

## Backend Folder Structure

```text
backend/
  Dockerfile
  README.md
  requirements.txt
  app/
    __init__.py
    camera.py
    config.py
    gpio_control.py
    main.py
    webrtc.py
    websocket.py
  venv/
```

## Installation

### Prerequisites

- Jetson Nano with JetPack installed
- Python 3.8+ for default profile, or Python 3.6 for `requirements.jetpack46.txt`
- CUDA and cuDNN installed for GPU acceleration
- GStreamer 1.0 and plugins

### Install system packages (Jetson Nano)

```bash
sudo apt update
sudo apt install -y \
  python3-pip \
  python3-opencv \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav
```

### Install Python dependencies

```bash
cd backend
pip3 install -r requirements.txt
```

For JetPack 4.6 / Python 3.6 profile:

```bash
cd backend
pip3 install -r requirements.jetpack46.txt
```

## Configuration

Edit `backend/app/config.py` to customize the backend behavior.

Key settings:

- `CAMERA_DEVICE` — e.g. `/dev/video0`
- `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`
- `CAMERA_SOURCE` — `usb` or `csi`
- `CAMERA_ACCELERATION` — `auto` (default, hardware-first), `hardware`, or `compat`
- `CAMERA_USB_STARTUP_PROBE` — enable startup probing/reordering for USB candidates (`true`/`false`)
- `CAMERA_CSI_SENSOR_ID` — CSI sensor index used by `nvarguscamerasrc`
- `GST_PIPELINE_OVERRIDE` — full custom GStreamer capture pipeline override
- `CUDA_ENABLED` — enable/disable CUDA processing
- `PROCESSING_SCALE` — resize dimensions for frame processing
- `GPIO_LED_PIN`, `GPIO_BUTTON_PIN`
- `API_HOST`, `API_PORT`
- `STUN_SERVERS` — used by WebRTC

## Run the Backend

### Development mode

```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production mode

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Using Docker

```bash
cd backend
docker build -t jetson-nano-backend .
docker run --privileged -p 8000:8000 jetson-nano-backend
```

## HTTP API Endpoints

### Root / health

- `GET /` — simple service health check
- `GET /health` — camera health details and timestamp

### System

- `GET /api/system/info` — device info and CUDA availability
- `GET /api/system/status` — full system status payload
- `GET /api/stats` — backend stats including frame count and WebRTC connection count

### Camera

- `GET /api/camera/info` — camera open state, frame count, CUDA status, selected pipeline, and startup probe diagnostics
- `GET /api/camera/frame` — single JPEG frame response
- `GET /api/camera/stream` — MJPEG live stream fallback

### GPIO

- `GET /api/gpio/status` — current LED and GPIO availability
- `POST /api/gpio/on` — turn LED on
- `POST /api/gpio/off` — turn LED off
- `POST /api/gpio/toggle` — toggle LED state

### WebRTC

- `POST /api/webrtc/offer` — accept browser SDP offer and return SDP answer
  - On JP4.6 compatibility profile (without `aiortc`), this endpoint returns `503` and frontend should fallback to `GET /api/camera/stream`.

### WebSocket

- `WS /ws` — persistent socket for real-time commands and status

## WebSocket Message Protocol

The backend accepts JSON messages over `/ws`:

- `{ "type": "ping" }` → responds with `{ "type": "pong" }`
- `{ "type": "status_request" }` → responds with `{ "type": "device_status", "data": {...} }`
- `{ "type": "gpio_on" }` → turns LED on and broadcasts `{ "type": "gpio_state_changed", "data": {...} }`
- `{ "type": "gpio_off" }` → turns LED off and broadcasts `{ "type": "gpio_state_changed", "data": {...} }`

The backend also broadcasts device status to all connected WebSocket clients every 5 seconds.

## Module Responsibilities

### `app/config.py`
Application settings and constants.

- Camera and GStreamer parameters
- CUDA processing options
- GPIO pin configuration
- API host/port and logging
- WebRTC STUN servers

### `app/camera.py`
Camera capture and processing.

- `CameraCapture`: initializes capture via GStreamer
- `get_frame()`: returns a BGR frame
- `CUDA`-based resize via `cv2.cuda`
- fallback to CPU processing when CUDA fails
- `check_cuda_availability()`: inspects OpenCV CUDA device count

### `app/gpio_control.py`
GPIO state management.

- tries `Jetson.GPIO`, falls back to mock mode if unavailable
- `GPIOController` with methods:
  - `led_on()`
  - `led_off()`
  - `toggle_led()`
  - `get_led_state()`
  - `cleanup()`

### `app/webrtc.py`
WebRTC stream handling.

- `CameraVideoTrack`: builds video frames from camera capture
- `WebRTCManager`: manages active `RTCPeerConnection` instances
- creates peer connections with STUN config and cleans up disconnected peers

### `app/websocket.py`
WebSocket management.

- `WebSocketManager`: accepts connections and broadcasts JSON
- processes incoming messages
- periodic device status broadcast every 5 seconds
- reports active connection count

### `app/main.py`
FastAPI app entry point.

- configures CORS for frontend access
- defines all REST and WebSocket routes
- starts background status broadcast task on startup
- cleans up camera and GPIO on shutdown

## Testing the Backend

### Verify Python dependencies

```bash
cd backend
pip3 install -r requirements.txt
```

### Verify WebRTC endpoint

```bash
curl -X POST http://localhost:8000/api/webrtc/offer \
  -H "Content-Type: application/json" \
  -d '{"sdp": "", "type": "offer"}'
```

### Verify GPIO endpoints

```bash
curl http://localhost:8000/api/gpio/status
curl -X POST http://localhost:8000/api/gpio/on
curl -X POST http://localhost:8000/api/gpio/off
curl -X POST http://localhost:8000/api/gpio/toggle
```

### Verify system endpoints

```bash
curl http://localhost:8000/api/system/status
curl http://localhost:8000/api/stats
```

### Test WebSocket (simple example)

Use a WebSocket client and connect to:

```text
ws://localhost:8000/ws
```

Then send JSON messages like:

```json
{ "type": "status_request" }
```

## Debugging

### Check CUDA availability

```bash
python3 -c "import cv2; print(cv2.cuda.getCudaEnabledDeviceCount())"
```

### Check GStreamer support

```bash
gst-inspect-1.0 | grep nv
```

### Check camera device

```bash
ls /dev/video*
gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! xvimagesink
```

## JetPack 4.6 (Jetson Nano) build using Dockerfile.jetpack46

If you're deploying to Jetson Nano with JetPack 4.6 (L4T r32.7.1 / Python 3.6), use the provided Dockerfile `Dockerfile.jetpack46` and `requirements.jetpack46.txt`. This Dockerfile relies on system OpenCV / numpy packages from apt and installs a conservative set of Python packages suitable for Python 3.6.

### Recommended: Native Jetson venv deployment (no container)

Use JetPack-provided OpenCV/GStreamer libraries directly and install app Python deps in a venv.

```bash
cd backend
chmod +x scripts/setup_jetpack46_native.sh
./scripts/setup_jetpack46_native.sh

source .venv-jp46/bin/activate

# Camera source options:
#   CAMERA_SOURCE=usb (default)
#   CAMERA_SOURCE=csi
export CAMERA_SOURCE=usb

# Acceleration mode options:
#   CAMERA_ACCELERATION=auto      (default, tries HW path first then compatibility fallback)
#   CAMERA_ACCELERATION=hardware  (prefer HW path)
#   CAMERA_ACCELERATION=compat    (prefer compatibility/CPU decode path)
export CAMERA_ACCELERATION=hardware

# USB startup probe (format-aware + quick performance check):
#   true  => auto-reorder MJPEG/YUY2/UYVY candidates by measured startup speed
#   false => use static fallback order from config
export CAMERA_USB_STARTUP_PROBE=true

# CSI sensor-id (applies when CAMERA_SOURCE=csi)
export CAMERA_CSI_SENSOR_ID=0

# Optional pipeline override:
# export GST_PIPELINE_OVERRIDE='v4l2src device=/dev/video0 ! ... ! appsink drop=1 max-buffers=1 sync=false'

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Important native note:
- Create venv with `--system-site-packages` (handled by setup script), otherwise apt-installed `cv2` may be invisible inside the venv.
- Ensure `/dev/video0` is not occupied by another process/container while testing native mode.

Build and run (on the Jetson Nano host):

```bash
cd backend
docker build -f Dockerfile.jetpack46 -t jetson-nano-backend:jp46 .
docker run --runtime nvidia --privileged -p 8000:8000 --device /dev:/dev jetson-nano-backend:jp46
```

### Verify NVIDIA acceleration inside container (Jetson host)

After starting the container, validate runtime and accelerated libraries:

```bash
# 1) Confirm NVIDIA runtime is active and env capabilities are present
docker inspect jetson-nano-backend --format '{{json .HostConfig.Runtime}} {{json .Config.Env}}'

# 2) Check Jetson release info inside container
docker exec -it jetson-nano-backend bash -lc "cat /etc/nv_tegra_release"

# 3) Verify NVIDIA GStreamer plugins are present
docker exec -it jetson-nano-backend bash -lc "gst-inspect-1.0 nvvidconv && gst-inspect-1.0 nvjpegdec"

# 4) Verify OpenCV CUDA visibility
docker exec -it jetson-nano-backend bash -lc "python3 -c 'import cv2; print(cv2.cuda.getCudaEnabledDeviceCount())'"
```

If step (3) or (4) fails, the container will run but fallback to CPU/VIC paths depending on stage.

Notes:
- Do not install `opencv-python` / `numpy` from pip on the Jetson; use the system packages (`python3-opencv`, `python3-numpy`) provided by apt.
- On JetPack 4.6, the stock FFmpeg stack often conflicts with current `av`/`aiortc` builds. For reliable deployment, the JP4.6 profile runs with MJPEG + REST/WebSocket and treats WebRTC as optional.
- In this mode, `POST /api/webrtc/offer` returns `503` with guidance to use `GET /api/camera/stream`.
- If you maintain a custom FFmpeg toolchain and matching `av`/`aiortc`, you can add those packages back to `requirements.jetpack46.txt`.

### View logs

```bash
# Direct uvicorn logs
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### GPIO permissions

```bash
sudo usermod -a -G gpio $USER
```

## Troubleshooting

### Camera not detected
- Verify the camera is connected and listed under `/dev/video*`
- Confirm the GStreamer pipeline can open the device
- If using a USB webcam, try `gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! xvimagesink`

### CUDA issues
- Make sure JetPack and CUDA are installed and compatible with OpenCV
- Run `tegrastats` to verify GPU activity
- If CUDA fails, the backend falls back to CPU processing automatically
- If `/api/system/info` reports `cuda_available: false`, check OpenCV build flags with:
  - `python3 -c "import cv2; print('CUDA' in cv2.getBuildInformation()); print(cv2.getBuildInformation())"`
- In containers, ensure GPU runtime is enabled (JetPack 4.x typically requires `--runtime nvidia`).

### WebRTC connection fails
- Ensure the frontend and backend are on the same host or proxy setup
- Confirm `/api/webrtc/offer` returns a valid SDP answer
- Check browser console for ICE / connection errors

### WebSocket issues
- Confirm client connects to `ws://localhost:8000/ws`
- Check backend logs for accept or broadcast errors
- The backend broadcasts status every 5 seconds when clients are connected

## Performance Optimization

### GStreamer pipeline
- `CAMERA_ACCELERATION=auto` (default) tries hardware JPEG decode (`nvjpegdec`) + `nvvidconv` first.
- If camera output is raw YUV, backend also tries NVIDIA-style hardware conversion paths:
  - `v4l2src ... format=UYVY ! nvvidconv`
  - `v4l2src ... format=YUY2 ! nvvidconv`
- If the hardware pipeline fails for a specific USB camera, backend falls back to compatibility pipeline (`jpegdec`) to keep streaming alive.
- For strict hardware preference, set `CAMERA_ACCELERATION=hardware`.
- With `CAMERA_USB_STARTUP_PROBE=true`, backend performs a small startup probe:
  - detects advertised USB formats via `v4l2-ctl --list-formats-ext` when available
  - opens each candidate briefly and scores frame-read throughput
  - reorders candidates so the fastest successful pipeline is tried first

NVIDIA references used for this implementation:
- Jetson Linux Developer Guide — *Accelerated GStreamer* (camera capture with `nvarguscamerasrc`, `v4l2src`, `nvvidconv`)
- Jetson Linux Developer Guide — *Camera Software Development Solution* (API matrix and V4L2/ARGUS guidance)
- Jetson Linux Developer Guide — *Hardware Acceleration in the WebRTC Framework* (H.264 HW encoding and YUY2→I420/NV12 conversion note)

### CUDA processing
- Attempts GPU-accelerated resize with `cv2.cuda`
- Performs one-time CUDA capability detection at startup to avoid per-frame CUDA probe overhead
- Falls back to CPU resize if CUDA is unavailable or fails

## CUDA / GPU Acceleration on Jetson Nano (Recommended Path)

Yes — you can use Jetson GPU/CUDA cores to optimize this app. Practical guidance:

1. **Use hardware capture/convert path (already configured):**
  - The default `GST_PIPELINE` uses `nvjpegdec` + `nvvidconv`.
2. **Use an OpenCV build with CUDA support:**
  - If OpenCV is not CUDA-enabled, backend will run CPU fallback.
3. **Run containers with NVIDIA runtime on JetPack 4.x:**
  - Use `--runtime nvidia` and device access (`--device /dev:/dev` or explicit camera devices).
4. **Tune frame size/FPS for Nano constraints:**
  - Lower `CAMERA_WIDTH`, `CAMERA_HEIGHT`, and/or `CAMERA_FPS` when thermal or CPU bound.
5. **Verify at runtime:**
  - `GET /api/system/info` for CUDA device status.
  - `tegrastats` for GR3D utilization while streaming.

### Why CUDA may appear unused

- OpenCV package in the running environment may not be compiled with CUDA.
- Container may not have GPU runtime passthrough.
- Pipeline may rely mostly on VIC/NVDEC acceleration rather than CUDA cores for some stages.
- MJPEG encoding path (`cv2.imencode`) is CPU-oriented by design.

### WebRTC
- Uses STUN servers for ICE negotiation
- Handles connection state changes and cleans up failed peers

## Security Notes

- Use HTTPS/TLS in production
- Restrict CORS origins instead of allowing `*`
- Use authenticated access for GPIO and WebSocket control
- Store sensitive configuration in environment variables

## Production Deployment

### Docker

```bash
cd backend
docker build -t jetson-nano-backend .
docker run --privileged -p 8000:8000 jetson-nano-backend
```

### Docker Compose

If you have a full stack compose file, run:

```bash
docker-compose up -d
```

For JetPack 4.6, ensure compose backend service includes:

- `dockerfile: Dockerfile.jetpack46`
- `runtime: nvidia`
- `NVIDIA_VISIBLE_DEVICES=all`
- `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility`

## Resource Usage

Typical Jetson Nano usage for a live stream:
- CPU: 15-35%
- GPU: 20-50%
- Memory: 200-500MB
- Network: 2-5 Mbps for 720p video

## Notes

- The backend uses the same `/api/*` base path expected by the React frontend.
- If `Jetson.GPIO` is not installed, the backend will still run in mock GPIO mode.
- `camera.py` tries a GStreamer capture pipeline first and falls back to `cv2.VideoCapture(0)`.
- Frontend supports WebRTC first, then automatically falls back to MJPEG when `/api/webrtc/offer` returns `503` or WebRTC setup fails.
- Frontend backend target is configurable via `VITE_API_BASE_URL` (for example `http://192.168.1.20:8000` when testing against Jetson).
- The backend is readiness-ready for Docker deployment, but hardware access requires `--privileged` mode on Jetson Nano.

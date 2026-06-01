# Jetson Nano Dashboard Backend

FastAPI backend for real-time video streaming, GPIO control, and device monitoring on a Jetson Nano.

## Overview

This backend provides:

- WebRTC streaming from the Jetson Nano camera
- MJPEG fallback camera streaming
- GPIO REST API for LED control
- WebSocket real-time status updates
- System and application status endpoints
- CUDA-aware OpenCV processing

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

- **Real-time Video Streaming** via WebRTC
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
- Python 3.8+ or compatible
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

## Configuration

Edit `backend/app/config.py` to customize the backend behavior.

Key settings:

- `CAMERA_DEVICE` — e.g. `/dev/video0`
- `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`
- `GST_PIPELINE` — GStreamer capture pipeline
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

- `GET /api/camera/info` — camera open state, frame count, CUDA status
- `GET /api/camera/frame` — single JPEG frame response
- `GET /api/camera/stream` — MJPEG live stream fallback

### GPIO

- `GET /api/gpio/status` — current LED and GPIO availability
- `POST /api/gpio/on` — turn LED on
- `POST /api/gpio/off` — turn LED off
- `POST /api/gpio/toggle` — toggle LED state

### WebRTC

- `POST /api/webrtc/offer` — accept browser SDP offer and return SDP answer

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

## JetPack 4.6 (Jetson Nano) build using Dockerfile.jetpack46

If you're deploying to Jetson Nano with JetPack 4.6 (L4T r32.7.1 / Python 3.6), use the provided Dockerfile `Dockerfile.jetpack46` and `requirements.jetpack46.txt`. This Dockerfile relies on system OpenCV / numpy packages from apt and installs a conservative set of Python packages suitable for Python 3.6.

Build and run (on the Jetson Nano host):

```bash
cd backend
docker build -f Dockerfile.jetpack46 -t jetson-nano-backend:jp46 .
docker run --privileged -p 8000:8000 --device /dev:/dev jetson-nano-backend:jp46
```

Notes:
- Do not install `opencv-python` / `numpy` from pip on the Jetson; use the system packages (`python3-opencv`, `python3-numpy`) provided by apt.
- `aiortc` / `av` may need to be built on-device for ARM; iterate on `requirements.jetpack46.txt` and then pin working versions with `pip3 freeze`.
```

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
- Uses hardware JPEG decode via `nvjpegdec`
- Converts frames using `nvvidconv`
- Provides a low-latency capture path for the Jetson Nano

### CUDA processing
- Attempts GPU-accelerated resize with `cv2.cuda`
- Falls back to CPU resize if CUDA is unavailable or fails

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
- The frontend currently uses only the WebRTC `/api/webrtc/offer` path for live streaming, but the MJPEG and frame endpoints are available as alternatives.
- The backend is readiness-ready for Docker deployment, but hardware access requires `--privileged` mode on Jetson Nano.

This starts:
- FastAPI backend on port 8000
- React frontend on port 80
- Nginx reverse proxy
- Full monitoring with health checks

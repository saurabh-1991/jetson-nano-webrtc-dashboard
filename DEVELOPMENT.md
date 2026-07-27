# Jetson Nano Dashboard - Development Setup

This guide helps you get started with development and testing.

## Local Development

### 1. Backend Setup (Jetson Nano or Linux)

```bash
# Navigate to backend
cd backend

# Create virtual environment (optional)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip3 install -r requirements.txt

# Run development server
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will be available at `http://localhost:8000`.

### 2. Frontend Setup

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will be available at `http://localhost:5173`.

## Testing

### Manual API Testing

```bash
# Health check
curl http://localhost:8000/health

# Get system info
curl http://localhost:8000/api/system/info

# Turn LED on
curl -X POST http://localhost:8000/api/gpio/on

# Get GPIO status
curl http://localhost:8000/api/gpio/status

# Get MJPEG stream
curl http://localhost:8000/api/camera/stream
```

### Browser Testing

1. Open `http://localhost:5173` in your browser
2. Test video streaming connection
3. Test GPIO controls
4. Monitor device status

## Docker Development

### Build Images

```bash
# Backend
docker build -t jetson-backend ./backend

# Frontend
docker build -t jetson-frontend ./frontend
```

### Run with Docker Compose

```bash
docker-compose up -d
```

Access:
- API: `http://localhost:8000`
- Frontend: `http://localhost:80`

### View Logs

```bash
docker-compose logs -f jetson-backend
docker-compose logs -f jetson-frontend
```

## Jetson Nano (JetPack 4.6) Deployment and Validation

This section is the recommended path for deploying and testing on a real Jetson Nano running JetPack 4.6 (Python 3.6 / L4T r32.7.1).

### 1. Prerequisites on Jetson

- Jetson Nano flashed with JetPack 4.6
- Python 3.6 and `python3-venv`
- GStreamer + OpenCV packages from JetPack
- Camera connected and visible under `/dev/video*`
- Ensure no other app/container is holding the camera device (`/dev/video0`)

### 2. Native backend setup (venv, no Docker)

Run on Jetson host:

```bash
cd backend
chmod +x scripts/setup_jetpack46_native.sh
./scripts/setup_jetpack46_native.sh
```

### 3. Run backend natively with GStreamer pipeline

Run on Jetson host:

```bash
cd backend
source .venv-jp46/bin/activate

# Camera source options:
#   CAMERA_SOURCE=usb (default, USB webcam)
#   CAMERA_SOURCE=csi (CSI camera via nvarguscamerasrc)
export CAMERA_SOURCE=usb

# Pipeline acceleration mode:
#   CAMERA_ACCELERATION=auto      (default, hardware-first then compatibility fallback)
#   CAMERA_ACCELERATION=hardware  (prefer hardware pipeline)
#   CAMERA_ACCELERATION=compat    (prefer compatibility pipeline)
export CAMERA_ACCELERATION=hardware

# CSI camera sensor-id (used only when CAMERA_SOURCE=csi)
export CAMERA_CSI_SENSOR_ID=0

# Optional custom pipeline override:
# export GST_PIPELINE_OVERRIDE='v4l2src device=/dev/video0 ! ... ! appsink drop=1 max-buffers=1 sync=false'

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Validate backend health and JetPack runtime behavior

```bash
# Basic health
curl http://localhost:8000/health

# Full status
curl http://localhost:8000/api/system/status

# CUDA diagnostics
curl http://localhost:8000/api/system/info

# JP4.6 core mode behavior (expected 503 if aiortc is not installed)
curl -X POST http://localhost:8000/api/webrtc/offer \
  -H "Content-Type: application/json" \
  -d '{"sdp":"test","type":"offer"}'
```

Expected behavior in JP4.6 core profile:

- `/health` and `/api/system/status` return success.
- `/api/system/info` typically indicates CUDA diagnostics (`reason` field explains fallback state).
- `/api/webrtc/offer` may return `503` when WebRTC dependencies are unavailable.
- Frontend should then use MJPEG fallback stream (`/api/camera/stream`).

### 5. Configure frontend to target Jetson backend

In `frontend/.env`:

```bash
VITE_API_BASE_URL=http://<JETSON_IP>:8000
```

Then run frontend:

```bash
cd frontend
npm install
npm run dev
```

### 6. Validate end-to-end UI behavior

1. Open `http://localhost:5173`
2. Click **Start Stream**
3. Confirm one of the following:
   - WebRTC connects successfully, or
   - UI switches to **Mode: MJPEG** with fallback notice
4. Validate GPIO controls and device status updates

### 6.1 Validate dual-camera endpoints (current default behavior)

```bash
# Enabled logical cameras
curl http://localhost:8000/api/camera/enabled

# Per-camera health snapshots
curl "http://localhost:8000/api/camera/info?camera_id=cam1"
curl "http://localhost:8000/api/camera/info?camera_id=cam2"

# Per-camera single-frame checks
curl -o /tmp/cam1.jpg "http://localhost:8000/api/camera/frame?camera_id=cam1"
curl -o /tmp/cam2.jpg "http://localhost:8000/api/camera/frame?camera_id=cam2"
```

### 7. Verify NVIDIA acceleration inside container

### 7. Verify JetPack-native acceleration on host

```bash
# Verify NVIDIA GStreamer plugins
gst-inspect-1.0 nvvidconv
gst-inspect-1.0 nvjpegdec

# Verify OpenCV runtime capabilities
python3 - <<'PY'
import cv2
print('opencv', cv2.__version__)
print('has cv2.cuda:', hasattr(cv2, 'cuda'))
if hasattr(cv2, 'cuda'):
  print('cuda device count:', cv2.cuda.getCudaEnabledDeviceCount())
print('has cv2.cuda_GpuMat:', hasattr(cv2, 'cuda_GpuMat'))
print('has cv2.cuda.GpuMat:', hasattr(cv2.cuda, 'GpuMat') if hasattr(cv2, 'cuda') else False)
PY

# Monitor GPU utilization while streaming
tegrastats
```

### Optional: container path (if needed)

```bash
cd backend
docker build -f Dockerfile.jetpack46 -t jetson-nano-backend:jp46 .
docker run --runtime nvidia --privileged -p 8000:8000 --device /dev:/dev jetson-nano-backend:jp46

# Verify container runtime/plugins
docker inspect jetson-nano-backend --format '{{json .HostConfig.Runtime}}'
docker exec -it jetson-nano-backend bash -lc "gst-inspect-1.0 nvvidconv && gst-inspect-1.0 nvjpegdec"
```

### Recommended JP4.6 compose-compatible runtime path

On older Jetson compose versions, use the canonical helper after compose startup:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose up -d
./scripts/run_backend_with_nvidia_runtime.sh
```

This preserves the compose network while recreating backend with `--runtime nvidia` and the expected network alias for frontend API proxying.

Notes:

- Hardware-accelerated GStreamer elements (`nvjpegdec`, `nvvidconv`) should be present.
- OpenCV CUDA device count can still be `0` if that build lacks usable CUDA runtime/device support.
- MJPEG encoding path is primarily CPU-based even when parts of the pipeline are hardware accelerated.

## Plug-and-Play Power-Run Setup (Auto Login + Auto Start + Static IP)

Use this section when you want the Jetson board to boot and serve the dashboard automatically with predictable URLs.

### One-command setup (recommended)

Use the wrapper below to apply boot automation + static IP in one command.

Before running, edit this config file with your custom IP values:

`scripts/powerrun.config`

Example keys to update:

- `ETH_IP`, `ETH_GATEWAY`, `ETH_DNS`
- `WIFI_IP`, `WIFI_GATEWAY`, `WIFI_DNS`
- `WIFI_SSID`, `WIFI_PASSWORD`
- `AUTOLOGIN_USER`, `ENABLE_ROOT_ACCOUNT`, `ROOT_PASSWORD`

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/powerrun_apply_all.sh scripts/setup_powerrun_jetson.sh scripts/configure_static_ip_nmcli.sh

# Edit config first
nano scripts/powerrun.config

# Run using config defaults
sudo ./scripts/powerrun_apply_all.sh

# Root autologin + Ethernet static IP example
sudo ./scripts/powerrun_apply_all.sh \
  --project-dir /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
  --autologin-user root --enable-root-account --root-password 'ChangeMeNow!' \
  --eth-device eth0 --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8

# Add Wi-Fi static IP in the same run (optional)
sudo ./scripts/powerrun_apply_all.sh \
  --project-dir /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
  --autologin-user root --enable-root-account --root-password 'ChangeMeNow!' \
  --eth-device eth0 --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8 \
  --wifi-device wlan0 --wifi-ssid "YourRouterSSID" --wifi-password "YourRouterPassword" \
  --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8
```

### What needs to be done

1. Configure desktop autologin (you asked for root user).
2. Install a systemd service that starts Docker Compose on boot.
3. Configure static IPv4 on Ethernet and/or Wi-Fi so URL stays fixed.

### 1) Configure boot automation (autologin + auto-start services)

Run on Jetson host:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
chmod +x scripts/setup_powerrun_jetson.sh scripts/configure_static_ip_nmcli.sh

# Option A (recommended security): autologin with non-root user (e.g., saurabh)
sudo AUTOLOGIN_USER=saurabh ENABLE_AUTOLOGIN=true ENABLE_ROOT_ACCOUNT=false \
  PROJECT_DIR=/home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
  ./scripts/setup_powerrun_jetson.sh

# Option B (requested): root autologin
# NOTE: this is insecure for production networks.
sudo AUTOLOGIN_USER=root ENABLE_AUTOLOGIN=true ENABLE_ROOT_ACCOUNT=true ROOT_PASSWORD='ChangeMeNow!' \
  PROJECT_DIR=/home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
  ./scripts/setup_powerrun_jetson.sh
```

This installs and enables:

- LightDM autologin config: `/etc/lightdm/lightdm.conf.d/90-jetson-dashboard-autologin.conf`
- systemd service: `/etc/systemd/system/jetson-dashboard.service`

The service runs:

- `docker-compose -f <project>/docker-compose.yml up -d` on boot

### 2) Configure static IP (Ethernet and/or Wi-Fi)

#### Ethernet static IP

```bash
sudo ./scripts/configure_static_ip_nmcli.sh \
  --eth-device eth0 \
  --eth-ip 192.168.1.50/24 \
  --eth-gateway 192.168.1.1 \
  --eth-dns 192.168.1.1,8.8.8.8
```

#### Wi-Fi static IP

```bash
sudo ./scripts/configure_static_ip_nmcli.sh \
  --wifi-device wlan0 \
  --wifi-ssid "YourRouterSSID" \
  --wifi-password "YourRouterPassword" \
  --wifi-ip 192.168.1.60/24 \
  --wifi-gateway 192.168.1.1 \
  --wifi-dns 192.168.1.1,8.8.8.8
```

After this, open dashboard with fixed URL:

- `http://192.168.1.50/` (Ethernet example)
- `http://192.168.1.60/` (Wi-Fi example)

Docker containers use host port mapping (`80`, `8000`), so static host IP gives stable browser URL.

### 3) Validation after reboot

```bash
systemctl status jetson-dashboard.service --no-pager
docker-compose ps
curl http://127.0.0.1/health || curl http://127.0.0.1:8000/health
```

From another device on LAN:

```bash
curl http://<STATIC_IP>/api/system/status
```

## Debugging

### Backend Debugging

1. Check logs:
```bash
# Docker
docker logs jetson-nano-backend -f

# Direct
# Watch uvicorn output in terminal
```

2. Enable debug mode in `backend/app/config.py`:
```python
API_DEBUG = True
```

3. Check camera:
```bash
python3 << 'EOF'
import cv2
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
print(f"Frame shape: {frame.shape if ret else 'No frame'}")
cap.release()
EOF
```

### Frontend Debugging

1. Open browser DevTools (F12)
2. Check Console for errors
3. Check Network tab for API calls
4. Use React DevTools extension

## Performance Monitoring

### GPU Monitoring
```bash
# On Jetson Nano
watch -n 1 tegrastats
```

### CPU/Memory
```bash
# Watch system resources
watch -n 1 'ps aux | grep uvicorn'
```

### Network
```bash
# Monitor network usage
iftop
# or
nethogs
```

## Common Issues

### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000

# Kill it
kill -9 <PID>
```

### CUDA Not Available
```bash
# Check CUDA status
python3 -c "import cv2; print(cv2.cuda.getCudaEnabledDeviceCount())"

# If 0, reinstall CUDA packages
sudo apt install python3-opencv-cuda
```

### Camera Not Found
```bash
# List cameras
ls /dev/video*

# Test with GStreamer
gst-launch-1.0 v4l2src device=/dev/video0 ! xvimagesink
```

### GPIO Permission Denied
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER
# Logout and login or restart
```

## Environment Variables

Use the existing `.env` file in the project root (or copy from `.env.example` if you need to reset values):

```bash
# Backend
CAMERA_SOURCE=usb
CAMERA_ACCELERATION=auto
CAMERA_CSI_SENSOR_ID=0
GST_PIPELINE_OVERRIDE=

# Frontend
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Production Deployment

### On Jetson Nano

1. Clone repository
2. Configure `backend/app/config.py`
3. Build Docker images
4. Run with Docker Compose
5. Configure nginx reverse proxy
6. Add SSL certificates
7. Set up authentication

### Docker Compose Production

```yaml
services:
  jetson-backend:
    # ... as in docker-compose.yml
    environment:
      API_DEBUG: "False"
      LOG_LEVEL: "INFO"
    restart: always
```

## Development Workflow

1. Make changes to backend
2. FastAPI auto-reload will refresh
3. Make changes to frontend
4. Vite HMR will update browser
5. Test functionality
6. Commit changes
7. Push to repository

## Testing Checklist

- [ ] Backend starts without errors
- [ ] Frontend loads in browser
- [ ] WebRTC video connects (or JP4.6 fallback to MJPEG is active)
- [ ] LED on/off works
- [ ] LED toggle works
- [ ] Device status updates
- [ ] API endpoints respond
- [ ] WebSocket connects
- [ ] No console errors
- [ ] GPU accelerated (CUDA enabled)

## Resources

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Docs](https://react.dev/)
- [Vite Docs](https://vitejs.dev/)
- [WebRTC Docs](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)
- [GStreamer Docs](https://gstreamer.freedesktop.org/)
- [OpenCV CUDA Docs](https://docs.opencv.org/master/d0/d1d/group__cuda.html)

---

Happy developing! 🚀

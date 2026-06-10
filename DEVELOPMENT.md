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

Notes:

- Hardware-accelerated GStreamer elements (`nvjpegdec`, `nvvidconv`) should be present.
- OpenCV CUDA device count can still be `0` if that build lacks usable CUDA runtime/device support.
- MJPEG encoding path is primarily CPU-based even when parts of the pipeline are hardware accelerated.

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

Create `.env` file in project root:

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

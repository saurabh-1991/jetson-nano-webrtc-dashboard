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
JETSON_IP=192.168.1.100
API_PORT=8000
API_DEBUG=True
LOG_LEVEL=DEBUG

# Frontend
VITE_API_URL=http://localhost:8000
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
- [ ] WebRTC video connects
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

# Jetson Nano Real-time Web Dashboard

Complete web-based application for real-time video streaming from Jetson Nano USB webcam to laptop browser with GPIO controls.

## 📋 Overview

This project creates a production-ready dashboard for:
- **Real-time video streaming** via WebRTC from Jetson Nano
- **GPIO control** for hardware components (LEDs, relays, etc.)
- **Device monitoring** with system status and health checks
- **Low-latency streaming** optimized for edge computing

## 🏗️ Architecture

```
Jetson Nano (Backend)              Laptop/Browser (Frontend)
├─ USB Webcam                     ├─ React Dashboard
├─ GStreamer Pipeline             ├─ Video Stream (WebRTC)
├─ OpenCV CUDA                    ├─ GPIO Controls
├─ FastAPI Server                 └─ Device Status
├─ GPIO Control                   
└─ WebRTC/WebSocket               
```

## ⚙️ Tech Stack

### Backend (Jetson Nano)
- **FastAPI** - REST API framework
- **Uvicorn** - ASGI server
- **GStreamer** - Hardware video decoding
- **OpenCV CUDA** - GPU image processing
- **aiortc** - WebRTC support
- **Jetson.GPIO** - GPIO control
- **Docker** - Containerization

### Frontend
- **React 18** - UI framework
- **Vite** - Build tool
- **Axios** - HTTP client
- **Tailwind CSS** - Styling (via custom CSS)
- **WebRTC** - Video streaming
- **WebSocket** - Real-time updates

## 📁 Project Structure

```
JetsonNano/POC_Project_1/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── camera.py            # GStreamer + OpenCV
│   │   ├── gpio_control.py      # GPIO management
│   │   ├── webrtc.py            # WebRTC streaming
│   │   ├── websocket.py         # WebSocket handlers
│   │   └── config.py            # Configuration
│   ├── requirements.txt          # Python dependencies
│   ├── Dockerfile               # Backend container
│   └── README.md                # Backend docs
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── VideoStream.jsx  # Video display
│   │   │   ├── GPIOControls.jsx # GPIO buttons
│   │   │   ├── DeviceStatus.jsx # Status display
│   │   │   └── *.css            # Styling
│   │   ├── services/
│   │   │   ├── api.js           # API client
│   │   │   └── webrtc.js        # WebRTC service
│   │   ├── App.jsx              # Main app
│   │   └── main.jsx             # Entry point
│   ├── package.json             # Dependencies
│   ├── vite.config.js           # Vite config
│   ├── Dockerfile               # Frontend container
│   ├── nginx.conf               # Nginx config
│   └── README.md                # Frontend docs
│
├── docker-compose.yml           # Multi-container setup
├── DEPLOYMENT.md                # Deployment instructions
└── Doc/
    └── jetson_nano_realtime_web_dashboard_architecture.md
```

## 📘 Deployment Guide

For detailed Jetson Nano deployment steps, including both Docker Compose and native installation, see `DEPLOYMENT.md`.

## 🚀 Quick Start

### Prerequisites
- Jetson Nano with JetPack installed
- CUDA and cuDNN
- GStreamer 1.0+
- Docker & Docker Compose (optional)
- USB webcam connected to Jetson Nano

### Option 1: Direct Installation

#### Backend Setup
```bash
cd backend

# JetPack 4.6 native path (recommended on Jetson)
python3 -m venv --system-site-packages .venv-jp46
source .venv-jp46/bin/activate
pip3 install -r requirements.jetpack46.txt

# (For non-JetPack/local modern Python, use requirements.txt instead)
# pip3 install -r requirements.txt

# Optional camera source switch: usb (default) | csi
export CAMERA_SOURCE=usb

python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Access dashboard at: `http://localhost:5173`

### Option 2: Docker Compose
```bash
docker-compose up -d
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:80`
- API: `http://localhost:8000/api`

## 📱 Features

### ✅ Live Video Streaming
- WebRTC for low-latency (30-120ms) streaming
- Hardware-accelerated video decoding
- MJPEG fallback option
- Automatic reconnection

### ✅ GPIO Control
- Turn LED on/off via REST API
- Toggle functionality
- Real-time status updates
- WebSocket notifications

### ✅ Device Monitoring
- Camera status and frame count
- CUDA GPU availability
- GPIO status
- WebSocket connections
- System health checks

### ✅ Performance Optimized
- GStreamer hardware decoding (nvjpegdec)
- NVIDIA CUDA processing
- GPU memory management
- Async/await architecture
- Frame dropping for latency

## 🔌 API Endpoints

### System
- `GET /` - Health check
- `GET /health` - Detailed status
- `GET /api/system/info` - System info
- `GET /api/system/status` - Full status

### Camera
- `GET /api/camera/info` - Camera details
- `GET /api/camera/frame` - Single frame
- `GET /api/camera/stream` - MJPEG stream

### GPIO
- `GET /api/gpio/status` - GPIO state
- `POST /api/gpio/on` - Turn LED on
- `POST /api/gpio/off` - Turn LED off
- `POST /api/gpio/toggle` - Toggle LED

### WebRTC
- `POST /api/webrtc/offer` - Establish connection

### WebSocket
- `WS /ws` - Real-time events

## ⚙️ Configuration

Edit `backend/app/config.py`:

```python
CAMERA_DEVICE = "/dev/video0"      # Camera device
CAMERA_WIDTH = 1280                 # Resolution
CAMERA_HEIGHT = 720
CAMERA_FPS = 30

GPIO_LED_PIN = 12                   # GPIO pin for LED
STUN_SERVERS = [...]                # WebRTC STUN servers
```

## 📊 Performance

### Expected Metrics
- Frame rate: 30 FPS
- Video latency: 30-120ms (WebRTC)
- API response: <50ms
- Memory: 200-400MB
- CPU usage: 15-25%
- GPU usage: 20-40%

### Bandwidth
- 720p @ 30fps: ~2-4 Mbps
- Optimized for home networks

## 🔧 Troubleshooting

### Camera Issues
```bash
# List cameras
ls /dev/video*

# Test GStreamer
gst-launch-1.0 v4l2src device=/dev/video0 ! xvimagesink
```

### CUDA Issues
```bash
# Check CUDA availability
python3 -c "import cv2; print(cv2.cuda.getCudaEnabledDeviceCount())"

# Monitor GPU
tegrastats
```

### GPIO Permission
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER
```

### WebRTC Connection
- Check firewall settings
- Verify STUN server connectivity
- Check browser WebRTC console logs
- Ensure backend is running

## 🔐 Security

For production:
- [ ] Enable HTTPS/SSL
- [ ] Add JWT authentication
- [ ] Implement rate limiting
- [ ] Configure CORS properly
- [ ] Use environment variables
- [ ] Enable firewall rules
- [ ] Regular security updates

## 📈 Future Enhancements

### AI Features
- YOLO object detection
- Face detection
- Motion detection
- People counting
- Gesture recognition

### Hardware
- Multi-camera support
- Additional GPIO pins
- Relay control
- Temperature sensors
- Network optimization

### Features
- Role-based access control
- Recording to disk
- Cloud streaming
- Mobile app
- Dashboard customization

## 📚 Documentation

- [Backend README](backend/README.md) - Backend details
- [Frontend README](frontend/README.md) - Frontend details
- [Architecture Doc](Doc/jetson_nano_realtime_web_dashboard_architecture.md) - Full architecture

## 🤝 Contributing

Feel free to extend and customize:
- Add more GPIO controls
- Implement additional sensors
- Add authentication
- Optimize performance
- Add new features

## 📄 License

This project is provided as-is for educational and commercial use.

## 💡 Tips

1. **Start Simple**: Begin with basic LED control before complex GPIO
2. **Monitor Performance**: Use `tegrastats` to watch GPU usage
3. **Test Locally**: Test components individually before integration
4. **Use Docker**: Docker simplifies deployment across systems
5. **Security**: Always use HTTPS in production
6. **Scale**: Start with single camera, extend to multiple

## 🎯 Next Steps

1. Deploy on Jetson Nano
2. Connect USB webcam
3. Configure GPIO pins for your hardware
4. Test video streaming
5. Test GPIO controls
6. Monitor performance
7. Deploy with Docker
8. Add HTTPS certificates
9. Implement authentication
10. Extend with AI features

---

**Version**: 1.0.0  
**Last Updated**: 2026-05-28  
**Status**: Production Ready ✅

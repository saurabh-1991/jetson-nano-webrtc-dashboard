# Deployment Guide

This document describes how to deploy the Jetson Nano WebRTC Dashboard on a Jetson Nano, including both:

- **Docker Compose deployment** (recommended)
- **Native Jetson deployment** (no Docker)

It also covers how to access and control the application from a remote PC.

---

## Prerequisites

### Hardware

- Jetson Nano board
- USB webcam or CSI camera connected and supported
- Jetson Nano power supply and network connectivity
- Remote PC on the same LAN (or VPN/port forwarding configured)

### Software

- Jetson Nano with JetPack installed
- Python 3 and `python3-pip`
- Node.js / npm (for frontend build if using native deployment)
- Docker and Docker Compose (for Docker deployment)
- `git` to clone the repo

### Jetson-specific packages

If deploying natively, install:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-opencv \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
  python3-jetson-gpio
```

If using Docker on Jetson, install the Jetson-compatible Docker runtime and Docker Compose.

---

## Option 1: Docker Compose Deployment (Recommended)

Use Docker Compose to run both backend and frontend on Jetson Nano.

### 1. Clone repository on Jetson

```bash
cd ~
git clone https://github.com/saurabh-1991/jetson-nano-webrtc-dashboard.git
cd jetson-nano-webrtc-dashboard
```

### 2. Build and run the stack

```bash
docker-compose up -d --build
```

### 3. Verify service startup

```bash
docker-compose ps
```

### 4. Open the dashboard from a remote PC

From your remote PC browser, open:

```text
http://<JETSON_IP>/
```

If the frontend is served on port 80 by Docker Compose, this is the correct URL.

### 5. Backend API health checks

From the Jetson or remote PC:

```bash
curl http://<JETSON_IP>:8000/health
curl http://<JETSON_IP>:8000/api/system/status
```

### 6. Stop or restart

```bash
docker-compose stop
docker-compose down
```

### Notes

- The Compose setup mounts `./backend` into the backend container and exposes `/dev` for camera access.
- The backend container is privileged so it can access Jetson hardware and devices.
- If your remote PC cannot access Jetson on port 80, check firewall or router settings.

---

## Option 2: Native Jetson Deployment (No Docker)

This approach runs the backend and frontend directly on the Jetson Nano.</n

### 1. Clone repository on Jetson

```bash
cd ~
git clone https://github.com/saurabh-1991/jetson-nano-webrtc-dashboard.git
cd jetson-nano-webrtc-dashboard
```

### 2. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Frontend build setup

```bash
cd ../frontend
npm install
npm run build
```

### 4. Serve frontend with Nginx or static server

The repo includes a `frontend/Dockerfile` that uses Nginx, but for native deployment you can also use a static server.

#### Option A: Use Nginx

Install Nginx on Jetson and point it to the built files.

```bash
sudo apt install -y nginx
sudo rm -f /etc/nginx/conf.d/default.conf
sudo tee /etc/nginx/conf.d/jetson-dashboard.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    root /home/<user>/jetson-nano-webrtc-dashboard/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo nginx -t
sudo systemctl restart nginx
```

Replace `/home/<user>` with your Jetson username path.

#### Option B: Use a lightweight static server

```bash
cd frontend
npx serve -s dist -l 80
```

### 5. Run backend

```bash
cd ~/jetson-nano-webrtc-dashboard/backend
source venv/bin/activate
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. Access from remote PC

- If using Nginx: `http://<JETSON_IP>/`
- If using `serve` and port 80: `http://<JETSON_IP>/`
- If using Vite dev server: `http://<JETSON_IP>:5173`

### 7. Validate API from remote PC

```bash
curl http://<JETSON_IP>:8000/health
curl http://<JETSON_IP>:8000/api/system/status
curl http://<JETSON_IP>:8000/api/gpio/status
```

### Notes

- If using Nginx, the frontend can proxy `/api` to the backend and the browser only needs `http://<JETSON_IP>/`.
- If the frontend is built statically and served from Nginx, no extra configuration is required in the app if API calls are relative.

---

## Jetson-specific camera and GPIO checks

### Camera access

Confirm the camera device is available:

```bash
ls /dev/video*
```

If using a CSI camera, you may need a Jetson-specific GStreamer pipeline instead of the default USB webcam pipeline.

### GPIO access

Confirm your user can access GPIO:

```bash
sudo usermod -a -G gpio $USER
```

Then log out and log in again.

---

## Remote PC access and control

### Find Jetson IP address

On Jetson, run:

```bash
ip addr show
```

Look for the IP on `eth0` or `wlan0`.

### Access from remote PC

Open a browser to:

```text
http://<JETSON_IP>/
```

If the frontend is served on port 80, this will load the dashboard.

### Remote command access

If the remote PC is outside the LAN, use one of these options:

- VPN into the network
- Router port forwarding for ports `80` and `8000`
- SSH tunnel:

```bash
ssh -L 8000:localhost:8000 -L 80:localhost:80 user@<JETSON_IP>
```

Then browse locally to `http://localhost/`.

---

## Troubleshooting

### If frontend cannot reach backend

- Confirm backend is running
- Confirm Jetson firewall allows `8000` and `80`
- Confirm the browser is pointing to the Jetson IP
- Confirm Nginx proxy is forwarding `/api` to `http://127.0.0.1:8000`

### If WebRTC stream fails

- Check backend logs for `/api/webrtc/offer` errors
- Confirm the camera is accessible and not held by another app
- Confirm the browser and Jetson are on the same network

### If LED stays on after shutdown

- Stop backend process completely
- Verify there are no leftover `uvicorn` or `python3` processes
- Use `ps aux | grep -E 'uvicorn|python3'`

---

## Recommended deployment summary

- Use **Docker Compose** for easiest deployment and remote access.
- Use **Native deployment** when you want minimal overhead or direct Jetson integration.
- Use **Nginx proxy** if you want the app available on port `80` and simplified API routing.

---

## References

- `docker-compose.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `backend/app/config.py`

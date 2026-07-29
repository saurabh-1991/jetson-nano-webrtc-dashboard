# Jetson Nano WebRTC Dashboard

Real-time dual-camera dashboard for Jetson Nano with low-latency browser streaming, GPIO control, and field-friendly deployment automation.

## Current branch scope

This branch is focused on:

- stable dual-camera runtime behavior (`cam1`, `cam2`)
- JetPack 4.6 deployment reliability
- documentation cleanup and operator/developer runbooks
- storage architecture planning (documented, not yet implemented)

## What you get

- **Live video pipeline** with fallback strategy:
  - H264 stream endpoint
  - WebRTC path
  - MJPEG fallback
- **GPIO control APIs** for hardware toggles
- **Runtime observability** via health/stats/camera diagnostics endpoints
- **Jetson deployment scripts** for:
  - auto-start on boot
  - LAN/static-IP setup
  - runtime `nvidia` backend launch workaround for older compose setups

## Architecture at a glance

- **Backend**: FastAPI + Uvicorn + camera/GStreamer/OpenCV integration
- **Frontend**: React + Vite + Nginx container
- **Runtime**: Docker Compose (default) with optional backend replacement script for `--runtime nvidia`

Main services in `docker-compose.yml`:

- `jetson-backend` → container `jetson-nano-backend` (port `8000`)
- `jetson-frontend` → container `jetson-nano-frontend` (port `80`)
- `docker-prune` (optional automatic cleanup)

## Quick start

### Option A — Docker Compose (recommended)

1. Copy and adjust env values from `.env.example`.
2. Start stack:

   - `docker-compose up -d --build` (first run or after Dockerfile/dependency changes)
   - `docker-compose up -d` (normal daily start)

3. Open:

   - Dashboard: `http://<jetson-ip>/`
   - API health: `http://<jetson-ip>:8000/health`

### Option B — Compose + explicit NVIDIA runtime backend

On older Jetson compose versions where YAML runtime support is limited:

- run `scripts/run_backend_with_nvidia_runtime.sh`

This keeps compose-managed networking and replaces only backend with `--runtime nvidia`.

### Option C — Native backend (JP4.6 validation/debug)

From `backend/`:

- `scripts/setup_jetpack46_native.sh`
- `scripts/run_jetpack46_native.sh`

Frontend can still run from `frontend/` with `npm run dev` for development.

## Key endpoints

- `GET /health`
- `GET /api/system/status`
- `GET /api/stats`
- `GET /api/camera/info`
- `GET /api/camera/stream` (MJPEG)
- `GET /api/camera/stream_h264`
- `POST /api/camera/recover`

## Project layout

- `backend/` — API, camera runtime, GPIO, config
- `frontend/` — dashboard UI
- `scripts/` — deployment/operations automation
- `Doc/` — architecture, operator cards, UAT, storage blueprint

## Documentation index

- `DEVELOPMENT.md` — contributor workflow and local testing
- `DEPLOYMENT.md` — Jetson field deployment runbook
- `Doc/jetson_nano_realtime_web_dashboard_architecture.md` — architecture reference
- `Doc/software-architecture-and-application-flow-v1.0.0.md` — Mermaid diagrams: deployment architecture, software architecture, and runtime flow
- `Doc/scalable-experiment-recording-architecture-v1.4.0.md` — recording architecture plan
- `Doc/production-video-storage-blueprint-v1.0.0.md` — production storage blueprint (new)
- `Doc/new-local-network-deployment.md` — first-time LAN setup guide
- `Doc/operator-quick-card-v1.2.0.md` — operator quick commands

## Notes

- Keep `.env.example` as the source template for branch configuration.
- WebRTC availability can vary by JP4.6 dependency profile; fallback flow is expected behavior.
- Video storage implementation is intentionally deferred; design is documented and ready for phase-1 coding.

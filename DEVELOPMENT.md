# Development Guide

This guide is for contributors working on this branch.

## 1) Development modes

Choose one workflow depending on your setup.

### Mode A (most common): frontend on laptop, backend on Jetson

Use this when camera/GPU/GPIO are physically on Jetson.

1. Start backend on Jetson (native or docker).
2. On laptop, set frontend API target:
   - `VITE_API_BASE_URL=http://<jetson-ip>:8000`
3. Run frontend locally with Vite.

### Mode B: native backend on Jetson (debug-friendly)

From `backend/` on Jetson:

- `./scripts/setup_jetpack46_native.sh`
- `./scripts/run_jetpack46_native.sh`

Use this mode for camera pipeline diagnostics and quick backend iteration.

### Mode C: full docker compose stack

From repo root:

- `docker-compose up -d --build` (first run or when image inputs changed)
- `docker-compose up -d` (normal restart)

For older compose/NVIDIA runtime constraints, run:

- `./scripts/run_backend_with_nvidia_runtime.sh`

## 2) Environment setup

1. Copy `.env.example` to `.env`.
2. Review camera/runtime values before testing.

Important branch defaults already documented in `.env.example` include:

- dual-camera profile controls
- H264 fallback/cooldown tuning
- media gateway toggles (optional)
- video storage blueprint placeholders (documented only for now)

## 3) Frontend development

From `frontend/`:

- install dependencies (`npm install`)
- run dev server (`npm run dev`)

Quick asset-only deployment to Jetson frontend container:

- `scripts/deploy_frontend_assets_quick.ps1`

## 4) Backend development focus areas

Key files:

- `backend/app/main.py` — API routes and health/stats
- `backend/app/camera.py` — capture pipeline and stream logic
- `backend/app/config.py` — env-driven tuning
- `backend/app/webrtc.py` — WebRTC negotiation path

When changing runtime behavior, validate both cameras (`cam1`, `cam2`) explicitly.

## 5) Validation checklist (minimum)

After changes, verify:

1. `GET /health` is healthy.
2. `GET /api/system/status` returns expected runtime flags.
3. `GET /api/camera/info?camera_id=cam1&create_if_missing=true` is sane.
4. `GET /api/camera/info?camera_id=cam2&create_if_missing=true` is sane.
5. Frontend live view recovers correctly across fallback paths.

Useful extra checks:

- `GET /api/stats`
- `POST /api/camera/recover`

## 6) Jetson-specific notes

- JetPack 4.6 can have partial WebRTC/CUDA variance by environment.
- MJPEG fallback is a valid operational path, not a failure by itself.
- Prefer script-driven runtime startup for repeatability.

## 7) Development hygiene for this branch

- Keep docs aligned with actual scripts and compose behavior.
- Avoid introducing parallel “alternative” startup scripts unless required.
- Validate on real Jetson before marking camera/perf changes as stable.

## 8) Next-phase scope (documented only)

Production video storage architecture is prepared in:

- `Doc/production-video-storage-blueprint-v1.0.0.md`

Implementation is intentionally deferred until phase-1 coding is approved.

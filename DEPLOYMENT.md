# Deployment Guide (Jetson Nano / JetPack 4.6)

This is the branch deployment runbook for field and lab setups.

## 1) Recommended deployment model

Use a hybrid model:

- **Offline-safe runtime on boot** for reliability after power/network changes
- **Manual online update** when internet is available

Primary scripts:

- `scripts/powerrun_apply_all.sh`
- `scripts/run_backend_with_nvidia_runtime.sh`
- `scripts/deploy_online_update.sh`

For first-time LAN setup walkthrough, see:

- `Doc/new-local-network-deployment.md`

## 2) Prerequisites

- Jetson Nano with JetPack 4.6
- Docker + docker-compose
- Camera(s) visible under `/dev/video*`
- Project checked out on Jetson

## 3) First deployment on Jetson

From project root on Jetson:

1. Configure boot/network/autologin values in `scripts/powerrun.config`.
2. Apply one-command setup:
   - `sudo ./scripts/powerrun_apply_all.sh`
3. Start stack:
   - `docker-compose up -d --build` (first run)
4. If needed for older compose runtime limitations:
   - `./scripts/run_backend_with_nvidia_runtime.sh`

## 4) Day-to-day startup

Normal start/stop without rebuild:

- start: `docker-compose up -d`
- stop: `docker-compose down --remove-orphans`

If backend runtime behavior regresses or GPU path is required, re-run:

- `./scripts/run_backend_with_nvidia_runtime.sh`

## 5) Online update flow

When internet is available and you want a controlled refresh:

- `./scripts/deploy_online_update.sh`

Optional git-sync mode:

- `./scripts/deploy_online_update.sh --sync-git --branch <branch-name>`

## 6) Verification checklist after deploy/reboot

On Jetson:

1. `docker-compose ps`
2. `curl http://127.0.0.1:8000/health`
3. `curl http://127.0.0.1/api/system/status`
4. `curl "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true"`
5. `curl "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true"`

From laptop on same LAN:

- `http://<jetson-ip>/`
- `http://<hostname>.local/` (if mDNS enabled)

## 7) Power/network resilience checks

After power cycle or LAN change:

- verify service auto-start is active
- verify dashboard resolves via static IP or `.local`
- verify stream fallback path still recovers (H264/WebRTC/MJPEG)

Useful helper:

- `scripts/check_lan_access.sh`

## 8) Troubleshooting quick actions

### A) Camera appears stuck

1. Use UI **Reset Camera** (calls `POST /api/camera/recover`).
2. If needed, restart backend container:
   - `docker restart jetson-nano-backend`

### B) Frontend reachable but API unstable

1. confirm backend health endpoint
2. inspect backend logs:
   - `docker-compose logs --tail=200 jetson-backend`

### C) Runtime/GPU mismatch on older compose

Re-run:

- `./scripts/run_backend_with_nvidia_runtime.sh`

It recreates backend with `--runtime nvidia` while keeping compose network compatibility.

## 9) Safe shutdown / rollback

Stop stack:

- `docker-compose down --remove-orphans`

Stop native mode if used:

- `./scripts/stop_native_dashboard.sh`

Rollback network setup (if static IP config causes access problems):

- revert via NetworkManager (`nmcli`) to DHCP
- re-apply with corrected `scripts/powerrun.config`

## 10) Related branch docs

- `README.md` — overview and quick start
- `DEVELOPMENT.md` — contributor workflow
- `Doc/operator-quick-card-v1.2.0.md` — operator cheat sheet
- `Doc/UAT-checklist-v1.1.0.md` — acceptance validation
- `Doc/production-video-storage-blueprint-v1.0.0.md` — upcoming storage architecture (design-only)

# Deployment Guide (Jetson Nano / JetPack 4.6)

This runbook is for field and lab deployment. It includes:

- exact deployment commands,
- where to change Modbus/Waveshare/VFD/flow settings,
- restart choices (compose vs NVIDIA runtime),
- troubleshooting with logs and diagnostics.

## 1) Recommended model

Use this model in production:

- Boot reliability with powerrun scripts
- Manual controlled updates when internet is available
- Backend launched through NVIDIA runtime script when required by camera/OpenCV CUDA path

Main scripts:

- `scripts/powerrun_apply_all.sh`
- `scripts/run_backend_with_nvidia_runtime.sh`
- `scripts/deploy_online_update.sh`

## 2) Prerequisites

- Jetson Nano with JetPack 4.6
- Docker and docker-compose installed
- Project checked out on Jetson
- Camera devices present under `/dev/video*`
- Waveshare/data logger reachable on LAN when using Modbus TCP

## 3) File locations for field configuration

Primary configuration file:

- `docker-compose.yml`

Sensor register mapping guide:

- `Doc/sensor-config.md`

NVIDIA backend runtime launcher:

- `scripts/run_backend_with_nvidia_runtime.sh`

## 4) First deployment on Jetson

From project root on Jetson:

1. Edit boot/network/autologin values in `scripts/powerrun.config`.
2. Run one-time base setup:
   - `sudo ./scripts/powerrun_apply_all.sh`
3. Build and start base stack:
   - `docker-compose up -d --build`
4. If backend needs NVIDIA runtime path:
   - `./scripts/run_backend_with_nvidia_runtime.sh`

## 5) Field update when you receive real gateway IP/registers

Edit `docker-compose.yml` backend environment values.

Minimum values for datalogger via Waveshare (no USB Modbus converter required):

- `MODBUS_TRANSPORT=tcp`
- `MODBUS_HOST=<WAVESHARE_OR_DATALOGGER_GATEWAY_IP>`
- `MODBUS_TCP_PORT=502`
- `MODBUS_SLAVE_ID=<LOGGER_SLAVE_ID>`

Flow meter (enabled by default):

- `FLOW_METER_ENABLED=true`
- `FLOW_METER_TRANSPORT=tcp`
- `FLOW_METER_HOST=<FLOW_GATEWAY_IP_OR_SAME_WAVESHARE_IP>`
- `FLOW_METER_TCP_PORT=502`
- `FLOW_METER_SLAVE_ID=<FLOW_SLAVE_ID>`
- `FLOW_METER_VALUE_ADDRESS=<REGISTER>`
- Optional: `FLOW_METER_DECIMAL_ADDRESS`, `FLOW_METER_STATUS_ADDRESS`

Temperature channels (if field map differs):

- `MODBUS_ADDR_HOT_ZONE_VALUE`, `MODBUS_ADDR_HOT_ZONE_DECIMAL`, `MODBUS_ADDR_HOT_ZONE_STATUS`
- `MODBUS_ADDR_COLD_ZONE_VALUE`, `MODBUS_ADDR_COLD_ZONE_DECIMAL`, `MODBUS_ADDR_COLD_ZONE_STATUS`
- `MODBUS_ADDR_EXHAUST_VALUE`, `MODBUS_ADDR_EXHAUST_DECIMAL`, `MODBUS_ADDR_EXHAUST_STATUS`

If manual uses 30001/40001 style logical addresses:

- set `MODBUS_ADDRESS_BASE`
- keep address values as in manual

## 6) Which restart command to run after config changes

### A) Compose-only backend restart

Use when you are not relying on NVIDIA runtime replacement:

- `docker-compose up -d --build jetson-backend`

### B) NVIDIA runtime backend restart (recommended on this branch)

Use when backend is expected to run with runtime nvidia:

- `./scripts/run_backend_with_nvidia_runtime.sh`

Notes:

- Full frontend rebuild is not required for sensor IP/register changes.
- If frontend did not change, restart only backend.

## 7) Day-to-day operation

Start/stop stack:

- start: `docker-compose up -d`
- stop: `docker-compose down --remove-orphans`

Controlled online refresh:

- `./scripts/deploy_online_update.sh`
- optional git sync: `./scripts/deploy_online_update.sh --sync-git --branch <branch>`

## 7.1) Docker engine stop/start/restart (host-level)

Use these only when container-level restart is not enough.

1. Stop Docker engine (stops all running containers):
   - `sudo systemctl stop docker`
2. Start Docker engine:
   - `sudo systemctl start docker`
3. Restart Docker engine:
   - `sudo systemctl restart docker`
4. Check Docker engine status:
   - `sudo systemctl status docker --no-pager`
5. Confirm engine + containers visible again:
   - `docker ps`

If `systemctl` is unavailable in your target image, use:

- `sudo service docker restart`

## 8) Post-deploy verification checklist

Run on Jetson:

1. Containers and status:
   - `docker-compose ps`
2. Backend health:
   - `curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs`
3. Frontend health:
   - `curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/`
4. Sensor payload:
   - `curl -s http://127.0.0.1:8000/api/sensors/latest`
5. Camera state:
   - `curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true"`
   - `curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true"`

Interpret sensor source quickly:

- `modbus`: logger and flow both read OK
- `modbus_partial`: one path OK, one path unavailable
- `modbus_unavailable`: no Modbus data currently available

## 8.1) How datalogger temperature/flow reaches Jetson UI

Field path:

1. Sensors and flow meter are wired to the datalogger (Modbus RTU map).
2. Datalogger RS485 lines are connected to Waveshare RS485-to-Ethernet gateway.
3. Jetson backend polls gateway by TCP (`MODBUS_HOST`, `MODBUS_TCP_PORT`, `FLOW_METER_HOST`, `FLOW_METER_TCP_PORT`).
4. Backend decodes registers in `app/sensor_data.py` using map/settings from `app/modbus_sensor_config.py` and env vars.
5. Backend serves values at `/api/sensors/latest`.
6. Frontend reads backend API and renders temperatures/flow in UI widgets.

Field verification sequence:

1. Gateway reachable from Jetson:
   - `ping -c 3 <WAVESHARE_IP>`
   - `nc -vz <WAVESHARE_IP> 502`
2. Backend has correct env loaded:
   - `docker exec -it jetson-nano-backend sh -lc "env | grep -E 'MODBUS_|FLOW_METER_' | sort"`
3. Backend API has decoded payload:
   - `curl -s http://127.0.0.1:8000/api/sensors/latest`
4. UI/backend connectivity:
   - `curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/`
   - `curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs`

If step 3 shows `modbus_unavailable`, issue is before UI (gateway/IP/slave/register/runtime config).

## 9) Troubleshooting and analysis commands

### A) Backend does not start or keeps restarting

1. Check restart state:
   - `docker-compose ps`
2. Inspect backend logs:
   - `docker logs --tail 200 jetson-nano-backend`
   - `docker-compose logs --tail 200 jetson-backend`
3. If import/runtime mismatch is seen (for example CUDA/OpenCV shared library errors), re-run:
   - `./scripts/run_backend_with_nvidia_runtime.sh`

### B) Frontend is up but API fails

1. Compare status codes:
   - `curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs`
   - `curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/`
2. Backend logs:
   - `docker logs --tail 300 jetson-nano-backend`
3. Network reachability from backend container:
   - `docker exec -it jetson-nano-backend sh -lc "ip route; cat /etc/resolv.conf"`

### C) Modbus values unavailable

1. Confirm effective env inside backend container:
   - `docker exec -it jetson-nano-backend sh -lc "env | grep -E 'MODBUS_|FLOW_METER_' | sort"`
2. Verify API output:
   - `curl -s http://127.0.0.1:8000/api/sensors/latest`
3. Look for connection warnings in logs:
   - `docker logs --tail 300 jetson-nano-backend | grep -Ei 'modbus|flow|connect|timeout|unavailable|exception'`
4. Validate IP/port reachability from Jetson:
   - `ping -c 3 <WAVESHARE_IP>`
   - `nc -vz <WAVESHARE_IP> 502`
5. If register map is uncertain, re-check values in `Doc/sensor-config.md` and data logger manual.

### D) Container name conflict errors (common during recreate)

Symptom example: container name already in use.

Fix:

1. Remove stale container:
   - `docker rm -f jetson-nano-backend`
2. Start again:
   - `docker-compose up -d --no-deps jetson-backend`

### E) Camera stuck or no live frames

1. Trigger recover endpoint:
   - `curl -X POST http://127.0.0.1:8000/api/camera/recover`
2. Check camera diagnostics:
   - `curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true"`
3. Backend logs:
   - `docker logs --tail 300 jetson-nano-backend | grep -Ei 'camera|v4l|gstreamer|recover|error'`

### F) Quick container and image audit

- running containers: `docker ps`
- compose status: `docker-compose ps`
- recent exits: `docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'`
- backend image id: `docker image inspect jetsonnanowebrtcdashboard_jetson-backend:latest --format '{{.Id}}'`

## 10) Safe shutdown and rollback

Stop stack:

- `docker-compose down --remove-orphans`

Stop native mode if used:

- `./scripts/stop_native_dashboard.sh`

If static IP setup causes access issues:

- revert interface to DHCP with NetworkManager
- fix `scripts/powerrun.config`
- reapply `sudo ./scripts/powerrun_apply_all.sh`

## 11) Related docs

- `README.md` for overview
- `DEVELOPMENT.md` for contributor workflow
- `Doc/sensor-config.md` for register/IP mapping details
- `Doc/operator-quick-card-v1.2.0.md` for operator quick use
- `Doc/UAT-checklist-v1.1.0.md` for validation checklist

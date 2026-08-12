# Deployment Guide (Jetson Nano / JetPack 4.6)

This document is a field-first, offline runbook intended for engineers who may have no internet at site.

It includes:

- exact command-by-command procedures,
- expected results after each step,
- dual-VFD + sensor + camera verification,
- failure recovery flows that do not depend on online resources.

## 1) Scope and operating model

Use this model in production:

- device boot/network behavior managed by powerrun scripts,
- routine service restart through docker-compose,
- backend recovery through NVIDIA runtime launcher when CUDA/OpenCV path is required.

Primary scripts:

- `scripts/powerrun_apply_all.sh`
- `scripts/deploy_frontend_backend.sh`
- `scripts/run_backend_with_nvidia_runtime.sh`
- `scripts/deploy_online_update.sh`
- `scripts/run_native_dashboard.sh`
- `scripts/stop_native_dashboard.sh`

## 2) Prerequisites checklist (offline friendly)

Required:

- Jetson Nano on JetPack 4.6
- Docker engine and docker-compose command available
- project folder present on Jetson disk
- camera devices present in `/dev/video*`
- Waveshare/DataLogger network reachable over LAN for Modbus TCP

Run and confirm before any deployment:

```bash
cd /path/to/POC_Project_1
pwd
ls
docker --version
docker-compose --version
ls /dev/video*
```

Expected results:

- `pwd` shows the project root.
- `docker --version` and `docker-compose --version` both print versions.
- `ls /dev/video*` returns one or more camera nodes (example: `/dev/video0`).

If `docker-compose` is not found, do not continue deployment. Resolve local environment first.

## 3) Important files for field edits

- Main runtime settings: `docker-compose.yml`
- Sensor/register map reference: `Doc/sensor-config.md`
- NVIDIA backend launcher: `scripts/run_backend_with_nvidia_runtime.sh`
- Boot/network setup values: `scripts/powerrun.config`

## 4) First-time bring-up on a Jetson device

### Step 1: configure boot/network values

Edit `scripts/powerrun.config` with site-specific values.

### Step 2: apply one-time host setup

```bash
sudo ./scripts/powerrun_apply_all.sh
```

Expected result:

- script exits without error,
- service/boot configuration is applied.

### Step 3: build and start stack

```bash
docker-compose up -d --build
docker-compose ps
```

Expected result:

- services appear as `Up` in `docker-compose ps`.

### Step 4: switch backend to NVIDIA runtime path (recommended)

```bash
./scripts/run_backend_with_nvidia_runtime.sh
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Expected result:

- backend container starts successfully,
- backend status remains `Up` (not restarting).

## 5) Field configuration (Modbus, flow, dual VFD)

Edit backend environment values in `docker-compose.yml`.

### 5.1 Datalogger via Waveshare (no USB-TTL converter)

Current field mapping for Waveshare 4CH endpoints:

- `192.168.0.201` -> VFD #1
- `192.168.0.202` -> VFD #2
- `192.168.0.203` -> Flow meter
- `192.168.0.204` -> Datalogger

Before backend restart, verify datalogger converter web page at `http://192.168.0.204/ip_en.html`:

- Work Mode: `TCP Server`
- Protocol: `Modbus TCP to RTU`
- Device Port: `502` (auto-adjusts when protocol conversion is enabled)
- Serial must match your logger RS485 settings (baud/databits/parity/stopbits)

If Protocol is `None` and Device Port is `4196`, backend Modbus TCP polling may return unavailable data.

Required baseline:

- `MODBUS_TRANSPORT=tcp`
- `MODBUS_HOST=192.168.0.204` (datalogger endpoint)
- `MODBUS_TCP_PORT=502`
- `MODBUS_SLAVE_ID=<LOGGER_SLAVE_ID>`

### 5.2 Flow meter configuration

- `FLOW_METER_ENABLED=true`
- `FLOW_METER_TRANSPORT=tcp`
- `FLOW_METER_HOST=192.168.0.203` (flow meter endpoint)
- `FLOW_METER_TCP_PORT=502`
- `FLOW_METER_SLAVE_ID=<FLOW_SLAVE_ID>`
- `FLOW_METER_VALUE_ADDRESS=<REGISTER>`
- optional: `FLOW_METER_DECIMAL_ADDRESS`, `FLOW_METER_STATUS_ADDRESS`

### 5.3 Dual VFD configuration (VFD #1 and VFD #2)

VFD #1:

- `VFD_ENABLED=true`
- `VFD_HOST=192.168.0.201`
- `VFD_PORT=502`
- `VFD_SLAVE_ID=<VFD1_SLAVE_ID>`

VFD #2:

- `VFD2_ENABLED=true`
- `VFD2_HOST=192.168.0.202`
- `VFD2_PORT=502`
- `VFD2_SLAVE_ID=<VFD2_SLAVE_ID>`

Optional per-drive tuning:

- speed bounds and scaling: `VFD_MIN_SPEED_HZ`, `VFD_MAX_SPEED_HZ`, `VFD_SPEED_SCALE`
- command registers: `VFD_RUN_COMMAND_REGISTER`, `VFD_SPEED_COMMAND_REGISTER` (MS300 default `0x2000` / `0x2001`)
- command words: `VFD_RUN_FORWARD_WORD=18` (`0x0012`), `VFD_STOP_WORD=1` (`0x0001`)
- optional logical-address conversion: `VFD_ADDRESS_BASE`, `VFD_ADDRESS_OFFSET`
- mirror values for VFD2 with `VFD2_*`

### 5.4 Temperature register mapping

Set if field map differs:

- `MODBUS_ADDR_HOT_ZONE_VALUE`, `MODBUS_ADDR_HOT_ZONE_DECIMAL`, `MODBUS_ADDR_HOT_ZONE_STATUS`
- `MODBUS_ADDR_COLD_ZONE_VALUE`, `MODBUS_ADDR_COLD_ZONE_DECIMAL`, `MODBUS_ADDR_COLD_ZONE_STATUS`
- `MODBUS_ADDR_EXHAUST_VALUE`, `MODBUS_ADDR_EXHAUST_DECIMAL`, `MODBUS_ADDR_EXHAUST_STATUS`

If manual uses logical addresses (30001/40001 style):

- set `MODBUS_ADDRESS_BASE`,
- keep register numbers consistent with the manual convention.

## 6) Restart decision table after config changes

Preferred single-command deploy (frontend + backend together):

```bash
./scripts/deploy_frontend_backend.sh
```

Rebuild images then deploy frontend + backend together:

```bash
./scripts/deploy_frontend_backend.sh --rebuild
```

Compose-only mode (skip runtime=nvidia backend replacement):

```bash
./scripts/deploy_frontend_backend.sh --rebuild --no-nvidia-backend
```

Expected result:

- script prints backend and frontend HTTP checks,
- both endpoints should return `200`:
  - backend: `http://127.0.0.1:8000/docs`
  - frontend: `http://127.0.0.1:80/`

Use compose-only backend restart when backend runtime is standard:

```bash
docker-compose up -d --build jetson-backend
```

Use NVIDIA runtime launcher when this branch/site depends on CUDA/OpenCV runtime libraries:

```bash
./scripts/run_backend_with_nvidia_runtime.sh
```

Expected result for either path:

- backend becomes healthy and responds with HTTP 200 on `/docs`.

Note: sensor IP/register changes do not require frontend rebuild.

## 7) Standard daily operations

Start all services:

```bash
docker-compose up -d
```

Stop all services:

```bash
docker-compose down --remove-orphans
```

Controlled update flow (internet available only):

```bash
./scripts/deploy_online_update.sh
./scripts/deploy_online_update.sh --sync-git --branch <branch>
```

## 8) Host-level Docker control (only if container restart is insufficient)

Stop Docker engine:

```bash
sudo systemctl stop docker
```

Start Docker engine:

```bash
sudo systemctl start docker
```

Restart Docker engine:

```bash
sudo systemctl restart docker
```

Check engine status:

```bash
sudo systemctl status docker --no-pager
docker ps
```

Fallback when systemd service layout differs:

```bash
sudo service docker restart
```

Expected result:

- `docker ps` prints container table, not daemon connection errors.

## 9) Mandatory post-deploy validation with expected results

Run in this order.

### 9.1 Container state

```bash
docker-compose ps
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Expected result:

- frontend and backend are present,
- status is `Up`.

### 9.2 Backend HTTP health

```bash
curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs
```

Expected result:

- prints `backend:200`.

### 9.3 Frontend HTTP health

```bash
curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/
```

Expected result:

- prints `frontend:200`.

### 9.4 Sensor payload validity

```bash
curl -s http://127.0.0.1:8000/api/sensors/latest
```

Expected result:

- valid JSON,
- `source` should be one of:
  - `modbus` (best: logger and flow are both available),
  - `modbus_partial` (one available, one unavailable),
  - `modbus_unavailable` (no valid Modbus reads).

### 9.5 Camera diagnostics

```bash
curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true"
curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true"
```

Expected result:

- both return JSON without server error.

### 9.6 Dual VFD endpoint validation

VFD #1 status:

```bash
curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd1"
```

VFD #2 status:

```bash
curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd2"
```

Expected result:

- JSON with `success: true`,
- each call includes selected `vfd` and aggregated `vfds` map.

Optional command test:

```bash
curl -s -X POST http://127.0.0.1:8000/api/vfd/run -H "Content-Type: application/json" -d '{"vfd_id":"vfd1","run":false}'
curl -s -X POST http://127.0.0.1:8000/api/vfd/run -H "Content-Type: application/json" -d '{"vfd_id":"vfd2","run":false}'
```

Expected result:

- both return success JSON,
- `vfd_id` in response matches request.

### 9.7 GPIO runtime validation

```bash
curl -s http://127.0.0.1:8000/api/gpio/status
docker logs --tail 200 jetson-nano-backend | grep -Ei 'jetson\\.gpio|gpio initialized|gpio runtime unavailable|gpio not available'
```

Expected result:

- response JSON includes `gpio.gpio_available: true`,
- logs do not contain `Jetson.GPIO not available`.

## 10) Data-path verification (sensor to UI)

Signal chain:

1. Field temperature channels feed datalogger registers.
2. Flow meter is wired on its own Waveshare endpoint.
3. Backend polls datalogger (`192.168.0.204`) and flow endpoint (`192.168.0.203`) via Modbus TCP.
4. VFD control uses dedicated endpoints `192.168.0.201` and `192.168.0.202`.
5. Backend decodes register map and publishes `/api/sensors/latest`.
6. Frontend reads backend API and renders values.

Offline diagnostic commands:

```bash
ping -c 3 192.168.0.204
nc -vz 192.168.0.204 502
ping -c 3 192.168.0.203
nc -vz 192.168.0.203 502
ping -c 3 192.168.0.201
nc -vz 192.168.0.201 502
ping -c 3 192.168.0.202
nc -vz 192.168.0.202 502
docker exec -it jetson-nano-backend sh -lc "env | grep -E 'MODBUS_|FLOW_METER_|VFD|VFD2_' | sort"
curl -s http://127.0.0.1:8000/api/sensors/latest
```

Expected result:

- ping succeeds,
- TCP 502 is reachable,
- env output matches site sheet,
- sensor API returns JSON.

## 11) Troubleshooting playbooks (symptom -> command -> expected)

### 11.1 Backend keeps restarting or exits

Commands:

```bash
docker-compose ps
docker logs --tail 300 jetson-nano-backend
docker-compose logs --tail 300 jetson-backend
```

Expected clues:

- import/shared-library failures,
- Modbus/connectivity warnings,
- camera initialization failures.

If CUDA/OpenCV library issue appears (example: libcublas missing), run:

```bash
./scripts/run_backend_with_nvidia_runtime.sh
```

### 11.2 Frontend opens but data/actions fail

Commands:

```bash
curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs
curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/
docker logs --tail 300 jetson-nano-backend
```

Expected interpretation:

- `frontend:200` + `backend!=200` means backend issue,
- both 200 but UI stale usually indicates browser/session/cache or API payload issue.

### 11.3 Sensors show modbus_unavailable

Commands:

```bash
docker exec -it jetson-nano-backend sh -lc "env | grep -E 'MODBUS_|FLOW_METER_' | sort"
curl -s http://127.0.0.1:8000/api/sensors/latest
docker logs --tail 300 jetson-nano-backend | grep -Ei 'modbus|flow|connect|timeout|unavailable|exception'
ping -c 3 192.168.0.204
nc -vz 192.168.0.204 502
ping -c 3 192.168.0.203
nc -vz 192.168.0.203 502
```

Expected interpretation:

- wrong env -> fix compose and restart backend,
- unreachable gateway -> fix cable/switch/IP,
- reachable gateway + still unavailable -> verify slave ID/register map.

### 11.4 VFD control unavailable or no effect

Commands:

```bash
curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd1"
curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd2"
docker exec -it jetson-nano-backend sh -lc "env | grep -E '^VFD|^VFD2_' | sort"
docker logs --tail 300 jetson-nano-backend | grep -Ei 'vfd|modbus|connect|write|exception'
```

Expected interpretation:

- `enabled=false` or `host_configured=false` means incomplete env,
- `last_error=modbus_connect_failed` suggests network/slave/IP issue,
- write errors suggest register/slave mismatch.

### 11.5 Container name conflict during recreate

Symptoms:

- message similar to container name already in use.

Commands:

```bash
docker rm -f jetson-nano-backend
docker-compose up -d --no-deps jetson-backend
```

Expected result:

- backend recreated and listed as Up.

### 11.6 Camera stuck or blank stream

Commands:

```bash
curl -X POST http://127.0.0.1:8000/api/camera/recover
curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam1&create_if_missing=true"
curl -s "http://127.0.0.1:8000/api/camera/info?camera_id=cam2&create_if_missing=true"
docker logs --tail 300 jetson-nano-backend | grep -Ei 'camera|v4l|gstreamer|recover|error'
```

Expected result:

- camera info shows valid state and stream can restart.

### 11.7 Quick audit commands for field reports

```bash
date
hostname
ip -brief a
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}'
docker image inspect jetsonnanowebrtcdashboard_jetson-backend:latest --format '{{.Id}}'
```

Expected use:

- capture output in report for remote support analysis.

## 12) Safe cleanup, prune, and rollback guidance

Stop stack safely:

```bash
docker-compose down --remove-orphans
```

Stop native runtime mode if used:

```bash
./scripts/stop_native_dashboard.sh
```

Conservative cleanup (safe first):

```bash
docker container prune -f
docker image prune -f
```

Aggressive cleanup (only if you can rebuild locally and have enough time):

```bash
docker system prune -a -f --volumes
```

Expected caution:

- aggressive prune removes stopped containers, dangling and unused images, and unused volumes/network artifacts.

Rollback strategy:

1. Restore last known-good `docker-compose.yml` and config files.
2. Recreate stack:

```bash
docker-compose up -d --build
./scripts/run_backend_with_nvidia_runtime.sh
```

3. Re-run section 9 validation.

## 13) Offline operation guidance

When no internet is available:

- do not depend on apt/pip/npm installs on site,
- avoid destructive cleanups unless required,
- preserve logs before restart loops,
- keep a local copy of this repository and configuration snapshots.

Recommended field backup commands before major change:

```bash
mkdir -p /tmp/jetson-field-backup
cp docker-compose.yml /tmp/jetson-field-backup/docker-compose.yml.$(date +%Y%m%d_%H%M%S)
docker-compose ps > /tmp/jetson-field-backup/compose_ps.$(date +%Y%m%d_%H%M%S).txt
docker ps -a > /tmp/jetson-field-backup/docker_ps_a.$(date +%Y%m%d_%H%M%S).txt
```

### 13.1 Frozen base image for offline backend rebuilds

The backend Docker build is split into two layers so app code changes never
require recompiling OpenCV/CUDA in the field:

- `backend/Dockerfile.jetpack46.base` - system deps + OpenCV/CUDA built from
  source. Expensive (45-90+ min on Jetson Nano). Only rebuild this when
  JetPack/OpenCV/system deps actually change.
- `backend/Dockerfile.jetpack46` - thin layer that just `FROM`s the frozen
  base image tag and copies `app/`. Rebuilds in seconds.

One-time (where internet is available), build and freeze the base image:

```bash
./scripts/build_base_image.sh jetson-backend-base:jp46-opencv455-v1
```

This produces `dist/jetson-backend-base_jp46-opencv455-v1.tar.gz` plus a
`.sha256` checksum file. Copy both to the field device (USB drive or `scp`;
no internet/registry required), then load it once per device:

```bash
./scripts/load_base_image.sh /path/to/jetson-backend-base_jp46-opencv455-v1.tar.gz
```

After that, normal app deployments only rebuild the thin layer:

```bash
docker-compose build jetson-backend   # seconds, not hours
./scripts/run_backend_with_nvidia_runtime.sh
```

Important: `docker image prune -f` (used in section 12 and by the
`docker-prune` sidecar) never removes tagged images, only dangling/untagged
ones - so the frozen base image tag is safe from routine pruning. Bump the
tag (e.g. `...-v2`) and rebuild the base only when JetPack/OpenCV/system
deps change; keep the tarball backed up outside git (it is too large for
version control).

## 14) One-command health snapshot for support handoff

Run this block and share the saved file:

```bash
OUT="/tmp/jetson_health_$(date +%Y%m%d_%H%M%S).log"
{
  echo "=== TIME ==="
  date
  echo "=== HOST ==="
  hostname
  echo "=== IP ==="
  ip -brief a
  echo "=== DOCKER PS ==="
  docker ps -a
  echo "=== COMPOSE PS ==="
  docker-compose ps
  echo "=== BACKEND 200 CHECK ==="
  curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs
  echo "=== FRONTEND 200 CHECK ==="
  curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/
  echo "=== SENSOR PAYLOAD ==="
  curl -s http://127.0.0.1:8000/api/sensors/latest
  echo
  echo "=== VFD1 STATUS ==="
  curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd1"
  echo
  echo "=== VFD2 STATUS ==="
  curl -s "http://127.0.0.1:8000/api/vfd/status?vfd_id=vfd2"
  echo
  echo "=== BACKEND LOG TAIL ==="
  docker logs --tail 200 jetson-nano-backend
} > "$OUT" 2>&1
echo "Saved: $OUT"
```

Expected result:

- a single log file is created under `/tmp` containing key diagnostics.

## 15) Related references

- `README.md` for overall architecture
- `DEVELOPMENT.md` for development workflow
- `Doc/sensor-config.md` for sensor and Modbus mapping details
- `Doc/operator-quick-card-v1.2.0.md` for operator shortcuts
- `Doc/UAT-checklist-v1.1.0.md` for acceptance checks

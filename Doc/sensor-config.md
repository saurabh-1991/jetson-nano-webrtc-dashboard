# Sensor Configuration Guide (Waveshare RS485 to Ethernet)

This guide explains how to configure the current backend for your field topology:

- Temperature Sensor 1, 2, 3 -> Data Logger (Modbus RTU)
- Flow Meter -> Data Logger (or separate Modbus endpoint)
- Data Logger RS485 -> Waveshare 4-CH RS485 to Ethernet
- Jetson Nano -> Waveshare over Ethernet (Modbus TCP from Python)

Goal: configure registers and network settings without requiring a USB/TTY converter.

## 1. Is this topology supported by current code?

Yes.

- Modbus transport supports `tcp` and `serial` in `backend/app/modbus_sensor_config.py`.
- Runtime client supports `ModbusTcpClient` in `backend/app/sensor_data.py`.
- Three temperature channels are already mapped in `SENSOR_REGISTER_MAP`.
- Flow meter is already supported as a separate logical read path in `FLOW_METER_CONFIG`.

No Python code change is required for normal field register remapping.

## 2. Which file should be edited in field deployment?

Primary file:

- `docker-compose.yml` (backend service environment block)

Optional file (only if you prefer `.env` driven values):

- Create/update a `.env` used by compose and reference variables in `docker-compose.yml`.

Do not edit Python files for routine address updates.

## 3. Required compose changes for Ethernet gateway (no TTYUSB)

In `docker-compose.yml`, set backend env like this:

```yaml
MODBUS_ENABLED=true
MODBUS_TRANSPORT=tcp
MODBUS_HOST=<WAVESHARE_IP>
MODBUS_TCP_PORT=502
MODBUS_SLAVE_ID=1

# Keep these present but unused in tcp mode
MODBUS_PORT=/dev/ttyUSB0
MODBUS_BAUDRATE=9600
MODBUS_BYTESIZE=8
MODBUS_PARITY=N
MODBUS_STOPBITS=1
```

Important:

- When `MODBUS_TRANSPORT=tcp`, the code uses host/port and does not require TTYUSB for the datalogger path.

## 4. Temperature register mapping (3 sensors from data logger)

The backend reads these logical keys:

- `hot_zone_temperature`
- `cold_zone_temperature`
- `exhaust_temp`

Set these env vars in `docker-compose.yml` to remap field registers:

```yaml
MODBUS_ADDR_HOT_ZONE_VALUE=<reg>
MODBUS_ADDR_HOT_ZONE_DECIMAL=<reg>
MODBUS_ADDR_HOT_ZONE_STATUS=<reg>

MODBUS_ADDR_COLD_ZONE_VALUE=<reg>
MODBUS_ADDR_COLD_ZONE_DECIMAL=<reg>
MODBUS_ADDR_COLD_ZONE_STATUS=<reg>

MODBUS_ADDR_EXHAUST_VALUE=<reg>
MODBUS_ADDR_EXHAUST_DECIMAL=<reg>
MODBUS_ADDR_EXHAUST_STATUS=<reg>
```

Scaling/address normalization options:

```yaml
MODBUS_REGISTER_TYPE=holding
MODBUS_ADDRESS_BASE=0
MODBUS_ADDRESS_OFFSET=0
```

Use `MODBUS_ADDRESS_BASE` when your manual lists logical addresses like `40001` or `30001`.

Example:

- Manual says CH1 value is `40011`
- Use `MODBUS_ADDRESS_BASE=40001`
- Set `MODBUS_ADDR_HOT_ZONE_VALUE=40011`
- Effective wire address becomes `10`

## 5. Flow meter configuration

Two common field patterns are supported.

### Pattern A: flow is read from same Waveshare endpoint (recommended for your topology)

```yaml
FLOW_METER_ENABLED=true
FLOW_METER_TRANSPORT=tcp
FLOW_METER_HOST=<WAVESHARE_IP>
FLOW_METER_TCP_PORT=502
FLOW_METER_SLAVE_ID=1

FLOW_METER_REGISTER_TYPE=holding
FLOW_METER_VALUE_ADDRESS=<flow_reg>
FLOW_METER_DECIMAL_ADDRESS=<optional_reg_or_blank>
FLOW_METER_STATUS_ADDRESS=<optional_reg_or_blank>

FLOW_METER_ADDRESS_BASE=0
FLOW_METER_ADDRESS_OFFSET=0
FLOW_METER_SCALE=0.1
FLOW_METER_OFFSET=0.0
FLOW_METER_SIGNED=false
```

### Pattern B: flow meter disabled in software

```yaml
FLOW_METER_ENABLED=false
```

## 6. Rebuild and restart after config change

From project root on Jetson:

```bash
docker-compose up -d --build jetson-backend
```

If your backend uses NVIDIA runtime script in production, run:

```bash
./scripts/run_backend_with_nvidia_runtime.sh
```

## 6.1 Field update flow when containers are already running

Use this when backend/frontend containers are already running and you changed IP/register env values.

### Option A: Backend-only refresh (recommended for sensor config changes)

1) Stop backend container:

```bash
docker-compose stop jetson-backend
```

2) Remove existing backend container:

```bash
docker-compose rm -f jetson-backend
```

3) Rebuild backend image:

```bash
docker-compose build --no-cache jetson-backend
```

4) (Optional) prune dangling images/layers:

```bash
docker image prune -f
docker builder prune -f
```

5) Start backend again:

```bash
docker-compose up -d jetson-backend
```

6) If your site uses NVIDIA runtime mode, run this instead of step 5:

```bash
./scripts/run_backend_with_nvidia_runtime.sh
```

### Option B: Full stack refresh (backend + frontend)

1) Stop all project containers:

```bash
docker-compose down --remove-orphans
```

2) (Optional) remove old images for this project only:

```bash
docker rmi jetsonnanowebrtcdashboard_jetson-backend:latest || true
docker rmi jetsonnanowebrtcdashboard_jetson-frontend:latest || true
```

3) Rebuild and start full stack:

```bash
docker-compose up -d --build
```

4) If backend should run in NVIDIA runtime mode, run after stack starts:

```bash
./scripts/run_backend_with_nvidia_runtime.sh
```

### Optional deep cleanup (use carefully)

This removes unused containers, networks, images, and build cache system-wide:

```bash
docker system prune -af
```

Run this only when you understand impact on other projects.

## 7. Validation checklist

1. Backend health:

```bash
curl -s http://localhost:8000/health
```

2. Live sensor output:

```bash
curl -s http://localhost:8000/api/sensors/latest
```

3. Expected source field:

- `source: "modbus"` means logger + flow reads are both working.
- `source: "modbus_partial"` means only one side is working.
- `source: "modbus_unavailable"` means modbus reads failed.

4. If values are empty, check:

- `MODBUS_HOST` / `FLOW_METER_HOST` IP
- slave ID
- register type (`holding` vs `input`)
- base/offset
- register addresses and decimals

## 8. When is Python code change actually needed?

Python edits are only needed if you want to change data model shape, for example:

- Add a fourth temperature key to API payload as a first-class field
- Rename logical sensor keys returned by `/api/sensors/latest`
- Merge flow read into the same Modbus client session by design

For normal field retuning (IP, slave ID, register addresses, scale, decimal), only environment/config changes are required.

## 9. Field troubleshooting commands (copy/paste)

1) Check backend and frontend status:

`docker-compose ps`

`curl -s -o /dev/null -w 'backend:%{http_code}\n' http://127.0.0.1:8000/docs`

`curl -s -o /dev/null -w 'frontend:%{http_code}\n' http://127.0.0.1:80/`

2) Check live sensor payload and source:

`curl -s http://127.0.0.1:8000/api/sensors/latest`

3) Inspect backend logs for Modbus and flow errors:

`docker logs --tail 300 jetson-nano-backend`

`docker logs --tail 300 jetson-nano-backend | grep -Ei 'modbus|flow|connect|timeout|unavailable|exception'`

4) Verify effective backend environment values:

`docker exec -it jetson-nano-backend sh -lc "env | grep -E 'MODBUS_|FLOW_METER_' | sort"`

5) Confirm gateway reachability from Jetson:

`ping -c 3 <WAVESHARE_IP>`

`nc -vz <WAVESHARE_IP> 502`

6) If backend failed after recreate, recover quickly:

`docker rm -f jetson-nano-backend`

`./scripts/run_backend_with_nvidia_runtime.sh`


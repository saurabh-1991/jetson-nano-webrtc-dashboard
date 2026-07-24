# Operator Quick Card — v1.2.0

Fast commands for field operators.

## 1) Open dashboard (same LAN)

Primary:

- `http://jetson-dashboard.local/`

Fallback:

- `http://<JETSON_IPV4>/`

## 2) Quick health check (from laptop)

```bash
curl -sS http://jetson-dashboard.local/api/system/status
curl -sS http://jetson-dashboard.local/api/stats
```

## 3) Quick health check (on Jetson)

```bash
systemctl is-active jetson-dashboard.service
systemctl is-active avahi-daemon
docker ps --format 'table {{.Names}}\t{{.Status}}'
curl -sS http://127.0.0.1:8000/health
```

## 4) If dashboard is not loading

Run on Jetson:

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
bash ./scripts/check_lan_access.sh
```

Then use the printed Primary/Fallback URL.

## 5) Restart application stack

```bash
cd /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard
docker-compose down --remove-orphans
docker-compose up -d --build
docker-compose ps
```

## 6) Camera stream recovery (v1.2.0)

### A. Automatic behavior

- Start Video will try WebRTC first and automatically switch to MJPEG on Jetson when WebRTC is unavailable.
- Camera fail-safe attempts recovery when camera read/open path is unhealthy.

### B. Manual operator recovery

Use dashboard button in **Status / Indicator → Camera**:

- Click **Reset Camera**.
- If camera is active, confirm the prompt (stream may pause briefly).
- Wait for confirmation message: `Camera recovery completed.`

### C. API fallback for remote operators

```bash
curl -sS -X POST http://jetson-dashboard.local/api/camera/recover \
  -H "Content-Type: application/json" \
  -d '{"reason":"operator_manual_recover"}'
```

## 7) Power-glitch resilience quick checks

Run on Jetson after power/network recovery:

```bash
systemctl is-enabled docker
systemctl is-active docker
systemctl is-enabled jetson-dashboard.service
docker inspect -f '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}' \
  jetson-nano-backend jetson-nano-frontend jetson-docker-prune
```

Expected:

- Docker active and enabled
- `jetson-dashboard.service` enabled
- Containers restart policy `unless-stopped`

## 8) If `.local` works in browser but SSH fails

Use IPv4 for SSH:

```bash
ssh saurabh@<JETSON_IPV4>
```

Keep `.local` for browser access.

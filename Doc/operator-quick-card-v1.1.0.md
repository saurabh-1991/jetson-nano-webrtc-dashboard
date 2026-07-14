# Operator Quick Card — v1.1.0

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
docker-compose up -d
docker-compose ps
```

## 6) If `.local` works in browser but SSH fails

Use IPv4 for SSH:

```bash
ssh saurabh@<JETSON_IPV4>
```

Keep `.local` for browser access.

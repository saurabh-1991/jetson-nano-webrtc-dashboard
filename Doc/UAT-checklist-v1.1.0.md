# UAT Checklist — Jetson Nano WebRTC Dashboard v1.1.0

Use this checklist for final acceptance testing on target Jetson + local LAN.

## Environment

- [ ] Jetson Nano powered on and connected to LAN
- [ ] Project branch: `poc_demo_v1.1.0`
- [ ] Dashboard reachable at `http://jetson-dashboard.local/` (or IPv4 fallback)

## Boot & startup

- [ ] `jetson-dashboard.service` is `enabled`
- [ ] `jetson-dashboard.service` is `active`
- [ ] `avahi-daemon` is `enabled` and `active`
- [ ] Backend container is `Up (healthy)`
- [ ] Frontend container is `Up`

## Connectivity & deployment behavior

- [ ] Browser opens `http://jetson-dashboard.local/`
- [ ] `GET /api/system/status` returns valid JSON
- [ ] `GET /health` returns `{"status":"healthy"...}`
- [ ] mDNS works after reboot (same `.local` URL)

## Camera & streaming

- [ ] Start Video works
- [ ] Stream displays in dashboard
- [ ] Stop Video releases stream correctly
- [ ] Multi-viewer behavior is stable (no severe lag or freezing)

## GPIO outputs

- [ ] Exhaust Blower toggles ON/OFF
- [ ] Air Mixer Blower toggles ON/OFF
- [ ] LPG Burner toggles ON/OFF
- [ ] UI state matches backend GPIO state

## Input signals / indicators

- [ ] Input cards show LED status correctly
- [ ] Input cards show associated `BOARD Pin` values
- [ ] Signal transitions reflect in UI refresh cycle

## Power-cycle simulation

- [ ] `docker-compose down --remove-orphans` then `docker-compose up -d` recovers services
- [ ] Dashboard and API are reachable after restart simulation

## Documentation

- [ ] `DEPLOYMENT.md` includes local-LAN remote workflow
- [ ] `Doc/new-local-network-deployment.md` is usable by a new operator
- [ ] Operator quick card is available (`Doc/operator-quick-card-v1.1.0.md`)

## Final sign-off

- [ ] UAT Pass
- [ ] Date:
- [ ] Tested by:
- [ ] Notes:

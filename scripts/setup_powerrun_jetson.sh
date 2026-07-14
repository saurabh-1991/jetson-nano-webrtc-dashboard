#!/usr/bin/env bash
set -euo pipefail

# Power-run bootstrap for Jetson Nano:
# 1) Optional root autologin (desktop)
# 2) Auto-start dashboard stack at boot via systemd service
# 3) Hooks for static IP script (run separately with your network values)

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] Run as root (sudo)."
  exit 1
fi

PROJECT_DIR_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$PROJECT_DIR_DEFAULT}"
AUTOLOGIN_USER="${AUTOLOGIN_USER:-root}"
ENABLE_AUTOLOGIN="${ENABLE_AUTOLOGIN:-true}"
ENABLE_ROOT_ACCOUNT="${ENABLE_ROOT_ACCOUNT:-false}"
ROOT_PASSWORD="${ROOT_PASSWORD:-}"
START_ON_BOOT="${START_ON_BOOT:-true}"
START_NOW="${START_NOW:-true}"
ENABLE_MDNS="${ENABLE_MDNS:-true}"
MDNS_HOSTNAME="${MDNS_HOSTNAME:-jetson-dashboard}"

SERVICE_FILE="/etc/systemd/system/jetson-dashboard.service"
LIGHTDM_FILE="/etc/lightdm/lightdm.conf.d/90-jetson-dashboard-autologin.conf"

if [[ ! -f "$PROJECT_DIR/docker-compose.yml" ]]; then
  echo "[ERROR] docker-compose.yml not found in PROJECT_DIR='$PROJECT_DIR'"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker not installed"
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "[ERROR] docker-compose not installed"
  exit 1
fi

enable_root_if_requested() {
  if [[ "$ENABLE_ROOT_ACCOUNT" != "true" ]]; then
    return
  fi

  if [[ -z "$ROOT_PASSWORD" ]]; then
    echo "[ERROR] ENABLE_ROOT_ACCOUNT=true requires ROOT_PASSWORD env var"
    exit 1
  fi

  echo "root:${ROOT_PASSWORD}" | chpasswd
  echo "[OK] Root account password configured"
}

configure_lightdm_autologin() {
  if [[ "$ENABLE_AUTOLOGIN" != "true" ]]; then
    echo "[INFO] Desktop autologin skipped (ENABLE_AUTOLOGIN=false)"
    return
  fi

  mkdir -p /etc/lightdm/lightdm.conf.d
  cat > "$LIGHTDM_FILE" <<EOF
[Seat:*]
autologin-user=${AUTOLOGIN_USER}
autologin-user-timeout=0
allow-guest=false
EOF

  echo "[OK] LightDM autologin configured for user '${AUTOLOGIN_USER}'"
}

configure_mdns_discovery() {
  if [[ "$ENABLE_MDNS" != "true" ]]; then
    echo "[INFO] mDNS discovery skipped (ENABLE_MDNS=false)"
    return
  fi

  if ! command -v avahi-daemon >/dev/null 2>&1; then
    echo "[INFO] Installing mDNS packages (avahi-daemon, libnss-mdns, avahi-utils)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y avahi-daemon libnss-mdns avahi-utils
  fi

  if [[ -n "$MDNS_HOSTNAME" ]]; then
    hostnamectl set-hostname "$MDNS_HOSTNAME"
  fi

  mkdir -p /etc/avahi/services
  cat > /etc/avahi/services/jetson-dashboard-http.service <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_http._tcp</type>
    <port>80</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
EOF

  systemctl enable avahi-daemon
  systemctl restart avahi-daemon

  echo "[OK] mDNS enabled. Try URL: http://${MDNS_HOSTNAME}.local/"
}

install_dashboard_service() {
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Jetson Nano Dashboard (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/docker-compose -f ${PROJECT_DIR}/docker-compose.yml up -d
ExecStop=/usr/bin/docker-compose -f ${PROJECT_DIR}/docker-compose.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable docker.service

  if [[ "$START_ON_BOOT" == "true" ]]; then
    systemctl enable jetson-dashboard.service
  fi

  if [[ "$START_NOW" == "true" ]]; then
    systemctl restart jetson-dashboard.service
  fi

  echo "[OK] Systemd service installed: $SERVICE_FILE"
}

enable_root_if_requested
configure_lightdm_autologin
configure_mdns_discovery
install_dashboard_service

echo ""
echo "[DONE] Power-run bootstrap complete"
echo "Service status:"
systemctl --no-pager --full status jetson-dashboard.service || true
echo ""
echo "Next: configure static IP if needed:"
echo "  sudo ${PROJECT_DIR}/scripts/configure_static_ip_nmcli.sh --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8"
echo "  sudo ${PROJECT_DIR}/scripts/configure_static_ip_nmcli.sh --wifi-ssid <SSID> --wifi-password <PASS> --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8"

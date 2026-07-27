#!/usr/bin/env bash
set -euo pipefail

# One-command power-run setup for Jetson Nano.
# This wrapper runs:
#   1) setup_powerrun_jetson.sh   (autologin + systemd boot service)
#   2) configure_static_ip_nmcli.sh (optional static IP on eth/wifi)
#
# Example (root autologin + eth static + wifi static):
#   sudo ./scripts/powerrun_apply_all.sh \
#     --project-dir /home/saurabh/Saurabh/Jetson_Nano_WebRTC_POC/jetson-nano-webrtc-dashboard \
#     --autologin-user root --enable-root-account --root-password 'ChangeMeNow!' \
#     --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8 \
#     --wifi-ssid MyRouter --wifi-password MyPass123 \
#     --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] Run as root (sudo)."
  exit 1
fi

PROJECT_DIR_DEFAULT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$PROJECT_DIR_DEFAULT"
CONFIG_FILE=""
AUTOLOGIN_USER="root"
ENABLE_AUTOLOGIN="true"
ENABLE_ROOT_ACCOUNT="false"
ROOT_PASSWORD=""
START_ON_BOOT="true"
START_NOW="true"
COMPOSE_REBUILD_ON_BOOT="false"
ENABLE_MDNS="true"
MDNS_HOSTNAME="jetson-dashboard"

ETH_DEVICE="eth0"
ETH_IP=""
ETH_GATEWAY=""
ETH_DNS=""

WIFI_DEVICE="wlan0"
WIFI_SSID=""
WIFI_PASSWORD=""
WIFI_IP=""
WIFI_GATEWAY=""
WIFI_DNS=""

print_help() {
  cat <<'EOF'
Usage: sudo ./scripts/powerrun_apply_all.sh [options]

Boot/service options:
  --project-dir <path>
  --config <file>                (default: <project-dir>/scripts/powerrun.config)
  --autologin-user <user>         (default: root)
  --disable-autologin             (default: enabled)
  --enable-root-account           (requires --root-password)
  --root-password <password>
  --disable-start-on-boot         (default: enabled)
  --disable-start-now             (default: enabled)
  --enable-rebuild-on-boot        (default: disabled / offline-safe no-build)
  --disable-mdns                  (default: enabled)
  --mdns-hostname <hostname>      (default: jetson-dashboard)

Ethernet static IPv4 options:
  --eth-device <dev>              (default: eth0)
  --eth-ip <CIDR>
  --eth-gateway <ip>
  --eth-dns <dns1,dns2>

Wi-Fi static IPv4 options:
  --wifi-device <dev>             (default: wlan0)
  --wifi-ssid <ssid>
  --wifi-password <pass>
  --wifi-ip <CIDR>
  --wifi-gateway <ip>
  --wifi-dns <dns1,dns2>

Examples:
  sudo ./scripts/powerrun_apply_all.sh --autologin-user saurabh \
    --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8

  sudo ./scripts/powerrun_apply_all.sh --autologin-user root --enable-root-account \
    --root-password 'ChangeMeNow!' \
    --wifi-ssid MyRouter --wifi-password MyPass123 \
    --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8
EOF
}

load_config_file() {
  local cfg="$1"
  if [[ -f "$cfg" ]]; then
    echo "[INFO] Loading config: $cfg"
    # shellcheck disable=SC1090
    source "$cfg"
  else
    echo "[INFO] Config not found, using defaults/CLI: $cfg"
  fi
}

# First pass: read --project-dir / --config before loading config defaults.
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --project-dir)
      if (( i + 1 < ${#ARGS[@]} )); then
        PROJECT_DIR="${ARGS[$((i + 1))]}"
      fi
      ;;
    --config)
      if (( i + 1 < ${#ARGS[@]} )); then
        CONFIG_FILE="${ARGS[$((i + 1))]}"
      fi
      ;;
  esac
done

if [[ -z "$CONFIG_FILE" ]]; then
  CONFIG_FILE="$PROJECT_DIR/scripts/powerrun.config"
fi

load_config_file "$CONFIG_FILE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      print_help
      exit 0
      ;;

    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --config) CONFIG_FILE="$2"; shift 2 ;;
    --autologin-user) AUTOLOGIN_USER="$2"; shift 2 ;;
    --disable-autologin) ENABLE_AUTOLOGIN="false"; shift 1 ;;
    --enable-root-account) ENABLE_ROOT_ACCOUNT="true"; shift 1 ;;
    --root-password) ROOT_PASSWORD="$2"; shift 2 ;;
    --disable-start-on-boot) START_ON_BOOT="false"; shift 1 ;;
    --disable-start-now) START_NOW="false"; shift 1 ;;
    --enable-rebuild-on-boot) COMPOSE_REBUILD_ON_BOOT="true"; shift 1 ;;
    --disable-mdns) ENABLE_MDNS="false"; shift 1 ;;
    --mdns-hostname) MDNS_HOSTNAME="$2"; shift 2 ;;

    --eth-device) ETH_DEVICE="$2"; shift 2 ;;
    --eth-ip) ETH_IP="$2"; shift 2 ;;
    --eth-gateway) ETH_GATEWAY="$2"; shift 2 ;;
    --eth-dns) ETH_DNS="$2"; shift 2 ;;

    --wifi-device) WIFI_DEVICE="$2"; shift 2 ;;
    --wifi-ssid) WIFI_SSID="$2"; shift 2 ;;
    --wifi-password) WIFI_PASSWORD="$2"; shift 2 ;;
    --wifi-ip) WIFI_IP="$2"; shift 2 ;;
    --wifi-gateway) WIFI_GATEWAY="$2"; shift 2 ;;
    --wifi-dns) WIFI_DNS="$2"; shift 2 ;;

    *)
      echo "[ERROR] Unknown argument: $1"
      print_help
      exit 1
      ;;
  esac
done

if [[ "$ENABLE_ROOT_ACCOUNT" == "true" && -z "$ROOT_PASSWORD" ]]; then
  echo "[ERROR] --enable-root-account requires --root-password"
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/docker-compose.yml" ]]; then
  echo "[ERROR] Invalid --project-dir. docker-compose.yml not found in: $PROJECT_DIR"
  exit 1
fi

SETUP_SCRIPT="$PROJECT_DIR/scripts/setup_powerrun_jetson.sh"
IP_SCRIPT="$PROJECT_DIR/scripts/configure_static_ip_nmcli.sh"

if [[ ! -x "$SETUP_SCRIPT" ]]; then
  chmod +x "$SETUP_SCRIPT"
fi
if [[ ! -x "$IP_SCRIPT" ]]; then
  chmod +x "$IP_SCRIPT"
fi

echo "[STEP 1/2] Configure autologin + startup service"
AUTOLOGIN_USER="$AUTOLOGIN_USER" \
ENABLE_AUTOLOGIN="$ENABLE_AUTOLOGIN" \
ENABLE_ROOT_ACCOUNT="$ENABLE_ROOT_ACCOUNT" \
ROOT_PASSWORD="$ROOT_PASSWORD" \
START_ON_BOOT="$START_ON_BOOT" \
START_NOW="$START_NOW" \
COMPOSE_REBUILD_ON_BOOT="$COMPOSE_REBUILD_ON_BOOT" \
ENABLE_MDNS="$ENABLE_MDNS" \
MDNS_HOSTNAME="$MDNS_HOSTNAME" \
CONFIG_FILE="$CONFIG_FILE" \
PROJECT_DIR="$PROJECT_DIR" \
"$SETUP_SCRIPT"

STATIC_ARGS=()
if [[ -n "$ETH_IP" ]]; then
  STATIC_ARGS+=(--eth-device "$ETH_DEVICE" --eth-ip "$ETH_IP" --eth-gateway "$ETH_GATEWAY" --eth-dns "$ETH_DNS")
fi
if [[ -n "$WIFI_IP" ]]; then
  STATIC_ARGS+=(--wifi-device "$WIFI_DEVICE" --wifi-ssid "$WIFI_SSID" --wifi-password "$WIFI_PASSWORD" --wifi-ip "$WIFI_IP" --wifi-gateway "$WIFI_GATEWAY" --wifi-dns "$WIFI_DNS")
fi

if [[ ${#STATIC_ARGS[@]} -gt 0 ]]; then
  echo "[STEP 2/2] Configure static IP settings"
  "$IP_SCRIPT" "${STATIC_ARGS[@]}"
else
  echo "[STEP 2/2] Static IP skipped (no --eth-ip/--wifi-ip provided)"
fi

echo ""
echo "[DONE] Power-run one-shot setup complete."
echo "Config used: $CONFIG_FILE"
echo "Recommended final action: reboot Jetson once."

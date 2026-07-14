#!/usr/bin/env bash
set -euo pipefail

# Configure persistent static IPv4 using NetworkManager (JetPack/Ubuntu desktop friendly).
# Usage examples:
#   sudo ./scripts/configure_static_ip_nmcli.sh \
#     --eth-ip 192.168.1.50/24 --eth-gateway 192.168.1.1 --eth-dns 192.168.1.1,8.8.8.8
#
#   sudo ./scripts/configure_static_ip_nmcli.sh \
#     --wifi-ssid MyRouter --wifi-password MyPass123 \
#     --wifi-ip 192.168.1.60/24 --wifi-gateway 192.168.1.1 --wifi-dns 192.168.1.1,8.8.8.8

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] Run as root (sudo)."
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "[ERROR] nmcli not found. Install NetworkManager first."
  exit 1
fi

ETH_DEVICE="eth0"
WIFI_DEVICE="wlan0"

ETH_IP=""
ETH_GATEWAY=""
ETH_DNS=""

WIFI_SSID=""
WIFI_PASSWORD=""
WIFI_IP=""
WIFI_GATEWAY=""
WIFI_DNS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
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
      exit 1
      ;;
  esac
done

find_active_connection_for_device() {
  local dev="$1"
  nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$dev" '$2==d {print $1; exit}'
}

device_exists() {
  local dev="$1"
  nmcli -t -f DEVICE device status | awk -F: -v d="$dev" '$1==d {found=1} END {exit(found?0:1)}'
}

device_is_unavailable() {
  local dev="$1"
  local state
  state="$(nmcli -t -f GENERAL.STATE device show "$dev" 2>/dev/null | head -n1 | cut -d: -f2- || true)"

  # Typical unavailable state looks like: "20 (unavailable)"
  [[ "$state" == *"unavailable"* ]]
}

ensure_ethernet_connection() {
  local dev="$1"
  local conn
  conn="$(find_active_connection_for_device "$dev" || true)"
  if [[ -n "$conn" ]]; then
    echo "$conn"
    return
  fi

  conn="jetson-${dev}-static"
  nmcli connection add type ethernet ifname "$dev" con-name "$conn" >/dev/null
  echo "$conn"
}

ensure_wifi_connection() {
  local dev="$1"
  local ssid="$2"
  local conn
  conn="$(find_active_connection_for_device "$dev" || true)"
  if [[ -n "$conn" ]]; then
    echo "$conn"
    return
  fi

  conn="jetson-${dev}-${ssid}"
  nmcli connection add type wifi ifname "$dev" con-name "$conn" ssid "$ssid" >/dev/null
  echo "$conn"
}

apply_static_ipv4() {
  local conn="$1"
  local ip="$2"
  local gateway="$3"
  local dns="$4"

  nmcli connection modify "$conn" \
    ipv4.addresses "$ip" \
    ipv4.gateway "$gateway" \
    ipv4.dns "$dns" \
    ipv4.method manual \
    connection.autoconnect yes
}

if [[ -n "$ETH_IP" ]]; then
  if [[ -z "$ETH_GATEWAY" || -z "$ETH_DNS" ]]; then
    echo "[ERROR] Ethernet static config requires --eth-gateway and --eth-dns"
    exit 1
  fi

  if ! device_exists "$ETH_DEVICE"; then
    echo "[WARN] Ethernet device '$ETH_DEVICE' not found. Skipping Ethernet static IP configuration."
  elif device_is_unavailable "$ETH_DEVICE"; then
    echo "[WARN] Ethernet device '$ETH_DEVICE' is unavailable. Skipping Ethernet static IP configuration."
  else
  ETH_CONN="$(ensure_ethernet_connection "$ETH_DEVICE")"
  apply_static_ipv4 "$ETH_CONN" "$ETH_IP" "$ETH_GATEWAY" "$ETH_DNS"
  nmcli connection up "$ETH_CONN" || true
  echo "[OK] Ethernet static IP applied on $ETH_DEVICE via connection '$ETH_CONN'"
  fi
fi

if [[ -n "$WIFI_IP" ]]; then
  if [[ -z "$WIFI_SSID" || -z "$WIFI_PASSWORD" || -z "$WIFI_GATEWAY" || -z "$WIFI_DNS" ]]; then
    echo "[ERROR] Wi-Fi static config requires --wifi-ssid --wifi-password --wifi-gateway --wifi-dns"
    exit 1
  fi

  if ! device_exists "$WIFI_DEVICE"; then
    echo "[WARN] Wi-Fi device '$WIFI_DEVICE' not found. Skipping Wi-Fi static IP configuration."
  elif device_is_unavailable "$WIFI_DEVICE"; then
    echo "[WARN] Wi-Fi device '$WIFI_DEVICE' is unavailable. Skipping Wi-Fi static IP configuration."
  else

  WIFI_CONN="$(ensure_wifi_connection "$WIFI_DEVICE" "$WIFI_SSID")"
  nmcli connection modify "$WIFI_CONN" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$WIFI_PASSWORD" \
    connection.autoconnect yes

  apply_static_ipv4 "$WIFI_CONN" "$WIFI_IP" "$WIFI_GATEWAY" "$WIFI_DNS"
  nmcli connection up "$WIFI_CONN" || true
  echo "[OK] Wi-Fi static IP applied on $WIFI_DEVICE via connection '$WIFI_CONN'"
  fi
fi

if [[ -z "$ETH_IP" && -z "$WIFI_IP" ]]; then
  echo "[WARN] No static IP changes requested."
fi

echo "[DONE] Current device IPv4 summary:"
nmcli -p -f GENERAL.DEVICE,IP4.ADDRESS,IP4.GATEWAY device show "$ETH_DEVICE" 2>/dev/null || true
nmcli -p -f GENERAL.DEVICE,IP4.ADDRESS,IP4.GATEWAY device show "$WIFI_DEVICE" 2>/dev/null || true

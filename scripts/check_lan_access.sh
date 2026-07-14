#!/usr/bin/env bash
set -euo pipefail

# Quick LAN diagnostics for Jetson dashboard deployments.
# Run on Jetson host:
#   bash ./scripts/check_lan_access.sh

if ! command -v nmcli >/dev/null 2>&1; then
  echo "[ERROR] nmcli not found. This script expects NetworkManager tools."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[ERROR] curl not found. Install curl and retry."
  exit 1
fi

HOSTNAME_NOW="$(hostname 2>/dev/null || echo unknown)"
MDNS_URL="http://${HOSTNAME_NOW}.local/"

echo "============================================================"
echo "Jetson Dashboard LAN Diagnostics"
echo "============================================================"
echo "Hostname       : ${HOSTNAME_NOW}"
echo "mDNS URL       : ${MDNS_URL}"
echo "Timestamp      : $(date -Is)"
echo ""

echo "[1/6] Network interfaces (active state + IPv4):"
nmcli device status || true
echo ""
ip -4 addr show | awk '/^[0-9]+: /{iface=$2; sub(":","",iface)} /inet /{print "  " iface " -> " $2}'
echo ""

echo "[2/6] Service health:"
if command -v systemctl >/dev/null 2>&1; then
  echo "  jetson-dashboard.service : $(systemctl is-active jetson-dashboard.service 2>/dev/null || echo unknown)"
  echo "  avahi-daemon             : $(systemctl is-active avahi-daemon 2>/dev/null || echo unknown)"
  echo "  docker                   : $(systemctl is-active docker 2>/dev/null || echo unknown)"
else
  echo "  systemctl not available"
fi
echo ""

echo "[3/6] Containers:"
if command -v docker >/dev/null 2>&1; then
  docker ps --format '  {{.Names}} | {{.Status}} | {{.Ports}}' || true
else
  echo "  docker command not found"
fi
echo ""

echo "[4/6] Local API checks (from Jetson itself):"
if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null; then
  echo "  /health                 : OK"
else
  echo "  /health                 : FAIL"
fi

if curl -fsS --max-time 5 http://127.0.0.1/api/system/status >/dev/null; then
  echo "  /api/system/status      : OK"
else
  echo "  /api/system/status      : FAIL"
fi
echo ""

echo "[5/6] Hostname API checks:"
if curl -fsS --max-time 5 "http://${HOSTNAME_NOW}.local/api/system/status" >/dev/null; then
  echo "  ${HOSTNAME_NOW}.local      : OK"
else
  echo "  ${HOSTNAME_NOW}.local      : FAIL (may still be reachable from other LAN clients)"
fi
echo ""

echo "[6/6] Recommended access URLs for operators:"
echo "  Primary  : http://${HOSTNAME_NOW}.local/"

PRIMARY_IPV4="$(ip -4 -o addr show scope global | awk '{split($4,a,"/"); print a[1]; exit}')"
if [[ -n "${PRIMARY_IPV4}" ]]; then
  echo "  Fallback : http://${PRIMARY_IPV4}/"
fi

echo ""
echo "[DONE] Diagnostics complete."
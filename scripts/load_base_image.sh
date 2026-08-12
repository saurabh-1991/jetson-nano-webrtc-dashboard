#!/usr/bin/env bash
set -euo pipefail

# Load a frozen base image tarball (produced by scripts/build_base_image.sh)
# on a field/offline Jetson device. No internet or registry access needed -
# the field engineer only needs to scp/USB-copy the .tar.gz onto the device.
#
# Usage:
#   ./scripts/load_base_image.sh /path/to/jetson-backend-base_jp46-opencv455-v1.tar.gz

TARBALL="${1:?Usage: $0 /path/to/base-image.tar.gz}"

if [[ ! -f "${TARBALL}" ]]; then
  echo "[load-base] ERROR: file not found: ${TARBALL}"
  exit 1
fi

if [[ -f "${TARBALL}.sha256" ]]; then
  echo "[load-base] Verifying checksum..."
  (cd "$(dirname "${TARBALL}")" && sha256sum -c "$(basename "${TARBALL}").sha256")
else
  echo "[load-base] WARN: no .sha256 file found alongside tarball; skipping integrity check."
fi

echo "[load-base] Loading image from ${TARBALL} ..."
gunzip -c "${TARBALL}" | docker load

echo "[load-base] Done. Verify with: docker images | grep jetson-backend-base"
echo "[load-base] Then build the thin app image with:"
echo "[load-base]   docker-compose build jetson-backend"

#!/usr/bin/env bash
set -euo pipefail

# Build and freeze the base image (system deps + OpenCV/CUDA compiled from
# source). This is the expensive, slow step (45-90+ min on Jetson Nano) and
# should only be run when JetPack/OpenCV/system deps actually change - NOT
# for regular app code changes (those use the thin Dockerfile.jetpack46
# which extends this frozen base and rebuilds in seconds).
#
# Output: a compressed tarball under dist/ that a field engineer can copy
# via USB/scp to any Jetson (no internet/registry required) and load with
# scripts/load_base_image.sh.
#
# Usage:
#   ./scripts/build_base_image.sh [BASE_IMAGE_TAG]
#
# Example:
#   ./scripts/build_base_image.sh jetson-backend-base:jp46-opencv455-v1

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_IMAGE_TAG="${1:-jetson-backend-base:jp46-opencv455-v1}"
DIST_DIR="${PROJECT_DIR}/dist"

cd "${PROJECT_DIR}/backend"

echo "[build-base] Building ${BASE_IMAGE_TAG} from Dockerfile.jetpack46.base ..."
echo "[build-base] This compiles OpenCV+CUDA from source and can take 45-90+ minutes."
docker build -f Dockerfile.jetpack46.base -t "${BASE_IMAGE_TAG}" .

mkdir -p "${DIST_DIR}"
SAFE_NAME="$(echo "${BASE_IMAGE_TAG}" | tr '/:' '__')"
TARBALL="${DIST_DIR}/${SAFE_NAME}.tar.gz"

echo "[build-base] Exporting image to ${TARBALL} for offline field distribution..."
docker save "${BASE_IMAGE_TAG}" | gzip > "${TARBALL}"

SHA256="$(sha256sum "${TARBALL}" | awk '{print $1}')"
echo "${SHA256}  $(basename "${TARBALL}")" > "${TARBALL}.sha256"

echo "[build-base] Done."
echo "[build-base] Image:    ${BASE_IMAGE_TAG}"
echo "[build-base] Tarball:  ${TARBALL}"
echo "[build-base] SHA256:   ${SHA256}"
echo "[build-base] Copy the .tar.gz (and .sha256) to the field device, then run:"
echo "[build-base]   ./scripts/load_base_image.sh ${TARBALL}"

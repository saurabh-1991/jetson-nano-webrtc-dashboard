# JetPack 4.6 HW Acceleration Safe Trial Report (2026-07-27)

## Safety Objective

Performed **read-only diagnostics** on the running target (`192.168.1.11`) without stopping services or changing active runtime settings.

- No `docker-compose down`
- No package install on running host/container
- No camera pipeline replacement during live operation

## Live App Baseline and Post-Check

- Pre-check: `/health` = healthy, both cameras active
- Post-check: `/health` = healthy, both cameras active
- Conclusion: **current working application not hampered** during this trial

## Captured Errors / Evidence

### Phase A isolated validation result (non-disruptive)

- Running image `jetsonnanowebrtcdashboard_jetson-backend:latest` in a **throwaway** container with `--runtime nvidia` exposed NVIDIA plugins successfully:
  - `gst-inspect-1.0 nvvidconv` => plugin details present
  - `gst-inspect-1.0 nvjpegdec` => plugin details present
- Running production backend container `jetson-nano-backend` currently shows:
  - `docker inspect ... HostConfig.Runtime` => `runc`
  - `gst-inspect-1.0 nvvidconv` => `No such element or plugin 'nvvidconv'`
  - `ls /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstnv*` => none

Interpretation:

- The **image is capable**, but the **live container runtime selection prevents NVIDIA mount plugin injection**.
- This is consistent with NVIDIA container runtime documentation: device and userspace mounts are runtime-driven.

### 1) OpenCV build in container is not CUDA/GStreamer capable

From backend runtime logs and diagnostics:

- `OpenCV build reports GStreamer backend disabled; USB capture will use V4L2 fallback`
- `OpenCV build has no cv2.cuda module; using CPU fallback`

Observed package:

- `python3-opencv 3.2.0+dfsg-4ubuntu0.1`

Impact:

- `cv2.CAP_GSTREAMER` path cannot be used effectively in current container build
- `cv2.cuda` processing path unavailable

### 2) NVIDIA accelerated GStreamer plugins not present in backend container

Command output:

- `gst-inspect-1.0 nvjpegdec` -> `No such element or plugin 'nvjpegdec'`
- `gst-inspect-1.0 nvvidconv` -> `No such element or plugin 'nvvidconv'`

Command output (baseline source plugin):

- `gst-inspect-1.0 v4l2src` -> available

Impact:

- Hardware decode/convert pipelines (`nvjpegdec ! nvvidconv`) fail in current container

### 3) Missing v4l2 utility in backend container

Command output:

- `v4l2-ctl_missing`

Impact:

- Startup mode probing and control tuning can’t use `v4l2-ctl` tools inside container

## NVIDIA Runtime Prerequisites Check (Host)

Host checks are healthy:

- `nvidia-container-runtime` installed
- `nvidia-docker2` installed
- `docker info` includes runtime `nvidia`
- `/etc/nvidia-container-runtime/host-files-for-container.d` exists with `l4t.csv`, `cuda.csv`, `cudnn.csv`, `tensorrt.csv`

Conclusion:

- Runtime is available; the blocker is mostly **container userspace composition** (OpenCV build + plugin set), not missing runtime registration.

## NVIDIA References Used

1. NVIDIA Container Runtime on Jetson (official)
   - [NVIDIA Container Runtime on Jetson](https://nvidia.github.io/container-wiki/toolkit/jetson.html)
   - Relevance: runtime install checks, supported devices, mount behavior from host

2. NVIDIA Container Toolkit Advanced Usage
   - [NVIDIA Container Toolkit Advanced Usage](https://nvidia.github.io/container-wiki/toolkit/advanced-usage.html)
   - Relevance: default runtime behavior and runtime/library mounting model

3. NVIDIA libnvidia-container mount plugin design (Jetson branch)
   - [mount_plugins.md (NVIDIA/libnvidia-container)](https://github.com/NVIDIA/libnvidia-container/blob/jetson/design/mount_plugins.md)
   - Relevance: host-files mount plugin mechanism (`/etc/nvidia-container-runtime/host-files-for-container.d/*.csv`)

4. Jetson Linux Developer Guide index (JP4.6/L4T R32.7.6 archive)
   - [Jetson Linux Developer Guide (R32.7.6 index)](https://docs.nvidia.com/jetson/archives/l4t-archived/l4t-3276/index.html)
   - Relevance: canonical location for Accelerated GStreamer / Multimedia / HW accel docs

> Note: direct scrape of some NVIDIA docs pages returned cookie-gate content in this environment, but canonical URLs are listed above.

## Safe Remediation Plan (No disruption to current running app)

### Phase A (shadow image validation, no cutover)

1. Build a **new backend test image tag** only (do not replace running service).
2. Add multimedia plugin packages expected to provide NVIDIA GStreamer elements for JP4.6 (from L4T repos).
3. Validate in disposable container:
   - `gst-inspect-1.0 nvvidconv`
   - `gst-inspect-1.0 nvjpegdec`
   - Python OpenCV build info contains GStreamer support.

### Phase B (controlled switch)

1. Keep current stack running.
2. Start canary backend on alternate port (e.g., 18000) with same `/dev` bindings.
3. Probe `/api/camera/info` and stream startup latency.
4. If pass, schedule brief maintenance cutover.

### Phase C (rollback guarantee)

- Preserve current image digest and compose file
- One-command rollback to known-good tag

## Recommended Immediate Action

Proceed with **Phase A only** next: build/test a shadow backend image for JP4.6 acceleration readiness while keeping production traffic on current containers.

## High-confidence Fix Path (still safe rollout)

1. Ensure Compose launch uses NVIDIA runtime for backend container (or set Docker default runtime to `nvidia` per NVIDIA docs).
2. Validate in canary service/container first (`backend-canary` on alternate port), then cut over.
3. Keep rollback command ready to return immediately to current known-good service.

## Canary Attempt Log (performed)

- Canary container was started on port `18000` with `--runtime nvidia`.
- During this run, backend logs showed camera open failures due to shared device contention, including `Unable to stop the stream: Device or resource busy` and `VIDEOIO ERROR: V4L2: Pixel format of incoming image is unsupported by OpenCV`.
- This occurred because production backend was already actively using `/dev/video0` and `/dev/video1`.

Immediate safety action:

- Canary container was removed right away.
- Production service was rechecked and remained healthy with both camera frame counters increasing.

Operational guidance:

- For future canary with camera open tests, run in a maintenance window or isolate to one camera device at a time.
- For capability-only validation, keep using throwaway `--runtime nvidia` containers **without** binding active camera devices.

## Zero-downtime capability probe (confirmed)

Executed a throwaway container with `--runtime nvidia` and **no camera device binding** while production remained online.

Results:

- `gst-inspect-1.0 nvvidconv` => `OK`
- `gst-inspect-1.0 nvjpegdec` => `OK`

Conclusion:

- NVIDIA GStreamer plugins are available when runtime is `nvidia`.
- This validates the non-disruptive check path and avoids camera contention with the active production service.

## Strict Trials Implemented and Executed

Code-level hardening added:

- `CAMERA_ENABLED_IDS` supports explicit camera enable list (for single-camera trial mode).
- `CAMERA_STRICT_CAMERA_IDS` enforces strict request validation for disabled camera IDs.
- `CAMERA_REQUIRE_HARDWARE_ACCEL` enforces a strict hardware-only camera startup policy.
- Runtime diagnostics now include hardware eligibility fields: `opencv_gstreamer_enabled`, `nvjpegdec_available`, `nvvidconv_available`, and `hardware_pipeline_eligible`.

### Strict trial A: camera ID enforcement (single-camera)

With `CAMERA_ENABLED_IDS=cam1` and strict ID policy enabled:

- `GET /api/camera/info?camera_id=cam2` returns `404` with:
- `GET /api/camera/info?camera_id=cam2` returns `404` with `error: camera_not_enabled`, `requested_camera_id: cam2`, and `enabled_camera_ids: ["cam1"]`.

Result: strict single-camera behavior is deterministic and explicit.

### Strict trial B: hardware-required canary

Canary launched on `:18000` using `--runtime nvidia` and:

- `CAMERA_ACCELERATION=hardware`
- `CAMERA_REQUIRE_HARDWARE_ACCEL=true`

Observed diagnostics:

- `nvjpegdec_available=true`
- `nvvidconv_available=true`
- `opencv_gstreamer_enabled=false`
- `hardware_pipeline_eligible=false`

Observed API behavior:

- `GET /api/camera/info?camera_id=cam1&create_if_missing=true` => camera stays closed with explicit last error
- `GET /api/camera/frame?camera_id=cam1` => `503 Service Unavailable`

Result: strict hardware gate works as designed and avoids silent fallback.

### Compose runtime compatibility note

Attempted to set `runtime: nvidia` in `docker-compose.yml`, but target `docker-compose` rejected it as unsupported (`Unsupported config option ... 'runtime'`).

Action taken:

- Reverted `runtime` key in compose to keep deployment stable.
- Continued NVIDIA-runtime validation using explicit canary `docker run --runtime nvidia` path.

## Next-step rollout hardening (completed)

To make strict single-camera trials operationally clean, frontend/backend camera discovery was hardened:

- Added backend endpoint: `GET /api/camera/enabled`
- Dashboard now renders camera panels dynamically from enabled-camera metadata.
- Device status camera polling now follows backend-reported camera IDs.
- Stream connect path performs a camera preflight and surfaces disabled-camera errors without retry storms.
- Dashboard defaults to `cam1` until enabled-camera metadata is loaded, preventing transient `cam2` polling on startup.

Validation evidence (live target):

- `GET /api/camera/enabled` => `{"enabled_camera_ids":["cam1"], ...}`
- Browser snapshot after refresh showed only `Camera 1 (Main)` tile.
- Backend request logs over the verification window showed repeated `cam1` info requests and no `cam2` info polling.

Result:

- Strict single-camera mode is now both **enforced** and **quiet** (no disabled-camera poll noise).

# Software Architecture and Application Flow (v1.0.0)

This document provides branch-aligned architecture diagrams for the Jetson Nano WebRTC Dashboard.

---

## 1) System / Deployment Architecture

```mermaid
flowchart LR
  subgraph LAN[Local Network]
    U[Operator Browser\nReact UI in Nginx]
    J[Jetson Nano Host]
  end

  subgraph J[Jetson Nano Host]
    F[Frontend Container\njetson-nano-frontend\nPort 80]
    B[Backend Container\njetson-nano-backend\nPort 8000]
    P[Docker-Prune Service\nOptional housekeeping]
    C1[Camera 1 /dev/video0 or fallback]
    C2[Camera 2 /dev/video1]
    G[GPIO Devices\nLED/Relay/Switch]
  end

  U -->|HTTP /| F
  U -->|HTTP /api via Nginx proxy| F
  F -->|Proxy /api and /ws| B

  B -->|Capture + diagnostics| C1
  B -->|Capture + diagnostics| C2
  B -->|GPIO control| G

  U <-->|WebSocket events| B
  U <-->|WebRTC / H264 / MJPEG fallback| B

  P -.->|Prune dangling image/cache| J
```

---

## 2) Software Architecture (Component View)

```mermaid
flowchart TB
  subgraph Frontend[Frontend - React]
    APP[App.jsx]
    VS[VideoStream.jsx\nFallback state machine]
    GC[GPIOControls.jsx]
    DS[DeviceStatus.jsx]
    API[services/api.js]
    WRTC[services/webrtc.js]
    EV[services/eventLogger.js]
  end

  subgraph Backend[Backend - FastAPI]
    MAIN[main.py\nREST + WS routes]
    CAM[camera.py\nCapture / stream engine]
    CFG[config.py\nEnv-driven runtime config]
    GPIO[gpio_control.py]
    WS[websocket.py]
    WEBRTC[webrtc.py]
    LOG[event_logger.py]
    SENSOR[sensor_data.py]
  end

  APP --> VS
  APP --> GC
  APP --> DS

  VS --> API
  VS --> WRTC
  GC --> API
  DS --> API

  API --> MAIN
  WRTC --> MAIN
  EV --> MAIN

  MAIN --> CAM
  MAIN --> GPIO
  MAIN --> WS
  MAIN --> WEBRTC
  MAIN --> SENSOR
  MAIN --> LOG
  MAIN --> CFG

  CAM --> CFG
  GPIO --> CFG
  WEBRTC --> CFG
```

---

## 3) Application Flow (Live Stream + Fallback + Recovery)

```mermaid
sequenceDiagram
  autonumber
  participant User as Operator
  participant UI as Frontend UI
  participant API as FastAPI Backend
  participant Cam as Camera Runtime

  User->>UI: Open dashboard + Start Stream
  UI->>API: GET /api/camera/info?camera_id=cam1
  API->>Cam: Ensure camera runtime exists
  Cam-->>API: Camera status + stream hints
  API-->>UI: Camera info + capabilities

  UI->>API: Try H264 stream endpoint
  alt H264 path succeeds
    API-->>UI: H264 bytes/stream frames
    UI-->>User: Live video (H264)
  else H264 fails
    UI->>API: POST /api/webrtc/offer
    alt WebRTC succeeds
      API-->>UI: SDP answer + media path
      UI-->>User: Live video (WebRTC)
    else WebRTC unavailable/fails
      UI->>API: GET /api/camera/stream
      API-->>UI: MJPEG multipart stream
      UI-->>User: Live video (MJPEG fallback)
    end
  end

  par Background telemetry
    UI->>API: GET /api/stats (poll)
    API-->>UI: perf, viewer, stream state
  and Recovery signals
    UI->>API: WS /ws subscribe
    API-->>UI: health + recovery events
  end

  opt Manual intervention
    User->>UI: Click Reset Camera
    UI->>API: POST /api/camera/recover
    API->>Cam: Reinitialize active camera path
    Cam-->>API: Recovered / degraded status
    API-->>UI: Recovery result
  end
```

---

## 4) Optional future extension (recording/storage path)

The approved design direction for production video storage is documented separately in:

- `Doc/production-video-storage-blueprint-v1.0.0.md`

That extension adds segmented recording, upload queue, metadata index, and lifecycle governance without blocking current live streaming behavior.

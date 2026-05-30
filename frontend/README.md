# Jetson Nano Dashboard Frontend

React-based web dashboard for real-time video streaming and GPIO control on Jetson Nano devices.

## Overview

This frontend is built with React + Vite and provides a simple dashboard for:

- real-time camera streaming via WebRTC
- GPIO LED control
- device health/status monitoring
- backend API integration with FastAPI

The UI is split into three primary sections:

1. Live Camera Feed
2. GPIO Controls
3. Device Status

## Folder Structure

```text
frontend/
  Dockerfile
  README.md
  index.html
  nginx.conf
  package.json
  vite.config.js
  src/
    App.css
    App.jsx
    main.jsx
    components/
      DeviceStatus.css
      DeviceStatus.jsx
      GPIOControls.css
      GPIOControls.jsx
      VideoStream.css
      VideoStream.jsx
    services/
      api.js
      webrtc.js
```

## Setup

### Prerequisites

- Node.js 18+ / npm
- Backend running at `http://localhost:8000` for local development

### Install dependencies

```bash
cd frontend
npm install
```

### Run in development

```bash
npm run dev
```

Open the app at `http://localhost:5173`.

### Build for production

```bash
npm run build
```

The build output is generated in `dist/`.

### Preview production build

```bash
npm run preview
```

## Scripts

- `npm run dev` — start Vite development server
- `npm run build` — build production assets
- `npm run preview` — preview production build locally
- `npm run lint` — run ESLint on JS/JSX files

## Key Files and Responsibilities

### `package.json`

Defines project metadata, dependencies, and npm scripts.

### `vite.config.js`

Vite configuration for serving the React app. It may include build settings and proxy configuration for API calls.

### `index.html`

Root HTML file containing the app mount target and the React script entry point.

### `src/main.jsx`

App bootstrap file.

- Imports React and ReactDOM
- Renders `App` into the DOM
- Loads global CSS

### `src/App.jsx`

Main page layout.

- Defines the dashboard structure
- Renders `VideoStream`, `GPIOControls`, and `DeviceStatus`
- Contains header and footer markup

### `src/App.css`

Global styling for the dashboard layout, spacing, typography, and responsive page design.

## Services

### `src/services/api.js`

Axios-based API client.

- Creates a base Axios instance
- Uses `http://localhost:8000/api` in development
- Defines grouped endpoint helpers:
  - `cameraAPI` for camera-related endpoints
  - `gpioAPI` for GPIO control
  - `systemAPI` for device status
  - `webrtcAPI` for WebRTC offer exchange

### `src/services/webrtc.js`

WebRTC helper class.

- Manages `RTCPeerConnection`
- Handles offer creation and answer exchange
- Sets incoming media stream on a video element
- Provides connect/disconnect methods and state callbacks

> Note: the current `VideoStream.jsx` component uses its own local WebRTC implementation rather than importing this helper.

## Components

### `src/components/VideoStream.jsx`

Live video component.

- Creates a WebRTC peer connection
- Sends an SDP offer to backend endpoint `/api/webrtc/offer`
- Receives backend SDP answer and sets remote description
- Displays remote stream in a `<video>` element
- Shows connect/disconnect buttons
- Displays connection state and errors

### `src/components/GPIOControls.jsx`

GPIO control component.

- Fetches LED state from backend on mount
- Displays current LED ON/OFF status
- Calls backend endpoints:
  - `/api/gpio/status`
  - `/api/gpio/on`
  - `/api/gpio/off`
  - `/api/gpio/toggle`
- Updates UI after each action
- Handles loading state and errors

### `src/components/DeviceStatus.jsx`

Device status dashboard.

- Polls backend every 5 seconds using `/api/system/status`
- Displays status cards for:
  - camera activity
  - CUDA availability
  - GPIO availability and LED state
  - WebSocket connection count
- Shows last update timestamp
- Handles loading and error states

### Component styles

- `src/components/VideoStream.css` — styles for video container, buttons, and connection status
- `src/components/GPIOControls.css` — layout and button styling for GPIO controls
- `src/components/DeviceStatus.css` — cards and status grid styling

## Backend Integration

The frontend communicates with the FastAPI backend through these endpoints:

- `GET /api/gpio/status` — current GPIO status
- `POST /api/gpio/on` — turn LED on
- `POST /api/gpio/off` — turn LED off
- `POST /api/gpio/toggle` — toggle LED state
- `GET /api/system/status` — device status payload
- `POST /api/webrtc/offer` — exchange WebRTC offer/answer

## Testing checklist

1. Start backend service on `localhost:8000`
2. Start frontend with `npm run dev`
3. Visit `http://localhost:5173`
4. In the dashboard:
   - click `Start Stream` and verify video appears
   - verify LED status loads
   - use `LED ON`, `LED OFF`, and `TOGGLE`
   - confirm device status cards update every 5 seconds
5. Check browser console for WebRTC or network errors

## Notes

- The frontend is designed for local development with the API server on `localhost:8000`.
- If you deploy behind a reverse proxy, ensure API requests are forwarded to `/api`.
- The WebRTC component requires the backend to provide a valid SDP answer and media stream.

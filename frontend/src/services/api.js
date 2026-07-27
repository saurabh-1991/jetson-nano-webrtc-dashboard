import axios from 'axios'

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  : ''

export const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 5000,
})

const logEvent = (type, message, severity = 'info', meta = {}) => {
  try {
    if (typeof window !== 'undefined' && typeof window.__jetsonLogEvent === 'function') {
      window.__jetsonLogEvent(type, message, severity, meta)
    }
  } catch (_e) {
    // no-op
  }
}

api.interceptors.request.use(
  (config) => {
    config.metadata = { startedAt: Date.now() }
    return config
  },
  (error) => {
    logEvent('api_request_error', error?.message || 'request setup failed', 'error')
    return Promise.reject(error)
  }
)

api.interceptors.response.use(
  (response) => {
    const startedAt = response?.config?.metadata?.startedAt || Date.now()
    const durationMs = Date.now() - startedAt
    logEvent('api_response', `${response?.config?.method || 'get'} ${response?.config?.url || ''}`, 'info', {
      status: response?.status,
      durationMs,
    })
    return response
  },
  (error) => {
    const startedAt = error?.config?.metadata?.startedAt || Date.now()
    const durationMs = Date.now() - startedAt
    logEvent('api_response_error', error?.message || 'api error', 'error', {
      status: error?.response?.status,
      url: error?.config?.url,
      method: error?.config?.method,
      durationMs,
    })
    return Promise.reject(error)
  }
)

// Camera endpoints
export const cameraAPI = {
  getInfo: (cameraId = 'cam1') => api.get(`/camera/info?camera_id=${encodeURIComponent(cameraId)}`),
  getFrame: (cameraId = 'cam1') => api.get(`/camera/frame?camera_id=${encodeURIComponent(cameraId)}`),
  getStream: (cameraId = 'cam1') => `${API_BASE}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}`,
  recover: (reason = 'manual_operator_recover', cameraId = 'cam1') =>
    api.post('/camera/recover', { reason, camera_id: cameraId }),
}

// GPIO endpoints
export const gpioAPI = {
  getStatus: () => api.get('/gpio/status'),
  getOutputs: () => api.get('/gpio/outputs'),
  turnOutputOn: (outputName) => api.post(`/gpio/outputs/${outputName}/on`),
  turnOutputOff: (outputName) => api.post(`/gpio/outputs/${outputName}/off`),
  toggleOutput: (outputName) => api.post(`/gpio/outputs/${outputName}/toggle`),

  // Legacy compatibility helpers (mapped to exhaust blower in backend)
  turnOn: () => api.post('/gpio/on'),
  turnOff: () => api.post('/gpio/off'),
  toggle: () => api.post('/gpio/toggle'),
}

// System endpoints
export const systemAPI = {
  getInfo: () => api.get('/system/info'),
  getStatus: () => api.get('/system/status'),
  getStats: () => api.get('/stats'),
}

// Sensor data endpoints
export const sensorAPI = {
  getLatest: () => api.get('/sensors/latest'),
  getHistory: ({ limit = 120, intervalMinutes = 1, hours = 24 } = {}) =>
    api.get(`/sensors/history?limit=${limit}&interval_minutes=${intervalMinutes}&hours=${hours}`),
  getSimulationMode: () => api.get('/sensors/simulation'),
  setSimulationMode: (enabled) => api.post('/sensors/simulation', { enabled }),
}

// Diagnostics / event logs endpoints
export const eventsAPI = {
  getRecent: () => api.get('/events/recent'),
}

// WebRTC endpoints
export const webrtcAPI = {
  sendOffer: (offer) => api.post('/webrtc/offer', offer),
}

export default api

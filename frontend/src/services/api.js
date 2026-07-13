import axios from 'axios'

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  : ''

export const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 5000,
})

// Camera endpoints
export const cameraAPI = {
  getInfo: () => api.get('/camera/info'),
  getFrame: () => api.get('/camera/frame'),
  getStream: () => `${API_BASE}/api/camera/stream`,
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
}

// WebRTC endpoints
export const webrtcAPI = {
  sendOffer: (offer) => api.post('/webrtc/offer', offer),
}

export default api

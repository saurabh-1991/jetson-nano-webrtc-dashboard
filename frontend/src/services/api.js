import axios from 'axios'

const API_BASE = process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : ''

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

// WebRTC endpoints
export const webrtcAPI = {
  sendOffer: (offer) => api.post('/webrtc/offer', offer),
}

export default api

import axios from 'axios'

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  : ''

export const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 5000,
})

const errorThrottleMap = new Map()
const ERROR_THROTTLE_MS = 15000

const shouldThrottleErrorLog = (key) => {
  const now = Date.now()
  const lastAt = errorThrottleMap.get(key)
  if (typeof lastAt === 'number' && (now - lastAt) < ERROR_THROTTLE_MS) {
    return true
  }
  errorThrottleMap.set(key, now)
  return false
}

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
    const errorCode = String(error?.code || '').toUpperCase()
    const rawMessage = String(error?.message || '')
    const message = rawMessage.toLowerCase()
    const url = error?.config?.url || ''
    const method = error?.config?.method
    const startedAt = error?.config?.metadata?.startedAt || Date.now()
    const durationMs = Date.now() - startedAt

    // Common harmless noise while network path flips or requests are canceled.
    if (errorCode === 'ERR_CANCELED' || message.includes('canceled')) {
      return Promise.reject(error)
    }

    const isNetworkChanged = errorCode === 'ERR_NETWORK_CHANGED' || message.includes('network changed')
    const isSensorPoll = url.includes('/sensors/latest') || url.includes('/sensors/history')
    const throttleKey = `${method || 'get'}|${url}|${errorCode || message}`

    if (!(isSensorPoll || isNetworkChanged) || !shouldThrottleErrorLog(throttleKey)) {
      logEvent('api_response_error', error?.message || 'api error', isNetworkChanged ? 'warning' : 'error', {
        status: error?.response?.status,
        url,
        method,
        durationMs,
        code: errorCode || undefined,
      })
    }

    return Promise.reject(error)
  }
)

// Camera endpoints
export const cameraAPI = {
  getInfo: (cameraId = 'cam1', requestConfig = {}) =>
    api.get(`/camera/info?camera_id=${encodeURIComponent(cameraId)}`, requestConfig),
  getEnabled: () => api.get('/camera/enabled'),
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

// Experiment run endpoints
export const experimentsAPI = {
  getStorage: (requestConfig = {}) => api.get('/experiments/storage', requestConfig),
  getStorageHealth: (requestConfig = {}) => api.get('/experiments/storage/health', requestConfig),
  runStorageCleanup: (payload = {}) => api.post('/experiments/storage/cleanup', payload),
  deleteRun: (runId) => api.delete(`/experiments/${encodeURIComponent(runId)}`),
  getActive: (requestConfig = {}) => api.get('/experiments/active', requestConfig),
  getHistory: (limit = 20, requestConfig = {}) => api.get(`/experiments/history?limit=${limit}`, requestConfig),
  start: (payload = {}) => api.post('/experiments/start', payload),
  stop: (payload = {}) => api.post('/experiments/stop', payload),
  getArtifacts: (runId) => api.get(`/experiments/${encodeURIComponent(runId)}/artifacts`),
  getDownloadUrl: (runId) => `${API_BASE}/api/experiments/${encodeURIComponent(runId)}/download`,
  getMediaUrl: (runId, relativePath) => `${API_BASE}/api/experiments/${encodeURIComponent(runId)}/media?path=${encodeURIComponent(relativePath)}`,
  getPlayableMediaUrl: (runId, relativePath) => `${API_BASE}/api/experiments/${encodeURIComponent(runId)}/media-playable?path=${encodeURIComponent(relativePath)}`,
}

// WebRTC endpoints
export const webrtcAPI = {
  sendOffer: (offer) => api.post('/webrtc/offer', offer),
}

export default api

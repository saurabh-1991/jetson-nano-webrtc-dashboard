import axios from 'axios'

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  : ''

export const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 5000,
})

const errorThrottleMap = new Map()
const ERROR_THROTTLE_MS = 30000
const API_COOLDOWN_BASE_MS = 12000
const API_COOLDOWN_MAX_MS = 60000

let timeoutBurstCount = 0
let apiCooldownUntilTs = 0

const getApiCooldownRemainingMs = () => Math.max(0, apiCooldownUntilTs - Date.now())

export const isApiCoolingDown = () => getApiCooldownRemainingMs() > 0

export const getApiCooldownState = () => ({
  active: isApiCoolingDown(),
  remainingMs: getApiCooldownRemainingMs(),
  burstCount: timeoutBurstCount,
})

const classifyTransientNetworkError = (error) => {
  const errorCode = String(error?.code || '').toUpperCase()
  const message = String(error?.message || '').toLowerCase()

  const isTimeout = errorCode === 'ECONNABORTED' || message.includes('timeout')
  const isNetwork = errorCode === 'ERR_NETWORK' || message.includes('network error')
  const isConnection = message.includes('failed to fetch') || message.includes('err_connection')
  const isAbort = errorCode === 'ERR_CANCELED' || message.includes('canceled')

  return {
    isTimeout,
    isNetwork,
    isConnection,
    isAbort,
    isTransient: isTimeout || isNetwork || isConnection,
    errorCode,
    message,
  }
}

const markTransientFailureForCooldown = () => {
  timeoutBurstCount += 1
  const cooldownStep = Math.max(0, timeoutBurstCount - 3)
  const cooldownMs = Math.min(API_COOLDOWN_MAX_MS, API_COOLDOWN_BASE_MS * (2 ** cooldownStep))
  if (timeoutBurstCount >= 3) {
    apiCooldownUntilTs = Math.max(apiCooldownUntilTs, Date.now() + cooldownMs)
  }
}

const markApiSuccess = () => {
  timeoutBurstCount = Math.max(0, timeoutBurstCount - 1)
  if (timeoutBurstCount === 0) {
    apiCooldownUntilTs = 0
  }
}

const shouldThrottleErrorLog = (key) => {
  const now = Date.now()
  const lastAt = errorThrottleMap.get(key)
  if (typeof lastAt === 'number' && (now - lastAt) < ERROR_THROTTLE_MS) {
    return true
  }
  errorThrottleMap.set(key, now)
  return false
}

export const shouldThrottleClientNoise = (key) => shouldThrottleErrorLog(`client|${String(key || '')}`)

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
    markApiSuccess()

    const startedAt = response?.config?.metadata?.startedAt || Date.now()
    const durationMs = Date.now() - startedAt
    logEvent('api_response', `${response?.config?.method || 'get'} ${response?.config?.url || ''}`, 'info', {
      status: response?.status,
      durationMs,
    })
    return response
  },
  (error) => {
    const {
      isTransient,
      isAbort,
      errorCode,
      message,
    } = classifyTransientNetworkError(error)
    const rawMessage = String(error?.message || '')
    const url = error?.config?.url || ''
    const method = error?.config?.method
    const startedAt = error?.config?.metadata?.startedAt || Date.now()
    const durationMs = Date.now() - startedAt

    // Common harmless noise while network path flips or requests are canceled.
    if (isAbort) {
      return Promise.reject(error)
    }

    if (isTransient) {
      markTransientFailureForCooldown()
    }

    const isNetworkChanged = errorCode === 'ERR_NETWORK_CHANGED' || message.includes('network changed')
    const isSensorPoll = url.includes('/sensors/latest') || url.includes('/sensors/history')
    const throttleKey = `${method || 'get'}|${url}|${errorCode || message}`

    const shouldSuppress = isTransient && shouldThrottleErrorLog(throttleKey)
    if (!shouldSuppress) {
      logEvent('api_response_error', error?.message || 'api error', isNetworkChanged ? 'warning' : 'error', {
        status: error?.response?.status,
        url,
        method,
        durationMs,
        code: errorCode || undefined,
        cooldownActive: isApiCoolingDown(),
        cooldownRemainingMs: getApiCooldownRemainingMs(),
        noisyEndpoint: isSensorPoll,
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
  getH264Stream: (cameraId = 'cam1') => `${API_BASE}/api/camera/stream_h264?camera_id=${encodeURIComponent(cameraId)}`,
  prewarm: (cameraIds = ['cam1', 'cam2'], requestConfig = {}) =>
    api.post('/camera/prewarm', { camera_ids: cameraIds }, requestConfig),
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

// VFD endpoints
export const vfdAPI = {
  getStatus: () => api.get('/vfd/status'),
  setRun: (run) => api.post('/vfd/run', { run: !!run }),
  setSpeed: (speedHz) => api.post('/vfd/speed', { speed_hz: speedHz }),
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

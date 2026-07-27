const RETENTION_MS = 2 * 60 * 1000
const MAX_QUEUE = 400
const FLUSH_INTERVAL_MS = 5000
const HEARTBEAT_INTERVAL_MS = 5000
const DUPLICATE_WINDOW_MS = 15000

const queue = []
let flushTimer = null
let heartbeatTimer = null
const duplicateTracker = new Map()

const sessionId = (typeof crypto !== 'undefined' && crypto.randomUUID)
  ? crypto.randomUUID()
  : `fe-${Date.now()}-${Math.random().toString(36).slice(2)}`

const getApiBase = () => {
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
  }
  return ''
}

const pruneQueue = () => {
  const cutoff = Date.now() - RETENTION_MS
  while (queue.length > 0 && Number(queue[0].atTs || 0) < cutoff) {
    queue.shift()
  }

  if (queue.length > MAX_QUEUE) {
    queue.splice(0, queue.length - MAX_QUEUE)
  }
}

const enqueue = (event) => {
  queue.push(event)
  pruneQueue()
}

const buildDuplicateKey = (event) => {
  const metaUrl = event?.meta?.url || event?.meta?.path || ''
  return `${event?.type || ''}|${event?.severity || ''}|${event?.message || ''}|${metaUrl}`
}

const shouldSkipDuplicate = (event) => {
  const now = Date.now()
  const key = buildDuplicateKey(event)
  const lastTs = duplicateTracker.get(key)

  if (typeof lastTs === 'number' && (now - lastTs) < DUPLICATE_WINDOW_MS) {
    return true
  }

  duplicateTracker.set(key, now)
  if (duplicateTracker.size > 1000) {
    const staleCutoff = now - (DUPLICATE_WINDOW_MS * 2)
    for (const [k, ts] of duplicateTracker.entries()) {
      if (ts < staleCutoff) {
        duplicateTracker.delete(k)
      }
    }
  }
  return false
}

const safeLogToConsole = (event) => {
  try {
    if (event.severity === 'error') {
      console.error('[event]', event.type, event.message || '', event.meta || {})
    } else if (event.severity === 'warning') {
      console.warn('[event]', event.type, event.message || '', event.meta || {})
    }
  } catch (_e) {
    // no-op
  }
}

export const logFrontendEvent = (type, message = '', severity = 'info', meta = {}) => {
  const event = {
    type,
    message,
    severity,
    meta,
    at: new Date().toISOString(),
    atTs: Date.now(),
  }

  if (shouldSkipDuplicate(event)) {
    return
  }

  enqueue(event)
  safeLogToConsole(event)
}

const flushEvents = async () => {
  pruneQueue()
  if (queue.length === 0) {
    return
  }

  const eventsToSend = queue.splice(0, queue.length).map((e) => ({
    type: e.type,
    message: e.message,
    severity: e.severity,
    meta: e.meta,
    at: e.at,
  }))

  try {
    await fetch(`${getApiBase()}/api/events/frontend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        events: eventsToSend,
      }),
      keepalive: true,
    })
  } catch (_err) {
    // Re-queue on failure (bounded by retention and max queue)
    const requeued = eventsToSend.map((e) => ({ ...e, atTs: Date.now() }))
    requeued.forEach(enqueue)
  }
}

const sendHeartbeat = async () => {
  try {
    await fetch(`${getApiBase()}/api/safety/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        connection_state: navigator.onLine ? 'online' : 'offline',
      }),
      keepalive: true,
    })
  } catch (_e) {
    // no-op
  }
}

const bindBrowserErrorHooks = () => {
  window.addEventListener('error', (event) => {
    logFrontendEvent(
      'window_error',
      event?.message || 'window error',
      'error',
      {
        filename: event?.filename,
        lineno: event?.lineno,
        colno: event?.colno,
      }
    )
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event?.reason
    logFrontendEvent(
      'unhandled_promise_rejection',
      typeof reason === 'string' ? reason : 'unhandled promise rejection',
      'error',
      {
        reason: typeof reason === 'object' ? String(reason) : reason,
      }
    )
  })

  document.addEventListener('visibilitychange', () => {
    logFrontendEvent('visibility_change', document.visibilityState, 'info')
  })
}

export const initializeEventLogger = () => {
  if (typeof window === 'undefined') {
    return
  }

  if (window.__jetsonEventLoggerInitialized) {
    return
  }
  window.__jetsonEventLoggerInitialized = true

  window.__jetsonLogEvent = (type, message = '', severity = 'info', meta = {}) => {
    logFrontendEvent(type, message, severity, meta)
  }

  bindBrowserErrorHooks()
  logFrontendEvent('frontend_startup', 'Frontend event logger initialized', 'info', { sessionId })

  flushTimer = window.setInterval(() => {
    flushEvents()
  }, FLUSH_INTERVAL_MS)

  heartbeatTimer = window.setInterval(() => {
    sendHeartbeat()
  }, HEARTBEAT_INTERVAL_MS)

  // Send immediately on startup for faster watchdog arming.
  sendHeartbeat()

  window.addEventListener('beforeunload', () => {
    flushEvents()
  })
}

export const shutdownEventLogger = () => {
  if (flushTimer) {
    clearInterval(flushTimer)
    flushTimer = null
  }
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  flushEvents()
}

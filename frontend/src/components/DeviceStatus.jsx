import React, { useState, useEffect, useRef } from 'react'
import { cameraAPI, systemAPI } from '../services/api'
import { getApiCooldownState } from '../services/api'
import { shouldThrottleClientNoise } from '../services/api'
import './DeviceStatus.css'

const STATUS_BASE_MS = 7000
const STATUS_MAX_MS = 25000
const CAMERA_BASE_MS = 5000
const CAMERA_MAX_MS = 20000
const CAMERA_INFO_TIMEOUT_MIN_MS = 4500

function getBackoffDelay(baseMs, maxMs, failureCount) {
  const step = Math.max(0, Math.min(4, Number(failureCount || 0)))
  return Math.min(maxMs, baseMs * (2 ** step))
}

export const DeviceStatus = () => {
  const [status, setStatus] = useState(null)
  const [cameraIds, setCameraIds] = useState(['cam1'])
  const cameraIdsRef = useRef(['cam1'])
  const [cameras, setCameras] = useState({ cam1: null })
  const [cameraLastUpdatedAt, setCameraLastUpdatedAt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isRecoveringCamera, setIsRecoveringCamera] = useState({ cam1: false, cam2: false })
  const [recoverMessage, setRecoverMessage] = useState({ cam1: '', cam2: '' })
  const [error, setError] = useState(null)
  const [isCameraRefreshing, setIsCameraRefreshing] = useState(false)
  const [statusFailures, setStatusFailures] = useState(0)
  const [cameraFailures, setCameraFailures] = useState(0)
  const statusFailuresRef = useRef(0)
  const cameraFailuresRef = useRef(0)

  const fetchStatus = async () => {
    const cooldown = getApiCooldownState()
    if (cooldown.active) {
      return false
    }

    try {
      setIsRefreshing(true)
      const response = await systemAPI.getStatus()
      setStatus(response.data)
      const ids = Object.keys(response?.data?.cameras || {})
      if (ids.length > 0) {
        cameraIdsRef.current = ids
        setCameraIds(ids)
      }
      statusFailuresRef.current = 0
      setStatusFailures(0)
      setError(null)
      return true
    } catch (err) {
      if (!shouldThrottleClientNoise('device_status_fetch_failed')) {
        console.error('Failed to fetch device status:', err)
      }
      statusFailuresRef.current += 1
      setStatusFailures(statusFailuresRef.current)
      setError((prev) => {
        if (status) {
          // Keep stale status visible and rely on warning banner instead of hard error card.
          return null
        }
        return prev || 'Waiting for device status… network unstable, retrying.'
      })
      return false
    } finally {
      setIsRefreshing(false)
      setLoading(false)
    }
  }

  const fetchCameras = async () => {
    const cooldown = getApiCooldownState()
    if (cooldown.active) {
      return false
    }

    try {
      const ids = cameraIdsRef.current && cameraIdsRef.current.length > 0
        ? cameraIdsRef.current
        : ['cam1']
      const cameraInfoTimeoutMs = Math.max(
        CAMERA_INFO_TIMEOUT_MIN_MS,
        getBackoffDelay(CAMERA_BASE_MS, CAMERA_MAX_MS, cameraFailuresRef.current)
      )

      const responses = await Promise.allSettled(
        ids.map((id) => cameraAPI.getInfo(id, { timeout: cameraInfoTimeoutMs }))
      )

      setCameras((prev) => {
        const next = { ...prev }
        responses.forEach((result, index) => {
          const id = ids[index]
          if (result.status === 'fulfilled') {
            next[id] = result.value?.data || null
          }
        })
        return next
      })

      if (responses.some((result) => result.status === 'fulfilled')) {
        setCameraLastUpdatedAt(Date.now())
        cameraFailuresRef.current = 0
        setCameraFailures(0)
        return true
      }
      cameraFailuresRef.current += 1
      setCameraFailures(cameraFailuresRef.current)
      return false
    } catch (_err) {
      // Ignore - keep last known camera state to avoid UI flicker.
      cameraFailuresRef.current += 1
      setCameraFailures(cameraFailuresRef.current)
      return false
    }
  }

  useEffect(() => {
    let mounted = true
    let statusTimer = null
    let cameraTimer = null
    let statusInFlight = false
    let cameraInFlight = false

    const scheduleStatus = (delayMs = STATUS_BASE_MS) => {
      if (!mounted) return
      statusTimer = setTimeout(async () => {
        const cooldown = getApiCooldownState()
        if (cooldown.active) {
          scheduleStatus(Math.max(STATUS_BASE_MS, cooldown.remainingMs + 300))
          return
        }

        if (!statusInFlight) {
          statusInFlight = true
          const ok = await fetchStatus()
          statusInFlight = false
          const nextMs = ok
            ? STATUS_BASE_MS
            : getBackoffDelay(STATUS_BASE_MS, STATUS_MAX_MS, statusFailuresRef.current)
          scheduleStatus(nextMs)
          return
        }
        scheduleStatus(STATUS_BASE_MS)
      }, delayMs)
    }

    const scheduleCamera = (delayMs = CAMERA_BASE_MS) => {
      if (!mounted) return
      cameraTimer = setTimeout(async () => {
        const cooldown = getApiCooldownState()
        if (cooldown.active) {
          scheduleCamera(Math.max(CAMERA_BASE_MS, cooldown.remainingMs + 300))
          return
        }

        if (!cameraInFlight) {
          cameraInFlight = true
          setIsCameraRefreshing(true)
          const ok = await fetchCameras()
          setIsCameraRefreshing(false)
          cameraInFlight = false
          const nextMs = ok
            ? CAMERA_BASE_MS
            : getBackoffDelay(CAMERA_BASE_MS, CAMERA_MAX_MS, cameraFailuresRef.current)
          scheduleCamera(nextMs)
          return
        }
        scheduleCamera(CAMERA_BASE_MS)
      }, delayMs)
    }

    scheduleStatus(0)
    scheduleCamera(0)

    return () => {
      mounted = false
      if (statusTimer) clearTimeout(statusTimer)
      if (cameraTimer) clearTimeout(cameraTimer)
    }
  }, [])

  const handleManualRecoverCamera = async (cameraId) => {
    if (isRecoveringCamera?.[cameraId]) {
      return
    }

    const camera = cameras?.[cameraId]

    if (camera?.is_open) {
      const confirmed = window.confirm(
        'Camera appears active. Resetting it may briefly interrupt the live stream. Continue?'
      )
      if (!confirmed) {
        return
      }
    }

    try {
      setIsRecoveringCamera((prev) => ({ ...prev, [cameraId]: true }))
      setRecoverMessage((prev) => ({ ...prev, [cameraId]: 'Recovering camera...' }))
      const response = await cameraAPI.recover('manual_operator_button', cameraId)
      const ok = !!response?.data?.success
      setRecoverMessage((prev) => ({
        ...prev,
        [cameraId]: ok ? 'Camera recovery completed.' : 'Camera recovery attempted (still unavailable).',
      }))
      await Promise.all([fetchStatus(), fetchCameras()])
    } catch (recoverError) {
      if (!shouldThrottleClientNoise(`recover_camera_failed_${cameraId}`)) {
        console.error('Failed to recover camera:', recoverError)
      }
      setRecoverMessage((prev) => ({ ...prev, [cameraId]: 'Camera recovery request failed.' }))
    } finally {
      setIsRecoveringCamera((prev) => ({ ...prev, [cameraId]: false }))
      setTimeout(() => {
        setRecoverMessage((prev) => ({ ...prev, [cameraId]: '' }))
      }, 4500)
    }
  }

  if (loading && !status) {
    return <div className="device-status-container">Loading...</div>
  }

  if (!status) {
    return <div className="device-status-container error">{error}</div>
  }

  const getCameraLabel = (id) => {
    if (id === 'cam1') return 'Camera 1 (Main)'
    if (id === 'cam2') return 'Camera 2 (IR)'
    return `Camera ${id}`
  }

  const cameraEntries = cameraIds.map((id) => ({ id, label: getCameraLabel(id) }))

  const cameraStatusFresh = cameraLastUpdatedAt > 0 && (Date.now() - cameraLastUpdatedAt) <= 9000
  const hasDegradedSync = statusFailures >= 2 || cameraFailures >= 3

  return (
    <div className="device-status-container">
      <h2>Status / Indicator</h2>

      {hasDegradedSync && (
        <div className="status-warning-banner">
          Network jitter detected. Device status is using last known values while retrying.
        </div>
      )}

      <div className="status-grid">
        <div className="status-card">
          <div className="card-title">Cameras</div>
          <div className="camera-status-freshness-row">
            <span className={`refresh-indicator ${isRefreshing ? 'active' : ''}`}>
              {(isRefreshing || isCameraRefreshing) ? 'Refreshing…' : 'Auto-refresh'}
            </span>
            <span className={`health-badge ${cameraStatusFresh ? 'healthy' : 'warning'}`}>
              {cameraStatusFresh ? 'Live' : 'Delayed'}
            </span>
          </div>
          <div className="camera-cards-grid">
            {cameraEntries.map(({ id, label }) => {
              const camera = cameras?.[id] || {}
              const recovery = camera?.pipeline_diagnostics?.recovery || {}
              const recoveryFailures = Number(recovery?.failures || 0)
              const consecutiveRecoveryFailures = Number(recovery?.consecutive_failures || 0)
              const recoveryState = consecutiveRecoveryFailures > 0
                ? 'degraded'
                : recoveryFailures > 0
                  ? 'warning'
                  : 'healthy'

              const recoveryStateText = recoveryState === 'degraded'
                ? 'Degraded'
                : recoveryState === 'warning'
                  ? 'Recovered'
                  : 'Healthy'

              return (
                <div key={id} className="camera-subcard">
                  <div className="camera-subcard-title">{label}</div>
                  <div className="camera-primary-stats">
                    <span className={`camera-stat-chip ${camera?.is_open ? 'ok' : 'bad'}`}>
                      {camera?.is_open ? 'Active' : 'Inactive'}
                    </span>
                    <span className={`health-badge ${recoveryState}`}>{recoveryStateText}</span>
                    <span className="camera-stat-chip neutral">Frames: {Number(camera?.frame_count || 0)}</span>
                    <button
                      type="button"
                      className="camera-recover-btn"
                      onClick={() => handleManualRecoverCamera(id)}
                      disabled={!!isRecoveringCamera?.[id]}
                      title="Manual camera recovery if auto-recovery does not restore stream"
                    >
                      {isRecoveringCamera?.[id] ? 'Recovering…' : 'Reset'}
                    </button>
                  </div>

                  {recoverMessage?.[id] && (
                    <div className="camera-recover-feedback">{recoverMessage[id]}</div>
                  )}

                  <div className="camera-meta-line">
                    <span className="label">Active Device:</span>
                    <span className="value value-small">
                      {camera?.pipeline_diagnostics?.selected_pipeline_source || 'Not selected yet'}
                    </span>
                  </div>

                  <div className="camera-recovery-grid">
                    <div className="camera-recovery-item">
                      <span className="label">Attempts</span>
                      <span className="value">{Number(recovery?.attempts || 0)}</span>
                    </div>
                    <div className="camera-recovery-item">
                      <span className="label">Successes</span>
                      <span className="value">{Number(recovery?.successes || 0)}</span>
                    </div>
                    <div className="camera-recovery-item">
                      <span className="label">Failures</span>
                      <span className={`value ${recoveryFailures > 0 ? 'inactive' : 'active'}`}>{recoveryFailures}</span>
                    </div>
                  </div>

                  {recovery?.last_recovery_reason && (
                    <div className="camera-meta-line">
                      <span className="label">Last Recovery:</span>
                      <span className="value value-small">{recovery.last_recovery_reason}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Input Signal Indicators */}
        {status?.gpio?.inputs && (
          <div className="status-card">
            <div className="card-title">Input Signals</div>
            <div className="card-content">
              {Object.entries(status.gpio.inputs).map(([key, input]) => {
                const signalOn = !!input?.signal
                const pin = input?.pin
                const rawLevel = input?.raw_gpio_level
                return (
                  <div className="status-item" key={key}>
                    <div className="input-meta">
                      <div className="input-title">{input?.label || key}</div>
                      <div className="input-subtitle">
                        {typeof pin === 'number'
                          ? `BOARD Pin ${pin}${rawLevel ? ` · Raw ${rawLevel}` : ''}`
                          : 'Pin not configured'}
                      </div>
                    </div>
                    <span className="indicator-wrap">
                      <span
                        className={`input-led ${signalOn ? 'on' : 'off'}`}
                        aria-label={`${input?.label || key} ${signalOn ? 'active' : 'inactive'}`}
                      ></span>
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

    </div>
  )
}

export default DeviceStatus

import React, { useState, useEffect } from 'react'
import { cameraAPI, systemAPI } from '../services/api'
import './DeviceStatus.css'

export const DeviceStatus = () => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isRecoveringCamera, setIsRecoveringCamera] = useState(false)
  const [recoverMessage, setRecoverMessage] = useState('')
  const [error, setError] = useState(null)

  const fetchStatus = async () => {
    try {
      setIsRefreshing(true)
      const response = await systemAPI.getStatus()
      setStatus(response.data)
      setError(null)
    } catch (err) {
      console.error('Failed to fetch device status:', err)
      setError('Failed to load device status')
    } finally {
      setIsRefreshing(false)
      setLoading(false)
    }
  }

  useEffect(() => {
    // Fetch immediately and then every 5 seconds
    fetchStatus()
    const interval = setInterval(fetchStatus, 5000)

    return () => clearInterval(interval)
  }, [])

  const handleManualRecoverCamera = async () => {
    if (isRecoveringCamera) {
      return
    }

    if (camera?.is_open) {
      const confirmed = window.confirm(
        'Camera appears active. Resetting it may briefly interrupt the live stream. Continue?'
      )
      if (!confirmed) {
        return
      }
    }

    try {
      setIsRecoveringCamera(true)
      setRecoverMessage('Recovering camera...')
      const response = await cameraAPI.recover('manual_operator_button')
      const ok = !!response?.data?.success
      setRecoverMessage(ok ? 'Camera recovery completed.' : 'Camera recovery attempted (still unavailable).')
      await fetchStatus()
    } catch (recoverError) {
      console.error('Failed to recover camera:', recoverError)
      setRecoverMessage('Camera recovery request failed.')
    } finally {
      setIsRecoveringCamera(false)
      setTimeout(() => {
        setRecoverMessage('')
      }, 4500)
    }
  }

  if (loading) {
    return <div className="device-status-container">Loading...</div>
  }

  if (error) {
    return <div className="device-status-container error">{error}</div>
  }

  const camera = status?.camera || {}
  const recovery = camera?.recovery || {}
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
    <div className="device-status-container">
      <h2>Status / Indicator</h2>

      <div className="status-grid">
        {/* Camera Status */}
        {status?.camera && (
          <div className="status-card">
            <div className="card-title">Camera</div>
            <div className="card-content">
              <div className="camera-primary-stats">
                <span className={`camera-stat-chip ${status.camera.is_open ? 'ok' : 'bad'}`}>
                  {status.camera.is_open ? 'Active' : 'Inactive'}
                </span>
                <span className={`health-badge ${recoveryState}`}>{recoveryStateText}</span>
                <span className="camera-stat-chip neutral">Frames: {status.camera.frame_count}</span>
                <button
                  type="button"
                  className="camera-recover-btn"
                  onClick={handleManualRecoverCamera}
                  disabled={isRecoveringCamera}
                  title="Manual camera recovery if auto-recovery does not restore stream"
                >
                  {isRecoveringCamera ? 'Recovering…' : 'Reset Camera'}
                </button>
              </div>

              {recoverMessage && (
                <div className="camera-recover-feedback">{recoverMessage}</div>
              )}

              <div className="camera-meta-line">
                <span className="label">Active Device:</span>
                <span className="value value-small">{camera?.selected_source || 'Not selected yet'}</span>
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
          </div>
        )}

        {/* Input Signal Indicators */}
        {status?.gpio?.inputs && (
          <div className="status-card">
            <div className="card-title">Input Signals</div>
            <div className="card-content">
              {Object.entries(status.gpio.inputs).map(([key, input]) => {
                const signalOn = !!input?.signal
                const pin = input?.pin
                return (
                  <div className="status-item" key={key}>
                    <div className="input-meta">
                      <div className="input-title">{input?.label || key}</div>
                      <div className="input-subtitle">
                        {typeof pin === 'number' ? `BOARD Pin ${pin}` : 'Pin not configured'}
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

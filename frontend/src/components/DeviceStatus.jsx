import React, { useState, useEffect } from 'react'
import { systemAPI } from '../services/api'
import './DeviceStatus.css'

export const DeviceStatus = () => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
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

    // Fetch immediately and then every 5 seconds
    fetchStatus()
    const interval = setInterval(fetchStatus, 5000)

    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return <div className="device-status-container">Loading...</div>
  }

  if (error) {
    return <div className="device-status-container error">{error}</div>
  }

  return (
    <div className="device-status-container">
      <h2>Status / Indicator</h2>

      <div className="status-grid">
        {/* Camera Status */}
        {status?.camera && (
          <div className="status-card">
            <div className="card-title">Camera</div>
            <div className="card-content">
              <div className="status-item">
                <span className="label">Status:</span>
                <span className={`value ${status.camera.is_open ? 'active' : 'inactive'}`}>
                  {status.camera.is_open ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="status-item">
                <span className="label">Frames:</span>
                <span className="value">{status.camera.frame_count}</span>
              </div>
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
                return (
                  <div className="status-item" key={key}>
                    <span className="label">{input?.label || key}</span>
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

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
      <h2>Device Status</h2>

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

        {/* CUDA Status */}
        {status?.cuda && (
          <div className="status-card">
            <div className="card-title">CUDA</div>
            <div className="card-content">
              <div className="status-item">
                <span className="label">Available:</span>
                <span className={`value ${status.cuda.cuda_available ? 'active' : 'inactive'}`}>
                  {status.cuda.cuda_available ? 'Yes' : 'No'}
                </span>
              </div>
              <div className="status-item">
                <span className="label">Devices:</span>
                <span className="value">{status.cuda.cuda_device_count || 0}</span>
              </div>
            </div>
          </div>
        )}

        {/* GPIO Status */}
        {status?.gpio && (
          <div className="status-card">
            <div className="card-title">GPIO</div>
            <div className="card-content">
              <div className="status-item">
                <span className="label">LED:</span>
                <span className={`value ${status.gpio.led_on ? 'active' : 'inactive'}`}>
                  {status.gpio.led_on ? 'ON' : 'OFF'}
                </span>
              </div>
              <div className="status-item">
                <span className="label">Available:</span>
                <span className={`value ${status.gpio.gpio_available ? 'active' : 'inactive'}`}>
                  {status.gpio.gpio_available ? 'Yes' : 'No'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* WebSocket Connections */}
        {typeof status?.websocket_connections !== 'undefined' && (
          <div className="status-card">
            <div className="card-title">WebSocket</div>
            <div className="card-content">
              <div className="status-item">
                <span className="label">Connections:</span>
                <span className="value">{status.websocket_connections}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {status?.timestamp && (
        <div className="status-footer">
          <span>Last updated: {new Date(status.timestamp).toLocaleTimeString()}</span>
          <span className={`refresh-indicator ${isRefreshing ? 'active' : ''}`}>
            {isRefreshing ? 'Updating…' : 'Live'}
          </span>
        </div>
      )}
    </div>
  )
}

export default DeviceStatus

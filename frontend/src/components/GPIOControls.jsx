import React, { useState, useEffect } from 'react'
import { gpioAPI } from '../services/api'
import './GPIOControls.css'

export const GPIOControls = () => {
  const [ledState, setLedState] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  // Fetch initial GPIO state
  useEffect(() => {
    fetchGPIOStatus()
  }, [])

  const fetchGPIOStatus = async () => {
    try {
      const response = await gpioAPI.getStatus()
      setLedState(response.data.gpio.led_on || false)
    } catch (err) {
      console.error('Failed to fetch GPIO status:', err)
    }
  }

  const handleLedOn = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await gpioAPI.turnOn()
      setLedState(response.data.gpio.led_on)
    } catch (err) {
      setError('Failed to turn LED on')
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleLedOff = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await gpioAPI.turnOff()
      setLedState(!response.data.gpio.led_on)
    } catch (err) {
      setError('Failed to turn LED off')
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleToggle = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await gpioAPI.toggle()
      setLedState(response.data.gpio.led_on)
    } catch (err) {
      setError('Failed to toggle LED')
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="gpio-controls-container">
      <h2>GPIO Controls</h2>

      <div className="gpio-status-display">
        <div className="status-label">LED Status:</div>
        <div className={`led-indicator ${ledState ? 'on' : 'off'}`}>
          {ledState ? 'ON' : 'OFF'}
        </div>
      </div>

      <div className="gpio-buttons">
        <button
          onClick={handleLedOn}
          disabled={isLoading || ledState}
          className="btn btn-success"
        >
          {isLoading ? 'Loading...' : 'LED ON'}
        </button>

        <button
          onClick={handleLedOff}
          disabled={isLoading || !ledState}
          className="btn btn-danger"
        >
          {isLoading ? 'Loading...' : 'LED OFF'}
        </button>

        <button
          onClick={handleToggle}
          disabled={isLoading}
          className="btn btn-warning"
        >
          {isLoading ? 'Loading...' : 'TOGGLE'}
        </button>
      </div>

      {error && (
        <div className="error-alert">
          {error}
        </div>
      )}
    </div>
  )
}

export default GPIOControls

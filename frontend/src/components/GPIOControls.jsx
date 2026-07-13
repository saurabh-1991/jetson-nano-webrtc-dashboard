import React, { useState, useEffect } from 'react'
import { gpioAPI } from '../services/api'
import ToggleSwitch from './ToggleSwitch'
import './GPIOControls.css'

export const GPIOControls = () => {
  const OUTPUTS = [
    { key: 'exhaust_blower', label: 'Exhaust Blower' },
    { key: 'air_mixer_blower', label: 'Air Mixer Blower' },
    { key: 'lpg_burner', label: 'LPG Burner' },
  ]

  const [outputsState, setOutputsState] = useState({})
  const [gpioAvailable, setGpioAvailable] = useState(true)
  const [loadingOutput, setLoadingOutput] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchGPIOStatus()

    const interval = setInterval(fetchGPIOStatus, 5000)

    return () => clearInterval(interval)
  }, [])

  const fetchGPIOStatus = async () => {
    try {
      const response = await gpioAPI.getOutputs()
      const gpio = response.data.gpio || {}
      setOutputsState(gpio.outputs || {})
      setGpioAvailable(gpio.gpio_available !== false)
      setError(null)
    } catch (err) {
      console.error('Failed to fetch GPIO status:', err)
      setError('Failed to fetch controls status')
    }
  }

  const setOutputState = async (outputName, turnOn) => {
    setLoadingOutput(outputName)
    setError(null)

    try {
      const response = turnOn
        ? await gpioAPI.turnOutputOn(outputName)
        : await gpioAPI.turnOutputOff(outputName)

      if (!response.data.success) {
        throw new Error('GPIO not available on backend runtime')
      }

      const gpio = response.data.gpio || {}
      setOutputsState(gpio.outputs || {})
      setGpioAvailable(gpio.gpio_available !== false)
    } catch (err) {
      setError(`Failed to set ${outputName}`)
      console.error(err)
      await fetchGPIOStatus()
    } finally {
      setLoadingOutput(null)
    }
  }

  const handleToggle = (outputName, currentState) => {
    const nextState = !currentState
    setOutputState(outputName, nextState)
  }

  return (
    <div className="gpio-controls-container">
      <h2>Controls</h2>

      <div className="output-list">
        {OUTPUTS.map((output) => {
          const current = outputsState[output.key] || {}
          const isOn = !!current.on
          const pin = current.pin
          const isLoading = loadingOutput === output.key

          return (
            <div className="output-card" key={output.key}>
              <div className="output-meta">
                <div className="output-title">{output.label}</div>
                <div className="output-subtitle">
                  {typeof pin === 'number' ? `BOARD Pin ${pin}` : 'Pin not configured'}
                </div>
              </div>

              <div className="output-actions">
                <span className={`state-pill ${isOn ? 'on' : 'off'}`}>
                  {isOn ? 'ON' : 'OFF'}
                </span>

                <ToggleSwitch
                  isOn={isOn}
                  handleToggle={() => handleToggle(output.key, isOn)}
                  disabled={isLoading || !gpioAvailable}
                />
              </div>
            </div>
          )
        })}
      </div>

      {!gpioAvailable && (
        <div className="error-alert">
          GPIO is unavailable in backend runtime. Hardware controls are disabled.
        </div>
      )}

      {error && (
        <div className="error-alert">
          {error}
        </div>
      )}
    </div>
  )
}

export default GPIOControls

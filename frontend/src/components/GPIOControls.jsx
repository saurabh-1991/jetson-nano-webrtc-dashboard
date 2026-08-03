import React, { useState, useEffect } from 'react'
import { gpioAPI } from '../services/api'
import { vfdAPI } from '../services/api'
import { getApiCooldownState } from '../services/api'
import { shouldThrottleClientNoise } from '../services/api'
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
  const [vfdStatus, setVfdStatus] = useState(null)
  const [vfdRunBusy, setVfdRunBusy] = useState(false)
  const [vfdSpeedBusy, setVfdSpeedBusy] = useState(false)
  const [vfdSpeedDraft, setVfdSpeedDraft] = useState('0')
  const [vfdSpeedDirty, setVfdSpeedDirty] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchControlStatus()

    const interval = setInterval(fetchControlStatus, 5000)

    return () => clearInterval(interval)
  }, [])

  const fetchControlStatus = async () => {
    const cooldown = getApiCooldownState()
    if (cooldown.active) {
      return
    }

    try {
      const [gpioResponse, vfdResponse] = await Promise.allSettled([
        gpioAPI.getOutputs(),
        vfdAPI.getStatus(),
      ])

      if (gpioResponse.status === 'fulfilled') {
        const gpio = gpioResponse.value?.data?.gpio || {}
        setOutputsState(gpio.outputs || {})
        setGpioAvailable(gpio.gpio_available !== false)
      }

      if (vfdResponse.status === 'fulfilled') {
        const vfd = vfdResponse.value?.data?.vfd || null
        setVfdStatus(vfd)
        if (vfd && !vfdSpeedDirty) {
          setVfdSpeedDraft(String(vfd.speed_hz ?? 0))
        }
      }

      const allFailed = gpioResponse.status === 'rejected' && vfdResponse.status === 'rejected'
      setError(allFailed ? 'Failed to fetch controls status' : null)
    } catch (err) {
      if (!shouldThrottleClientNoise('gpio_status_fetch_failed')) {
        console.error('Failed to fetch control status:', err)
      }
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
      if (!shouldThrottleClientNoise(`gpio_set_failed_${outputName}`)) {
        console.error(err)
      }
      await fetchControlStatus()
    } finally {
      setLoadingOutput(null)
    }
  }

  const handleToggle = (outputName, currentState) => {
    const nextState = !currentState
    setOutputState(outputName, nextState)
  }

  const currentVfdSpeed = Number(vfdSpeedDraft)
  const hasValidVfdSpeedDraft = Number.isFinite(currentVfdSpeed)
  const minVfdSpeed = Number(vfdStatus?.min_speed_hz ?? 0)
  const maxVfdSpeed = Number(vfdStatus?.max_speed_hz ?? 50)
  const isVfdConfigured = !!(vfdStatus?.enabled && vfdStatus?.library_available && vfdStatus?.host_configured)
  const vfdRunState = !!vfdStatus?.is_running

  const handleVfdRunToggle = async () => {
    if (!vfdStatus) {
      return
    }

    const nextRunState = !vfdRunState
    setVfdRunBusy(true)
    setError(null)
    try {
      const response = await vfdAPI.setRun(nextRunState)
      const updated = response?.data?.vfd || null
      setVfdStatus(updated)
    } catch (err) {
      setError(`Failed to ${nextRunState ? 'start' : 'stop'} VFD`)
      if (!shouldThrottleClientNoise('vfd_run_toggle_failed')) {
        console.error(err)
      }
      await fetchControlStatus()
    } finally {
      setVfdRunBusy(false)
    }
  }

  const handleVfdSpeedApply = async () => {
    if (!hasValidVfdSpeedDraft) {
      setError('VFD speed must be a valid number')
      return
    }

    if (currentVfdSpeed < minVfdSpeed || currentVfdSpeed > maxVfdSpeed) {
      setError(`VFD speed must be between ${minVfdSpeed} and ${maxVfdSpeed} Hz`)
      return
    }

    setVfdSpeedBusy(true)
    setError(null)
    try {
      const response = await vfdAPI.setSpeed(currentVfdSpeed)
      const ok = !!response?.data?.success
      const updated = response?.data?.vfd || null
      setVfdStatus(updated)

      if (!ok) {
        const reason = response?.data?.result?.error || 'unknown error'
        setError(`Failed to set VFD speed: ${reason}`)
      } else {
        setVfdSpeedDirty(false)
      }
    } catch (err) {
      const detail = err?.response?.data?.detail
      const detailMessage = typeof detail?.error === 'string' ? detail.error : null
      setError(`Failed to set VFD speed${detailMessage ? `: ${detailMessage}` : ''}`)
      if (!shouldThrottleClientNoise('vfd_speed_apply_failed')) {
        console.error(err)
      }
      await fetchControlStatus()
    } finally {
      setVfdSpeedBusy(false)
    }
  }

  const handleVfdSliderChange = (event) => {
    setVfdSpeedDraft(event.target.value)
    setVfdSpeedDirty(true)
  }

  const handleVfdInputChange = (event) => {
    const raw = event.target.value
    setVfdSpeedDraft(raw)
    setVfdSpeedDirty(true)
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

      <div className="vfd-card">
        <div className="vfd-header-row">
          <div className="vfd-title-wrap">
            <div className="output-title">Delta VFD MS300</div>
            <div className="output-subtitle">
              {vfdStatus?.host ? `${vfdStatus.host}:${vfdStatus.port}` : 'Host not configured'}
            </div>
          </div>

          <div className="output-actions">
            <span className={`state-pill ${vfdRunState ? 'on' : 'off'}`}>
              {vfdRunState ? 'RUN' : 'STOP'}
            </span>
            <ToggleSwitch
              isOn={vfdRunState}
              handleToggle={handleVfdRunToggle}
              disabled={!isVfdConfigured || vfdRunBusy || vfdSpeedBusy}
            />
          </div>
        </div>

        <div className="vfd-speed-grid">
          <label htmlFor="vfd-speed-slider" className="vfd-speed-label">Speed Setpoint (Hz)</label>
          <input
            id="vfd-speed-slider"
            type="range"
            min={minVfdSpeed}
            max={maxVfdSpeed}
            step="0.1"
            value={hasValidVfdSpeedDraft ? currentVfdSpeed : minVfdSpeed}
            onChange={handleVfdSliderChange}
            disabled={!isVfdConfigured || vfdSpeedBusy}
          />

          <div className="vfd-speed-input-row">
            <input
              type="number"
              min={minVfdSpeed}
              max={maxVfdSpeed}
              step="0.1"
              value={vfdSpeedDraft}
              onChange={handleVfdInputChange}
              disabled={!isVfdConfigured || vfdSpeedBusy}
            />
            <button
              type="button"
              className="vfd-apply-btn"
              onClick={handleVfdSpeedApply}
              disabled={!isVfdConfigured || vfdSpeedBusy}
            >
              {vfdSpeedBusy ? 'Applying...' : 'Apply Speed'}
            </button>
          </div>

          <div className="output-subtitle">
            Allowed range: {minVfdSpeed} - {maxVfdSpeed} Hz
          </div>
        </div>
      </div>

      {!gpioAvailable && (
        <div className="error-alert">
          GPIO is unavailable in backend runtime. Hardware controls are disabled.
        </div>
      )}

      {vfdStatus && !isVfdConfigured && (
        <div className="error-alert">
          VFD control is not ready. Check backend VFD settings and Modbus network. {vfdStatus.last_error ? `(${vfdStatus.last_error})` : ''}
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

import React, { useState, useEffect, useRef } from 'react'
import { gpioAPI } from '../services/api'
import { vfdAPI } from '../services/api'
import { getApiCooldownState } from '../services/api'
import { shouldThrottleClientNoise } from '../services/api'
import ToggleSwitch from './ToggleSwitch'
import './GPIOControls.css'

export const GPIOControls = () => {
  const OUTPUTS = [
    { key: 'lpg_burner', label: 'LPG Burner' },
  ]

  const VFD_TARGETS = [
    { id: 'vfd1', label: 'Cold Air' },
    { id: 'vfd2', label: 'Exhaust Blower' },
  ]

  const [outputsState, setOutputsState] = useState({})
  const [gpioAvailable, setGpioAvailable] = useState(true)
  const [loadingOutput, setLoadingOutput] = useState(null)
  const [vfdStatuses, setVfdStatuses] = useState({})
  const [vfdRunBusy, setVfdRunBusy] = useState({})
  const [vfdSpeedBusy, setVfdSpeedBusy] = useState({})
  const [vfdSpeedDrafts, setVfdSpeedDrafts] = useState({})
  const [vfdSpeedDirty, setVfdSpeedDirty] = useState({})
  const [error, setError] = useState(null)
  const vfdSpeedDirtyRef = useRef({})

  useEffect(() => {
    vfdSpeedDirtyRef.current = vfdSpeedDirty
  }, [vfdSpeedDirty])

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
      const requestList = [
        gpioAPI.getOutputs(),
        ...VFD_TARGETS.map((vfd) => vfdAPI.getStatus(vfd.id)),
      ]
      const responses = await Promise.allSettled(requestList)

      const gpioResponse = responses[0]
      const vfdResponses = responses.slice(1)

      if (gpioResponse.status === 'fulfilled') {
        const gpio = gpioResponse.value?.data?.gpio || {}
        setOutputsState(gpio.outputs || {})
        setGpioAvailable(gpio.gpio_available !== false)
      }

      const freshStatuses = {}
      const draftUpdates = {}
      vfdResponses.forEach((result, index) => {
        const vfdId = VFD_TARGETS[index]?.id
        if (!vfdId || result.status !== 'fulfilled') {
          return
        }

        const vfd = result.value?.data?.vfd || null
        if (!vfd) {
          return
        }

        freshStatuses[vfdId] = vfd
        if (!vfdSpeedDirtyRef.current[vfdId]) {
          draftUpdates[vfdId] = String(vfd.speed_hz ?? 0)
        }
      })

      if (Object.keys(freshStatuses).length > 0) {
        setVfdStatuses((prev) => ({ ...prev, ...freshStatuses }))
      }

      if (Object.keys(draftUpdates).length > 0) {
        setVfdSpeedDrafts((prev) => ({ ...prev, ...draftUpdates }))
      }

      const anyVfdSuccess = vfdResponses.some((result) => result.status === 'fulfilled')
      const allFailed = gpioResponse.status === 'rejected' && !anyVfdSuccess
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

  const handleVfdRunToggle = async (vfdId) => {
    const vfdStatus = vfdStatuses[vfdId]
    if (!vfdStatus) {
      return
    }

    const vfdRunState = !!vfdStatus?.is_running

    const nextRunState = !vfdRunState
    setVfdRunBusy((prev) => ({ ...prev, [vfdId]: true }))
    setError(null)
    try {
      const response = await vfdAPI.setRun(nextRunState, vfdId)
      const ok = !!response?.data?.success
      const updated = response?.data?.vfd || null
      if (updated) {
        setVfdStatuses((prev) => ({ ...prev, [vfdId]: updated }))
      }
      if (!ok) {
        setError(`Failed to ${nextRunState ? 'start' : 'stop'} ${vfdId.toUpperCase()}`)
      }
      await fetchControlStatus()
    } catch (err) {
      setError(`Failed to ${nextRunState ? 'start' : 'stop'} ${vfdId.toUpperCase()}`)
      if (!shouldThrottleClientNoise('vfd_run_toggle_failed')) {
        console.error(err)
      }
      await fetchControlStatus()
    } finally {
      setVfdRunBusy((prev) => ({ ...prev, [vfdId]: false }))
    }
  }

  const handleVfdSpeedApply = async (vfdId) => {
    const vfdStatus = vfdStatuses[vfdId]
    if (!vfdStatus) {
      return
    }

    const draftValue = vfdSpeedDrafts[vfdId] ?? String(vfdStatus?.speed_hz ?? 0)
    const currentVfdSpeed = Number(draftValue)
    const hasValidVfdSpeedDraft = Number.isFinite(currentVfdSpeed)
    const minVfdSpeed = Number(vfdStatus?.min_speed_hz ?? 0)
    const maxVfdSpeed = Number(vfdStatus?.max_speed_hz ?? 50)

    if (!hasValidVfdSpeedDraft) {
      setError('VFD speed must be a valid number')
      return
    }

    if (currentVfdSpeed < minVfdSpeed || currentVfdSpeed > maxVfdSpeed) {
      setError(`VFD speed must be between ${minVfdSpeed} and ${maxVfdSpeed} Hz`)
      return
    }

    setVfdSpeedBusy((prev) => ({ ...prev, [vfdId]: true }))
    setError(null)
    try {
      const response = await vfdAPI.setSpeed(currentVfdSpeed, vfdId)
      const ok = !!response?.data?.success
      const updated = response?.data?.vfd || null
      if (updated) {
        setVfdStatuses((prev) => ({ ...prev, [vfdId]: updated }))
      }

      if (!ok) {
        const reason = response?.data?.result?.error || 'unknown error'
        setError(`Failed to set ${vfdId.toUpperCase()} speed: ${reason}`)
      } else {
        setVfdSpeedDirty((prev) => ({ ...prev, [vfdId]: false }))
      }
      await fetchControlStatus()
    } catch (err) {
      const detail = err?.response?.data?.detail
      const detailMessage = typeof detail?.error === 'string' ? detail.error : null
      setError(`Failed to set ${vfdId.toUpperCase()} speed${detailMessage ? `: ${detailMessage}` : ''}`)
      if (!shouldThrottleClientNoise('vfd_speed_apply_failed')) {
        console.error(err)
      }
      await fetchControlStatus()
    } finally {
      setVfdSpeedBusy((prev) => ({ ...prev, [vfdId]: false }))
    }
  }

  const handleVfdSliderChange = (vfdId, event) => {
    setVfdSpeedDrafts((prev) => ({ ...prev, [vfdId]: event.target.value }))
    setVfdSpeedDirty((prev) => ({ ...prev, [vfdId]: true }))
  }

  const handleVfdInputChange = (vfdId, event) => {
    const raw = event.target.value
    setVfdSpeedDrafts((prev) => ({ ...prev, [vfdId]: raw }))
    setVfdSpeedDirty((prev) => ({ ...prev, [vfdId]: true }))
  }

  return (
    <div className="gpio-controls-container">
      <h2>Controls</h2>

      <div className={`output-list ${OUTPUTS.length <= 1 ? 'single' : ''}`}>
        {OUTPUTS.map((output) => {
          const current = outputsState[output.key] || {}
          const isOn = !!current.on
          const pin = current.pin
          const activeLow = current.active_low === true
          const gpioLevel = String(current.gpio_level || 'UNKNOWN')
          const expectedGpioLevel = String(current.expected_gpio_level || 'UNKNOWN')
          const hasLevelMismatch = gpioLevel !== 'UNKNOWN' && expectedGpioLevel !== 'UNKNOWN' && gpioLevel !== expectedGpioLevel
          const isLoading = loadingOutput === output.key

          return (
            <div className="output-card" key={output.key}>
              <div className="output-meta">
                <div className="output-title">{output.label}</div>
                <div className="output-subtitle">
                  {typeof pin === 'number' ? `BOARD Pin ${pin}` : 'Pin not configured'}
                </div>
                <div className={`gpio-level-row ${hasLevelMismatch ? 'mismatch' : ''}`}>
                  <span>Mode: {activeLow ? 'Active-Low' : 'Active-High'}</span>
                  <span>Expected: {expectedGpioLevel}</span>
                  <span>Actual: {gpioLevel}</span>
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

      <div className="vfd-grid">
        {VFD_TARGETS.map((vfdTarget) => {
          const vfdId = vfdTarget.id
          const vfdStatus = vfdStatuses[vfdId] || null
          const minVfdSpeed = Number(vfdStatus?.min_speed_hz ?? 0)
          const maxVfdSpeed = Number(vfdStatus?.max_speed_hz ?? 50)
          const appliedVfdSpeed = Number(vfdStatus?.speed_hz ?? minVfdSpeed)
          const vfdSpeedScale = Number(vfdStatus?.speed_scale ?? 100)
          const draftValue = vfdSpeedDrafts[vfdId] ?? String(vfdStatus?.speed_hz ?? minVfdSpeed)
          const currentVfdSpeed = Number(draftValue)
          const hasValidVfdSpeedDraft = Number.isFinite(currentVfdSpeed)
          const selectedVfdSpeed = hasValidVfdSpeedDraft ? currentVfdSpeed : minVfdSpeed
          const selectedRegisterWord = Math.round(selectedVfdSpeed * vfdSpeedScale)
          const vfdRangeSpan = Math.max(0, maxVfdSpeed - minVfdSpeed)
          const vfdScaleMarks = vfdRangeSpan > 0
            ? Array.from({ length: 6 }, (_, index) => {
              const value = minVfdSpeed + ((vfdRangeSpan / 5) * index)
              return Number(value.toFixed(1))
            })
            : [Number(minVfdSpeed.toFixed(1))]
          const isVfdConfigured = !!(vfdStatus?.enabled && vfdStatus?.library_available && vfdStatus?.host_configured)
          const vfdRunState = !!vfdStatus?.is_running
          const isRunBusy = !!vfdRunBusy[vfdId]
          const isSpeedBusy = !!vfdSpeedBusy[vfdId]
          const isSpeedDirty = !!vfdSpeedDirty[vfdId]

          return (
            <div className="vfd-card" key={vfdId}>
              <div className="vfd-header-row">
                <div className="vfd-title-wrap">
                  <div className="output-title">{vfdTarget.label}</div>
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
                    handleToggle={() => handleVfdRunToggle(vfdId)}
                    disabled={!isVfdConfigured || isRunBusy || isSpeedBusy}
                  />
                </div>
              </div>

              <div className="vfd-speed-grid">
                <label htmlFor={`${vfdId}-speed-slider`} className="vfd-speed-label">Speed Setpoint (Hz)</label>

                <div className="vfd-speed-live-row">
                  <span className="vfd-live-chip">
                    Selected: {selectedVfdSpeed.toFixed(1)} Hz
                  </span>
                  <span className="vfd-live-chip">
                    Applied: {Number.isFinite(appliedVfdSpeed) ? appliedVfdSpeed.toFixed(1) : '--'} Hz
                  </span>
                  <span className="vfd-live-chip subtle">
                    Cmd Word: {selectedRegisterWord}
                  </span>
                  {isSpeedDirty && (
                    <span className="vfd-live-chip subtle">Pending apply</span>
                  )}
                </div>

                <input
                  id={`${vfdId}-speed-slider`}
                  type="range"
                  min={minVfdSpeed}
                  max={maxVfdSpeed}
                  step="0.1"
                  value={selectedVfdSpeed}
                  list={`${vfdId}-speed-scale`}
                  onChange={(event) => handleVfdSliderChange(vfdId, event)}
                  disabled={!isVfdConfigured || isSpeedBusy}
                />

                <datalist id={`${vfdId}-speed-scale`}>
                  {vfdScaleMarks.map((markValue) => (
                    <option key={markValue} value={markValue} />
                  ))}
                </datalist>

                <div className="vfd-scale-row" aria-hidden="true">
                  {vfdScaleMarks.map((markValue) => (
                    <span key={`label-${vfdId}-${markValue}`} className="vfd-scale-label">{markValue.toFixed(1)}</span>
                  ))}
                </div>

                <div className="vfd-speed-input-row">
                  <input
                    type="number"
                    min={minVfdSpeed}
                    max={maxVfdSpeed}
                    step="0.1"
                    value={draftValue}
                    onChange={(event) => handleVfdInputChange(vfdId, event)}
                    disabled={!isVfdConfigured || isSpeedBusy}
                  />
                  <button
                    type="button"
                    className="vfd-apply-btn"
                    onClick={() => handleVfdSpeedApply(vfdId)}
                    disabled={!isVfdConfigured || isSpeedBusy}
                  >
                    {isSpeedBusy ? 'Applying...' : 'Apply Speed'}
                  </button>
                </div>

                <div className="output-subtitle">
                  Allowed range: {minVfdSpeed} - {maxVfdSpeed} Hz (MS300 command resolution via scale: {vfdSpeedScale})
                </div>

                {!isVfdConfigured && (
                  <div className="output-subtitle">
                    VFD is not ready{vfdStatus?.last_error ? ` (${vfdStatus.last_error})` : ''}
                  </div>
                )}
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

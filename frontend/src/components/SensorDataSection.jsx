import React, { useEffect, useMemo, useState } from 'react'
import { sensorAPI } from '../services/api'
import ToggleSwitch from './ToggleSwitch'
import './SensorDataSection.css'

const SERIES = [
  { key: 'hot_zone_temperature', label: 'Hot Zone Temperature', color: '#ef4444' },
  { key: 'cold_zone_temperature', label: 'Cold Zone Temperature', color: '#3b82f6' },
  { key: 'exhaust_temp', label: 'Exaust Temp', color: '#f59e0b' },
]

const HISTORY_INTERVAL_OPTIONS = [
  { value: 1, label: '1 min' },
  { value: 5, label: '5 min' },
  { value: 15, label: '15 min' },
  { value: 30, label: '30 min' },
]

const HISTORY_RANGE_OPTIONS = [
  { value: 6, label: 'Last 6h' },
  { value: 12, label: 'Last 12h' },
  { value: 24, label: 'Last 24h' },
  { value: 48, label: 'Last 48h' },
]

const SENSOR_POLL_BASE_MS = 2000
const SENSOR_POLL_MAX_MS = 15000
const HISTORY_REFRESH_MS = 10000

function getRetryDelayMs(failureCount) {
  const step = Math.max(0, Math.min(4, Number(failureCount || 0)))
  return Math.min(SENSOR_POLL_MAX_MS, SENSOR_POLL_BASE_MS * (2 ** step))
}

function formatValue(value) {
  if (typeof value !== 'number') return '--'
  return `${value.toFixed(1)} °C`
}

function formatDateTime(value) {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return '--'
  }
}

function buildPolyline(history, key, width, height, minY, maxY, leftPad = 0, rightPad = 0) {
  if (!history || history.length < 2) return ''
  const plotWidth = Math.max(width - leftPad - rightPad, 1)
  const xStep = plotWidth / Math.max(history.length - 1, 1)
  const yRange = Math.max(maxY - minY, 1)

  return history
    .map((item, index) => {
      const x = leftPad + index * xStep
      const yValue = typeof item[key] === 'number' ? item[key] : minY
      const y = height - ((yValue - minY) / yRange) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

export const SensorDataSection = () => {
  const [latest, setLatest] = useState(null)
  const [history, setHistory] = useState([])
  const [realtimeHistory, setRealtimeHistory] = useState([])
  const [isRealtimeMode, setIsRealtimeMode] = useState(true)
  const [isSimulationEnabled, setIsSimulationEnabled] = useState(true)
  const [isUpdatingSimulation, setIsUpdatingSimulation] = useState(false)
  const [activeTab, setActiveTab] = useState(SERIES[0].key)
  const [historyIntervalMinutes, setHistoryIntervalMinutes] = useState(5)
  const [historyHours, setHistoryHours] = useState(24)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)
  const [retryDelayMs, setRetryDelayMs] = useState(SENSOR_POLL_BASE_MS)

  useEffect(() => {
    let mounted = true
    let pollTimer = null
    let failureCount = 0
    let lastHistoryFetchAt = 0

    const scheduleNextPoll = (delayMs) => {
      if (!mounted) return
      pollTimer = setTimeout(() => {
        fetchSensorData()
      }, delayMs)
    }

    const fetchSensorData = async () => {
      try {
        const latestResponse = await sensorAPI.getLatest()

        if (!mounted) return

        const latestSensors = latestResponse.data?.sensors || null
        const latestTimestamp = latestSensors?.timestamp || latestResponse.data?.timestamp || null

        setLatest(latestSensors)
        setLastUpdated(latestTimestamp)
        if (typeof latestResponse.data?.simulation_enabled === 'boolean') {
          setIsSimulationEnabled(latestResponse.data.simulation_enabled)
        }

        if (latestSensors) {
          const hasAnyNumericValue = SERIES.some((series) => typeof latestSensors?.[series.key] === 'number')
          if (hasAnyNumericValue) {
            setRealtimeHistory((prev) => {
              const next = [...prev, latestSensors]
              return next.slice(-180)
            })
          }
        }

        const nowMs = Date.now()
        if (!isRealtimeMode && ((nowMs - lastHistoryFetchAt) >= HISTORY_REFRESH_MS)) {
          const historyResponse = await sensorAPI.getHistory({
            limit: 500,
            intervalMinutes: historyIntervalMinutes,
            hours: historyHours,
          })
          setHistory(Array.isArray(historyResponse.data?.history) ? historyResponse.data.history : [])
          lastHistoryFetchAt = nowMs
        }

        failureCount = 0
        setRetryDelayMs(SENSOR_POLL_BASE_MS)
        setError(null)
        scheduleNextPoll(SENSOR_POLL_BASE_MS)
      } catch (err) {
        if (!mounted) return
        const retryMs = getRetryDelayMs(failureCount)

        if (failureCount === 0 || failureCount % 5 === 0) {
          console.warn('Sensor polling retry due to transient error:', err?.message || err)
        }

        failureCount += 1
        setRetryDelayMs(retryMs)
        setError(`Unable to load sensor data (retrying in ${Math.ceil(retryMs / 1000)}s)`)
        scheduleNextPoll(retryMs)
      }
    }

    fetchSensorData()

    return () => {
      mounted = false
      if (pollTimer) {
        clearTimeout(pollTimer)
      }
    }
  }, [historyIntervalMinutes, historyHours, isRealtimeMode])

  const displayedHistory = isRealtimeMode ? realtimeHistory : history
  const hasLatestSample = !!lastUpdated

  const numericSamples = useMemo(
    () => displayedHistory.filter((item) => typeof item?.[activeTab] === 'number'),
    [displayedHistory, activeTab]
  )

  const chartMeta = useMemo(() => {
    const values = numericSamples.map((item) => item?.[activeTab])

    if (values.length === 0) {
      return { minY: 0, maxY: 100 }
    }

    const minRaw = Math.min(...values)
    const maxRaw = Math.max(...values)
    const pad = Math.max((maxRaw - minRaw) * 0.12, 2)

    return {
      minY: minRaw - pad,
      maxY: maxRaw + pad,
    }
  }, [numericSamples, activeTab])

  const activeSeries = SERIES.find((s) => s.key === activeTab) || SERIES[0]
  const graphWidth = 560
  const graphHeight = 240
  const graphLeftPad = 8
  const graphRightPad = 8

  const yTicks = useMemo(() => {
    const steps = 5
    if (numericSamples.length === 0) {
      return Array.from({ length: steps + 1 }, (_, i) => ({
        y: (i / steps) * graphHeight,
        label: 'NA',
      }))
    }

    const range = chartMeta.maxY - chartMeta.minY
    if (!Number.isFinite(range) || range <= 0) return []

    const ticks = []
    for (let i = 0; i <= steps; i += 1) {
      const ratio = i / steps
      const value = chartMeta.maxY - ratio * range
      const y = ratio * graphHeight
      ticks.push({ y, label: `${value.toFixed(1)}°C` })
    }
    return ticks
  }, [chartMeta.maxY, chartMeta.minY, graphHeight, numericSamples.length])

  const handleSimulationToggle = async () => {
    const target = !isSimulationEnabled
    try {
      setIsUpdatingSimulation(true)
      await sensorAPI.setSimulationMode(target)
      setIsSimulationEnabled(target)
      setRealtimeHistory([])
      setHistory([])
      setError(null)
    } catch (err) {
      console.error('Failed to update simulation mode:', err)
      setError('Unable to switch simulation mode')
    } finally {
      setIsUpdatingSimulation(false)
    }
  }

  return (
    <div className="sensor-row-grid">
      <section className="sensor-card reading-card">
        <h2>Sensor Data Reading</h2>

        <div className="simulation-toggle-row">
          <ToggleSwitch
            label="Simulation"
            isOn={isSimulationEnabled}
            handleToggle={handleSimulationToggle}
            disabled={isUpdatingSimulation}
          />
        </div>

        {isSimulationEnabled && (
          <div className="simulation-note">
            Demo note: Simulated data is shown for demonstration and is not actual datalogger data.
          </div>
        )}

        <div className="reading-list">
          {SERIES.map((series) => (
            <div className="reading-item" key={series.key}>
              <span className="reading-label">{series.label}</span>
              <span className="reading-value">{formatValue(latest?.[series.key])}</span>
            </div>
          ))}
        </div>

        {error && <div className="sensor-error">{error}</div>}

        {!error && retryDelayMs > SENSOR_POLL_BASE_MS && (
          <div className="sensor-error">Transient network issue recovered. Polling every {Math.ceil(retryDelayMs / 1000)}s.</div>
        )}

        <div className="sensor-last-updated">
          Last updated: <strong>{formatDateTime(lastUpdated)}</strong>
        </div>
      </section>

      <section className="sensor-card graph-card">
        <div className="graph-title-row">
          <h2>Graph</h2>
          {!isSimulationEnabled && numericSamples.length === 0 && (
            <span className="logger-warning-badge">NO LOGGER DATA</span>
          )}
        </div>

        <div className="graph-controls">
          <div className="graph-mode-toggle">
            <ToggleSwitch
              label="Realtime"
              isOn={isRealtimeMode}
              handleToggle={() => setIsRealtimeMode((prev) => !prev)}
            />
            <span className="graph-mode-badge">{isRealtimeMode ? 'LIVE' : 'HISTORY'}</span>
          </div>

          <div className="graph-tabs" role="tablist" aria-label="Sensor graph tabs">
            {SERIES.map((series) => (
              <button
                key={series.key}
                className={`graph-tab ${activeTab === series.key ? 'active' : ''}`}
                style={activeTab === series.key ? { borderColor: series.color, color: series.color } : undefined}
                onClick={() => setActiveTab(series.key)}
                role="tab"
                aria-selected={activeTab === series.key}
                type="button"
              >
                {series.label}
              </button>
            ))}
          </div>

          {!isRealtimeMode && (
            <div className="history-filters">
              <label>
                Interval
                <select
                  value={historyIntervalMinutes}
                  onChange={(e) => setHistoryIntervalMinutes(Number(e.target.value))}
                >
                  {HISTORY_INTERVAL_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>

              <label>
                Range
                <select
                  value={historyHours}
                  onChange={(e) => setHistoryHours(Number(e.target.value))}
                >
                  {HISTORY_RANGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </div>

        <div className="graph-legend">
          {SERIES.map((series) => (
            <span key={series.key} className="legend-item">
              <span className="legend-dot" style={{ backgroundColor: series.color }}></span>
              {series.label}
            </span>
          ))}
        </div>

        <div className="graph-wrapper">
          {displayedHistory.length === 0 && !hasLatestSample ? (
            <div className="graph-empty">Waiting for sensor samples…</div>
          ) : (
            <>
              <svg viewBox={`0 0 ${graphWidth} ${graphHeight}`} className="sensor-graph" preserveAspectRatio="none">
                {yTicks.map((tick, idx) => (
                  <g key={`y-tick-${idx}`}>
                    <line
                      x1={graphLeftPad}
                      y1={tick.y}
                      x2={graphWidth - graphRightPad}
                      y2={tick.y}
                      className="grid-line"
                    />
                    <text x={graphLeftPad + 2} y={Math.max(10, tick.y - 2)} className="axis-text y-axis-text">
                      {tick.label}
                    </text>
                  </g>
                ))}

                <line x1={graphLeftPad} y1={graphHeight} x2={graphWidth - graphRightPad} y2={graphHeight} className="axis-line" />

                <polyline
                  fill="none"
                  stroke={activeSeries.color}
                  strokeWidth="3"
                  points={buildPolyline(
                    numericSamples,
                    activeSeries.key,
                    graphWidth,
                    graphHeight,
                    chartMeta.minY,
                    chartMeta.maxY,
                    graphLeftPad,
                    graphRightPad,
                  )}
                />

                {numericSamples.length === 1 && (
                  <circle
                    cx={graphWidth / 2}
                    cy={graphHeight / 2}
                    r="5"
                    fill={activeSeries.color}
                  />
                )}
              </svg>

            </>
          )}
        </div>
      </section>
    </div>
  )
}

export default SensorDataSection

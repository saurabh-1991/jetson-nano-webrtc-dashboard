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

function buildTimeTicks(history, width, leftPad = 0, rightPad = 0, tickMinutes = 30) {
  if (!history || history.length < 2) return []

  const plotWidth = Math.max(width - leftPad - rightPad, 1)
  const firstTs = new Date(history[0].timestamp).getTime()
  const lastTs = new Date(history[history.length - 1].timestamp).getTime()

  if (!Number.isFinite(firstTs) || !Number.isFinite(lastTs) || lastTs <= firstTs) {
    return []
  }

  const tickMs = tickMinutes * 60 * 1000
  const start = Math.ceil(firstTs / tickMs) * tickMs
  const ticks = []

  for (let ts = start; ts <= lastTs; ts += tickMs) {
    const ratio = (ts - firstTs) / (lastTs - firstTs)
    const x = leftPad + ratio * plotWidth
    const dt = new Date(ts)
    ticks.push({
      x,
      timeLabel: dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      dateLabel: dt.toLocaleDateString([], { day: '2-digit', month: 'short' }),
    })
  }

  if (ticks.length === 0) {
    const dt = new Date(lastTs)
    ticks.push({
      x: leftPad + plotWidth,
      timeLabel: dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      dateLabel: dt.toLocaleDateString([], { day: '2-digit', month: 'short' }),
    })
  }

  return ticks
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

  useEffect(() => {
    let mounted = true

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
          setRealtimeHistory((prev) => {
            const next = [...prev, latestSensors]
            return next.slice(-180)
          })
        }

        if (!isRealtimeMode) {
          const historyResponse = await sensorAPI.getHistory({
            limit: 500,
            intervalMinutes: historyIntervalMinutes,
            hours: historyHours,
          })
          setHistory(Array.isArray(historyResponse.data?.history) ? historyResponse.data.history : [])
        }

        setError(null)
      } catch (err) {
        if (!mounted) return
        console.error('Failed to fetch sensor data:', err)
        setError('Unable to load sensor data')
      }
    }

    fetchSensorData()
    const interval = setInterval(fetchSensorData, 2000)

    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [historyIntervalMinutes, historyHours, isRealtimeMode])

  const displayedHistory = isRealtimeMode ? realtimeHistory : history

  const chartMeta = useMemo(() => {
    const values = displayedHistory
      .map((item) => item?.[activeTab])
      .filter((v) => typeof v === 'number')

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
  }, [displayedHistory, activeTab])

  const activeSeries = SERIES.find((s) => s.key === activeTab) || SERIES[0]
  const graphWidth = 560
  const graphHeight = 180
  const graphLeftPad = 8
  const graphRightPad = 8
  const timeTicks = useMemo(
    () => buildTimeTicks(displayedHistory, graphWidth, graphLeftPad, graphRightPad, 30),
    [displayedHistory]
  )

  const yTicks = useMemo(() => {
    const steps = 5
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
  }, [chartMeta.maxY, chartMeta.minY])

  const handleSimulationToggle = async () => {
    const target = !isSimulationEnabled
    try {
      setIsUpdatingSimulation(true)
      await sensorAPI.setSimulationMode(target)
      setIsSimulationEnabled(target)
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

        <div className="sensor-last-updated">
          Last updated: <strong>{formatDateTime(lastUpdated)}</strong>
        </div>
      </section>

      <section className="sensor-card graph-card">
        <h2>Graph</h2>

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
          {displayedHistory.length === 0 ? (
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
                    displayedHistory,
                    activeSeries.key,
                    graphWidth,
                    graphHeight,
                    chartMeta.minY,
                    chartMeta.maxY,
                    graphLeftPad,
                    graphRightPad,
                  )}
                />

                {displayedHistory.length === 1 && (
                  <circle
                    cx={graphWidth / 2}
                    cy={graphHeight / 2}
                    r="5"
                    fill={activeSeries.color}
                  />
                )}
              </svg>

              <div className="graph-axis-x">
                <span className="axis-title">X-Axis: Time (mins/hr, 30 min ticks with day/date)</span>
                <div className="axis-ticks">
                  {timeTicks.map((tick, idx) => (
                    <span key={`${tick.timeLabel}-${tick.dateLabel}-${idx}`} className="axis-tick">
                      <span>{tick.timeLabel}</span>
                      <small>{tick.dateLabel}</small>
                    </span>
                  ))}
                </div>
              </div>

              <div className="graph-axis-y">
                Y-Axis: Temperature (°C) — {activeSeries.label}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}

export default SensorDataSection

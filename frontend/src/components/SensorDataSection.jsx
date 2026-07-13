import React, { useEffect, useMemo, useState } from 'react'
import { sensorAPI } from '../services/api'
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
  const [activeTab, setActiveTab] = useState(SERIES[0].key)
  const [historyIntervalMinutes, setHistoryIntervalMinutes] = useState(5)
  const [historyHours, setHistoryHours] = useState(24)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true

    const fetchSensorData = async () => {
      try {
        const [latestResponse, historyResponse] = await Promise.all([
          sensorAPI.getLatest(),
          sensorAPI.getHistory({
            limit: 500,
            intervalMinutes: historyIntervalMinutes,
            hours: historyHours,
          }),
        ])

        if (!mounted) return

        setLatest(latestResponse.data?.sensors || null)
        setHistory(Array.isArray(historyResponse.data?.history) ? historyResponse.data.history : [])
        setLastUpdated(latestResponse.data?.sensors?.timestamp || latestResponse.data?.timestamp || null)
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
  }, [historyIntervalMinutes, historyHours])

  const chartMeta = useMemo(() => {
    const values = history
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
  }, [history, activeTab])

  const activeSeries = SERIES.find((s) => s.key === activeTab) || SERIES[0]
  const graphWidth = 560
  const graphHeight = 180
  const graphLeftPad = 8
  const graphRightPad = 8
  const timeTicks = useMemo(
    () => buildTimeTicks(history, graphWidth, graphLeftPad, graphRightPad, 30),
    [history]
  )

  return (
    <div className="sensor-row-grid">
      <section className="sensor-card reading-card">
        <h2>Sensor Data Reading</h2>

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
          {history.length < 2 ? (
            <div className="graph-empty">Waiting for sensor samples…</div>
          ) : (
            <>
              <svg viewBox={`0 0 ${graphWidth} ${graphHeight}`} className="sensor-graph" preserveAspectRatio="none">
                <line x1={graphLeftPad} y1={graphHeight} x2={graphWidth - graphRightPad} y2={graphHeight} className="axis-line" />

                <polyline
                  fill="none"
                  stroke={activeSeries.color}
                  strokeWidth="3"
                  points={buildPolyline(
                    history,
                    activeSeries.key,
                    graphWidth,
                    graphHeight,
                    chartMeta.minY,
                    chartMeta.maxY,
                    graphLeftPad,
                    graphRightPad,
                  )}
                />
              </svg>

              <div className="graph-axis-x">
                <span className="axis-title">X-Axis: Time (30 min ticks, day/date)</span>
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
                Y-Axis: Reading ({activeSeries.label})
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}

export default SensorDataSection

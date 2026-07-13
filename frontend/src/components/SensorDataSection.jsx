import React, { useEffect, useMemo, useState } from 'react'
import { sensorAPI } from '../services/api'
import './SensorDataSection.css'

const SERIES = [
  { key: 'hot_zone_temperature', label: 'Hot Zone Temperature', color: '#ef4444' },
  { key: 'cold_zone_temperature', label: 'Cold Zone Temperature', color: '#3b82f6' },
  { key: 'exhaust_temp', label: 'Exaust Temp', color: '#f59e0b' },
]

function formatValue(value) {
  if (typeof value !== 'number') return '--'
  return `${value.toFixed(1)} °C`
}

function buildPolyline(history, key, width, height, minY, maxY) {
  if (!history || history.length < 2) return ''
  const xStep = width / Math.max(history.length - 1, 1)
  const yRange = Math.max(maxY - minY, 1)

  return history
    .map((item, index) => {
      const x = index * xStep
      const yValue = typeof item[key] === 'number' ? item[key] : minY
      const y = height - ((yValue - minY) / yRange) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

export const SensorDataSection = () => {
  const [latest, setLatest] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true

    const fetchSensorData = async () => {
      try {
        const [latestResponse, historyResponse] = await Promise.all([
          sensorAPI.getLatest(),
          sensorAPI.getHistory(90),
        ])

        if (!mounted) return

        setLatest(latestResponse.data?.sensors || null)
        setHistory(Array.isArray(historyResponse.data?.history) ? historyResponse.data.history : [])
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
  }, [])

  const chartMeta = useMemo(() => {
    const values = history.flatMap((item) =>
      SERIES.map((series) => item?.[series.key]).filter((v) => typeof v === 'number')
    )

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
  }, [history])

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
      </section>

      <section className="sensor-card graph-card">
        <h2>Graph</h2>

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
            <svg viewBox="0 0 600 220" className="sensor-graph" preserveAspectRatio="none">
              <line x1="0" y1="220" x2="600" y2="220" className="axis-line" />
              <line x1="0" y1="0" x2="0" y2="220" className="axis-line" />

              {SERIES.map((series) => (
                <polyline
                  key={series.key}
                  fill="none"
                  stroke={series.color}
                  strokeWidth="3"
                  points={buildPolyline(history, series.key, 600, 220, chartMeta.minY, chartMeta.maxY)}
                />
              ))}
            </svg>
          )}
        </div>
      </section>
    </div>
  )
}

export default SensorDataSection

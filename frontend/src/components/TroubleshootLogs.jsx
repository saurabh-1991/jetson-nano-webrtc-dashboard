import React, { useEffect, useMemo, useState } from 'react'
import { eventsAPI } from '../services/api'
import './TroubleshootLogs.css'

const MAX_RENDERED_EVENTS = 120

function formatTs(iso, ts) {
  if (iso) {
    try {
      return new Date(iso).toLocaleTimeString()
    } catch (_e) {
      return '--'
    }
  }
  if (typeof ts === 'number') {
    try {
      return new Date(ts * 1000).toLocaleTimeString()
    } catch (_e) {
      return '--'
    }
  }
  return '--'
}

function buildDisplayMessage(event) {
  const payload = event?.payload || {}
  if (payload?.message) {
    return payload.message
  }

  if (payload?.method && payload?.path) {
    const statusText = typeof payload?.status === 'number' ? ` -> ${payload.status}` : ''
    const durationText = typeof payload?.duration_ms === 'number' ? ` in ${payload.duration_ms} ms` : ''
    return `${payload.method} ${payload.path}${statusText}${durationText}`
  }

  if (payload?.error) {
    return String(payload.error)
  }

  return '--'
}

function buildDetailText(event) {
  const payload = event?.payload || {}
  const details = []

  if (payload?.client_host) details.push(`client=${payload.client_host}`)
  if (typeof payload?.status === 'number') details.push(`status=${payload.status}`)
  if (typeof payload?.duration_ms === 'number') details.push(`duration=${payload.duration_ms}ms`)
  if (payload?.output) details.push(`output=${payload.output}`)
  if (typeof payload?.result === 'boolean') details.push(`result=${payload.result ? 'success' : 'failed'}`)
  if (payload?.error) details.push(`error=${payload.error}`)

  return details.join(' | ')
}

export const TroubleshootLogs = ({ enabled }) => {
  const [events, setEvents] = useState([])
  const [meta, setMeta] = useState(null)
  const [safety, setSafety] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!enabled) {
      return undefined
    }

    let mounted = true

    const fetchRecent = async () => {
      try {
        if (!mounted) return
        setLoading((prev) => prev || events.length === 0)

        const response = await eventsAPI.getRecent()
        if (!mounted) return

        const payload = response?.data || {}
        const nextEvents = Array.isArray(payload?.events) ? payload.events : []

        setEvents(nextEvents)
        setMeta(payload?.meta || null)
        setSafety(payload?.safety || null)
        setError(null)
      } catch (err) {
        if (!mounted) return
        console.error('Failed to fetch troubleshooting logs:', err)
        setError('Failed to fetch troubleshooting logs')
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    fetchRecent()
    const interval = setInterval(fetchRecent, 3000)

    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [enabled])

  const displayedEvents = useMemo(() => {
    return [...events].reverse().slice(0, MAX_RENDERED_EVENTS)
  }, [events])

  const buildTimestampToken = () => {
    const now = new Date()
    const pad = (v) => String(v).padStart(2, '0')
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  }

  const downloadLogsTxt = () => {
    const generatedAt = new Date().toISOString()
    const lines = []

    lines.push('Jetson Nano Dashboard - Troubleshooting Logs')
    lines.push(`Generated At: ${generatedAt}`)
    lines.push(`Retention Seconds: ${meta?.retention_seconds ?? 120}`)
    lines.push(`In-memory Events: ${meta?.in_memory_events ?? events.length}`)
    lines.push(`Safety Reset Count: ${safety?.safety_reset_count ?? 0}`)
    lines.push(`Heartbeat Age Seconds: ${safety?.last_frontend_heartbeat_age_seconds ?? 'NA'}`)
    lines.push('')
    lines.push('Events:')

    const entries = [...events].reverse()
    if (entries.length === 0) {
      lines.push('[no events in current window]')
    } else {
      entries.forEach((event, idx) => {
        const eventTime = event?.iso || formatTs(null, event?.ts)
        const source = event?.source || '--'
        const type = event?.type || '--'
        const severity = event?.severity || 'info'
        const message = event?.payload?.message || '--'
        const metaStr = JSON.stringify(event?.payload?.meta || {})
        lines.push(`${idx + 1}. [${eventTime}] [${severity}] [${source}] [${type}] ${message} meta=${metaStr}`)
      })
    }

    const fileName = `jetson_troubleshoot_logs_${buildTimestampToken()}.txt`
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
    const blobUrl = URL.createObjectURL(blob)

    const link = document.createElement('a')
    link.href = blobUrl
    link.download = fileName
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    URL.revokeObjectURL(blobUrl)
  }

  if (!enabled) {
    return null
  }

  return (
    <section className="logs-panel" aria-live="polite">
      <div className="logs-panel-header">
        <h3>Troubleshooting Logs (Last 2 Minutes)</h3>
        <div className="logs-header-actions">
          {loading && <span className="logs-panel-badge">Loading…</span>}
          <button type="button" className="download-logs-btn" onClick={downloadLogsTxt}>
            Download Logs (.txt)
          </button>
        </div>
      </div>

      <div className="logs-meta-row">
        <span className="logs-chip">Events: {meta?.in_memory_events ?? events.length}</span>
        <span className="logs-chip">Retention: {meta?.retention_seconds ?? 120}s</span>
        <span className="logs-chip">Safety resets: {safety?.safety_reset_count ?? 0}</span>
        <span className="logs-chip">HB age: {safety?.last_frontend_heartbeat_age_seconds ?? 'NA'}s</span>
      </div>

      {error && <div className="logs-error">{error}</div>}

      <div className="logs-table-wrap">
        {displayedEvents.length === 0 ? (
          <div className="logs-empty">No events captured yet.</div>
        ) : (
          <table className="logs-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Source</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {displayedEvents.map((event, idx) => (
                <tr key={`${event?.ts || event?.iso || 'na'}-${idx}`}>
                  <td>{formatTs(event?.iso, event?.ts)}</td>
                  <td>{event?.source || '--'}</td>
                  <td>{event?.type || '--'}</td>
                  <td>
                    <span className={`sev-pill ${event?.severity || 'info'}`}>
                      {event?.severity || 'info'}
                    </span>
                  </td>
                  <td>
                    <div className="log-message-main">{buildDisplayMessage(event)}</div>
                    {buildDetailText(event) && (
                      <div className="log-message-detail">{buildDetailText(event)}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

export default TroubleshootLogs

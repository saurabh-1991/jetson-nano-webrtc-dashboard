import React, { useEffect, useMemo, useRef, useState } from 'react'
import { cameraAPI, experimentsAPI } from '../services/api'
import { getApiCooldownState } from '../services/api'
import './ExperimentControl.css'

const EXPERIMENT_REQUEST_TIMEOUT_MS = 9000

function getNextPollDelayMs({ failedCount, totalCount, failureStreak }) {
  if (failedCount <= 0) return 6000
  if (failedCount < totalCount) return 10000
  const streak = Math.max(1, Number(failureStreak || 1))
  return Math.min(30000, 12000 + (streak * 2000))
}

function formatTimestamp(value) {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString()
  } catch (_e) {
    return '--'
  }
}

function formatDuration(seconds) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds < 0) {
    return '--'
  }

  const total = Math.floor(seconds)
  const hrs = Math.floor(total / 3600)
  const mins = Math.floor((total % 3600) / 60)
  const secs = total % 60

  if (hrs > 0) {
    return `${hrs}h ${mins}m ${secs}s`
  }
  if (mins > 0) {
    return `${mins}m ${secs}s`
  }
  return `${secs}s`
}

function formatGiB(bytes) {
  const num = Number(bytes)
  if (!Number.isFinite(num) || num < 0) return '--'
  return `${(num / (1024 ** 3)).toFixed(2)} GB`
}

function pickCameraMp4Path(files, cameraId, manifest = null) {
  const cameraKey = String(cameraId || '').toLowerCase()
  if (!cameraKey) return ''

  const manifestSegments = Array.isArray(manifest?.video?.[cameraKey]?.segments)
    ? manifest.video[cameraKey].segments
    : []

  const fromManifest = manifestSegments
    .map((seg) => seg?.path || seg?.relative_path)
    .find((rel) => typeof rel === 'string' && rel.toLowerCase().endsWith('.mp4'))

  if (fromManifest) {
    return fromManifest
  }

  const directManifestPath = manifest?.video?.[cameraKey]?.latest_path || manifest?.video?.[cameraKey]?.path
  if (typeof directManifestPath === 'string' && directManifestPath.toLowerCase().endsWith('.mp4')) {
    return directManifestPath
  }

  const cameraPattern = new RegExp(`(^|[\\/_.-])${cameraKey}([\\/_.-]|$)`, 'i')

  const matched = (Array.isArray(files) ? files : [])
    .map((item) => item?.relative_path)
    .filter((rel) => typeof rel === 'string' && rel.toLowerCase().endsWith('.mp4'))
    .filter((rel) => cameraPattern.test(rel))
    .sort()

  return matched[0] || ''
}

export const ExperimentControl = ({
  title = 'Experiment Control',
  showHistory = true,
  showPlayback = true,
  compact = false,
  onRunStarted = null,
}) => {
  const [storage, setStorage] = useState(null)
  const [storageHealth, setStorageHealth] = useState(null)
  const [active, setActive] = useState({ active: false, run: null })
  const [history, setHistory] = useState([])
  const [playbackRunId, setPlaybackRunId] = useState('')
  const [playbackCam1Url, setPlaybackCam1Url] = useState('')
  const [playbackCam2Url, setPlaybackCam2Url] = useState('')
  const [playbackCam1RawUrl, setPlaybackCam1RawUrl] = useState('')
  const [playbackCam2RawUrl, setPlaybackCam2RawUrl] = useState('')
  const [playbackCam1UsingRawFallback, setPlaybackCam1UsingRawFallback] = useState(false)
  const [playbackCam2UsingRawFallback, setPlaybackCam2UsingRawFallback] = useState(false)
  const [playbackCam1Label, setPlaybackCam1Label] = useState('')
  const [playbackCam2Label, setPlaybackCam2Label] = useState('')
  const [playbackCam1Error, setPlaybackCam1Error] = useState('')
  const [playbackCam2Error, setPlaybackCam2Error] = useState('')
  const [artifactLoadingRunId, setArtifactLoadingRunId] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [isRunningCleanup, setIsRunningCleanup] = useState(false)
  const [deletingRunId, setDeletingRunId] = useState('')
  const [infoMessage, setInfoMessage] = useState('')
  const [consecutiveFailures, setConsecutiveFailures] = useState(0)
  const [lastSuccessfulRefreshAt, setLastSuccessfulRefreshAt] = useState(null)
  const [error, setError] = useState(null)
  const [runName, setRunName] = useState('')
  const [operator, setOperator] = useState('')
  const [site, setSite] = useState('')
  const [tags, setTags] = useState('')
  const [historyExpanded, setHistoryExpanded] = useState(!compact)
  const refreshInFlightRef = useRef(false)

  const loadData = async ({ initial = false } = {}) => {
    if (refreshInFlightRef.current) {
      return { failedCount: 0, totalCount: 0, failureStreak: consecutiveFailures, skipped: true }
    }

    const cooldown = getApiCooldownState()
    if (cooldown.active) {
      return {
        failedCount: 4,
        totalCount: 4,
        failureStreak: Math.max(1, Number(consecutiveFailures || 0)),
        skipped: true,
        cooldownRemainingMs: cooldown.remainingMs,
      }
    }

    try {
      refreshInFlightRef.current = true
      if (initial) {
        setIsLoading(true)
      } else {
        setIsRefreshing(true)
      }

      const requestConfig = { timeout: EXPERIMENT_REQUEST_TIMEOUT_MS }

      const [storageRes, healthRes, activeRes, historyRes] = await Promise.allSettled([
        experimentsAPI.getStorage(requestConfig),
        experimentsAPI.getStorageHealth(requestConfig),
        experimentsAPI.getActive(requestConfig),
        experimentsAPI.getHistory(25, requestConfig),
      ])

      if (storageRes.status === 'fulfilled') {
        setStorage(storageRes.value?.data || null)
      }

      if (healthRes.status === 'fulfilled') {
        setStorageHealth(healthRes.value?.data || null)
      }

      if (activeRes.status === 'fulfilled') {
        setActive(activeRes.value?.data || { active: false, run: null })
      }

      if (historyRes.status === 'fulfilled') {
        setHistory(Array.isArray(historyRes.value?.data?.runs) ? historyRes.value.data.runs : [])
      }

      const results = [storageRes, healthRes, activeRes, historyRes]
      const failedCount = results.filter((r) => r.status === 'rejected').length
      const totalCount = results.length

      let failureStreak = 0
      setConsecutiveFailures((prev) => {
        failureStreak = failedCount === 0 ? 0 : prev + 1
        return failureStreak
      })

      if (failedCount === 0) {
        setLastSuccessfulRefreshAt(new Date().toISOString())
        setError(null)
      } else if (failedCount === totalCount && failureStreak >= 2) {
        setError('Connection unstable. Showing last known run data and retrying automatically.')
      } else if (failureStreak >= 3) {
        setError('Partial refresh detected repeatedly. Showing last known values where needed.')
      }

      return {
        failedCount,
        totalCount,
        failureStreak,
        skipped: false,
      }
    } catch (_e) {
      let failureStreak = 0
      setConsecutiveFailures((prev) => {
        failureStreak = prev + 1
        return failureStreak
      })
      if (failureStreak >= 2) {
        setError('Failed to refresh run control data. Retrying with backoff...')
      }
      return {
        failedCount: 4,
        totalCount: 4,
        failureStreak,
        skipped: false,
      }
    } finally {
      refreshInFlightRef.current = false
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    let mounted = true
    let timer = null

    const tick = async () => {
      if (!mounted) return
      const result = await loadData({ initial: false })
      if (!mounted) return

      const delay = result?.skipped
        ? Math.max(3000, Number(result?.cooldownRemainingMs || 0) + 300)
        : getNextPollDelayMs({
          failedCount: result?.failedCount ?? 0,
          totalCount: result?.totalCount ?? 4,
          failureStreak: result?.failureStreak ?? 0,
        })

      timer = setTimeout(tick, delay)
    }

    loadData({ initial: true }).then(() => {
      if (mounted) {
        timer = setTimeout(tick, 6000)
      }
    })

    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  const activeRun = active?.run || null
  const preferredMounted = !!storage?.preferred_mounted
  const selectedTier = storage?.selected_tier || '--'
  const diskFreeBytes = storageHealth?.disk?.free_bytes
  const diskUsedBytes = storageHealth?.disk?.used_bytes
  const runsTotalBytes = storageHealth?.runs?.total_size_bytes
  const hasDegradedSync = consecutiveFailures >= 2

  const handleRunCleanup = async () => {
    try {
      setIsRunningCleanup(true)
      setError(null)
      setInfoMessage('')
      const response = await experimentsAPI.runStorageCleanup({})
      const removedRuns = Number(response?.data?.storage?.removed_count || 0)
      const reclaimedBytes = Number(response?.data?.storage?.reclaimed_bytes || 0)
      const reclaimedMb = (reclaimedBytes / (1024 * 1024)).toFixed(2)
      setInfoMessage(`Cleanup completed: removed ${removedRuns} run(s), reclaimed ${reclaimedMb} MB.`)
      await loadData({ initial: false })
    } catch (cleanupErr) {
      const detail = cleanupErr?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to run storage cleanup')
    } finally {
      setIsRunningCleanup(false)
    }
  }

  const handleDeleteRun = async (runId) => {
    if (!runId) return

    const confirmed = window.confirm(
      `Delete experiment ${runId}? This permanently removes sensor/video artifacts and cannot be undone.`
    )
    if (!confirmed) return

    try {
      setDeletingRunId(runId)
      setError(null)
      setInfoMessage('')
      const response = await experimentsAPI.deleteRun(runId)
      const reclaimedBytes = Number(response?.data?.reclaimed_bytes || 0)
      const reclaimedMb = (reclaimedBytes / (1024 * 1024)).toFixed(2)
      setInfoMessage(`Deleted ${runId}. Reclaimed ${reclaimedMb} MB.`)
      await loadData({ initial: false })
    } catch (deleteErr) {
      const detail = deleteErr?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to delete experiment run')
    } finally {
      setDeletingRunId('')
    }
  }

  const elapsed = useMemo(() => {
    if (!activeRun?.started_at) return '--'
    const started = new Date(activeRun.started_at).getTime()
    if (Number.isNaN(started)) return '--'
    const now = Date.now()
    const delta = Math.max(0, Math.floor((now - started) / 1000))
    return formatDuration(delta)
  }, [activeRun?.started_at, isRefreshing])

  const handleStart = async () => {
    try {
      setIsStarting(true)
      setError(null)

      // Keep camera controls responsive immediately when Start Run is pressed.
      // This lets operators use Start Cam 1 / Start Cam 2 without waiting on
      // experiment API latency.
      if (typeof onRunStarted === 'function') {
        onRunStarted()
      }

      const tagList = String(tags || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)

      await experimentsAPI.start({
        run_name: runName || undefined,
        operator: operator || undefined,
        site: site || undefined,
        tags: tagList,
      })

      // Best-effort warmup after successful start. Backend now skips prewarm
      // for cameras that already have active MJPEG clients.
      cameraAPI.prewarm(['cam1', 'cam2'], { timeout: 5000 }).catch(() => {})

      await loadData({ initial: false })
      setRunName('')
      setTags('')
    } catch (startErr) {
      const detail = startErr?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to start run')
    } finally {
      setIsStarting(false)
    }
  }

  const handleStop = async () => {
    try {
      setIsStopping(true)
      setError(null)
      await experimentsAPI.stop({ reason: 'operator_stop' })
      await loadData({ initial: false })
    } catch (stopErr) {
      const detail = stopErr?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to stop run')
    } finally {
      setIsStopping(false)
    }
  }

  const handleDownload = (runId) => {
    if (!runId) return
    const url = experimentsAPI.getDownloadUrl(runId)
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  const handlePlayback = async (runId) => {
    if (!runId) return
    try {
      setArtifactLoadingRunId(runId)
      setError(null)
      const artifacts = await experimentsAPI.getArtifacts(runId)
      const files = Array.isArray(artifacts?.data?.files) ? artifacts.data.files : []
      const manifest = artifacts?.data?.manifest || null
      const mp4Files = files
        .map((item) => item?.relative_path)
        .filter((rel) => typeof rel === 'string' && rel.toLowerCase().endsWith('.mp4'))

      if (mp4Files.length === 0) {
        setError('No MP4 video found for this run yet.')
        setPlaybackRunId('')
        setPlaybackCam1Url('')
        setPlaybackCam2Url('')
        setPlaybackCam1RawUrl('')
        setPlaybackCam2RawUrl('')
        setPlaybackCam1UsingRawFallback(false)
        setPlaybackCam2UsingRawFallback(false)
        setPlaybackCam1Label('')
        setPlaybackCam2Label('')
        setPlaybackCam1Error('')
        setPlaybackCam2Error('')
        return
      }

      const cam1Path = pickCameraMp4Path(files, 'cam1', manifest)
      const cam2Path = pickCameraMp4Path(files, 'cam2', manifest)
      const nonce = Date.now()

      setPlaybackRunId(runId)
      setPlaybackCam1UsingRawFallback(false)
      setPlaybackCam2UsingRawFallback(false)
      setPlaybackCam1Error('')
      setPlaybackCam2Error('')
      if (cam1Path) {
        const playable = `${experimentsAPI.getPlayableMediaUrl(runId, cam1Path)}&v=${nonce}`
        const raw = `${experimentsAPI.getMediaUrl(runId, cam1Path)}&v=${nonce}`
        setPlaybackCam1Url(playable)
        setPlaybackCam1RawUrl(raw)
        setPlaybackCam1Label(cam1Path)
      } else {
        setPlaybackCam1Url('')
        setPlaybackCam1RawUrl('')
        setPlaybackCam1Label('')
      }

      if (cam2Path) {
        const playable = `${experimentsAPI.getPlayableMediaUrl(runId, cam2Path)}&v=${nonce}`
        const raw = `${experimentsAPI.getMediaUrl(runId, cam2Path)}&v=${nonce}`
        setPlaybackCam2Url(playable)
        setPlaybackCam2RawUrl(raw)
        setPlaybackCam2Label(cam2Path)
      } else {
        setPlaybackCam2Url('')
        setPlaybackCam2RawUrl('')
        setPlaybackCam2Label('')
      }
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to load playback artifacts')
      setPlaybackRunId('')
      setPlaybackCam1Url('')
      setPlaybackCam2Url('')
      setPlaybackCam1RawUrl('')
      setPlaybackCam2RawUrl('')
      setPlaybackCam1UsingRawFallback(false)
      setPlaybackCam2UsingRawFallback(false)
      setPlaybackCam1Label('')
      setPlaybackCam2Label('')
      setPlaybackCam1Error('')
      setPlaybackCam2Error('')
    } finally {
      setArtifactLoadingRunId('')
    }
  }

  const handleCam1PlaybackError = () => {
    if (!playbackCam1UsingRawFallback && playbackCam1RawUrl) {
      setPlaybackCam1UsingRawFallback(true)
      setPlaybackCam1Error('Primary playback failed, switched to raw stream fallback.')
      setPlaybackCam1Url(`${playbackCam1RawUrl}${playbackCam1RawUrl.includes('?') ? '&' : '?'}fallback=1`)
      return
    }

    setPlaybackCam1Error('Cam 1 playback failed. Use Download to verify artifact file directly.')
  }

  const handleCam1PlaybackLoaded = () => {
    setPlaybackCam1Error('')
  }

  const handleCam2PlaybackError = () => {
    if (!playbackCam2UsingRawFallback && playbackCam2RawUrl) {
      setPlaybackCam2UsingRawFallback(true)
      setPlaybackCam2Error('Primary playback failed, switched to raw stream fallback.')
      setPlaybackCam2Url(`${playbackCam2RawUrl}${playbackCam2RawUrl.includes('?') ? '&' : '?'}fallback=1`)
      return
    }

    setPlaybackCam2Error('Cam 2 playback failed. Use Download to verify artifact file directly.')
  }

  const handleCam2PlaybackLoaded = () => {
    setPlaybackCam2Error('')
  }

  return (
    <div className={`experiment-control-container ${compact ? 'compact' : ''}`}>
      <div className="experiment-control-header">
        <h2>{title}</h2>
        <span className={`refresh-pill ${isRefreshing ? 'active' : ''} ${hasDegradedSync ? 'warn' : ''}`}>
          <span className="refresh-pill-dot" aria-hidden="true" />
          Auto-refresh
        </span>
      </div>

      {isLoading ? (
        <div className="experiment-loading">Loading run controls…</div>
      ) : (
        <>
          <div className="storage-status-row">
            <span className={`storage-badge ${preferredMounted ? 'ok' : 'warn'}`}>
              USB Mount: {preferredMounted ? 'Available' : 'Not mounted'}
            </span>
            <span className="storage-meta">Active storage: {selectedTier}</span>
            <span className="storage-meta">Free: {formatGiB(diskFreeBytes)}</span>
            <span className="storage-meta">Used: {formatGiB(diskUsedBytes)}</span>
            <span className="storage-meta">Runs: {formatGiB(runsTotalBytes)}</span>
            {lastSuccessfulRefreshAt && (
              <span className="storage-meta">Last sync: {formatTimestamp(lastSuccessfulRefreshAt)}</span>
            )}
          </div>

          {hasDegradedSync && (
            <div className="sync-warning-banner">
              Network jitter detected. Data may be slightly stale; retries are running with backoff.
            </div>
          )}

          <div className="control-form-grid">
            <label>
              Run Name
              <input
                type="text"
                value={runName}
                onChange={(e) => setRunName(e.target.value)}
                placeholder="Optional"
                disabled={!!active?.active || isStarting || isStopping}
              />
            </label>

            <label>
              Operator
              <input
                type="text"
                value={operator}
                onChange={(e) => setOperator(e.target.value)}
                placeholder="Optional"
                disabled={!!active?.active || isStarting || isStopping}
              />
            </label>

            <label>
              Site
              <input
                type="text"
                value={site}
                onChange={(e) => setSite(e.target.value)}
                placeholder="Optional"
                disabled={!!active?.active || isStarting || isStopping}
              />
            </label>

            <label>
              Tags (comma separated)
              <input
                type="text"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="test, batch-1"
                disabled={!!active?.active || isStarting || isStopping}
              />
            </label>
          </div>

          <div className="control-actions-row">
            {!active?.active ? (
              <button
                type="button"
                className="btn-run btn-start"
                onClick={handleStart}
                disabled={isStarting || isStopping}
              >
                {isStarting ? 'Starting…' : 'Start Run'}
              </button>
            ) : (
              <button
                type="button"
                className="btn-run btn-stop"
                onClick={handleStop}
                disabled={isStopping || isStarting}
              >
                {isStopping ? 'Stopping…' : 'Stop Run'}
              </button>
            )}

            <button
              type="button"
              className="btn-run btn-refresh"
              onClick={() => loadData({ initial: false })}
              disabled={isRefreshing || isStarting || isStopping || isRunningCleanup}
            >
              Refresh
            </button>

            <button
              type="button"
              className="btn-run btn-cleanup"
              onClick={handleRunCleanup}
              disabled={isRunningCleanup || isStarting || isStopping}
            >
              {isRunningCleanup ? 'Cleaning…' : 'Run Cleanup'}
            </button>
          </div>

          <div className="active-run-card">
            <h3>Current Run</h3>
            {!active?.active || !activeRun ? (
              <div className="muted">No active run</div>
            ) : (
              <div className="active-run-grid">
                <div><span className="k">ID:</span> <span className="v mono">{activeRun.run_id}</span></div>
                <div><span className="k">Name:</span> <span className="v">{activeRun.run_name || '--'}</span></div>
                <div><span className="k">Started:</span> <span className="v">{formatTimestamp(activeRun.started_at)}</span></div>
                <div><span className="k">Elapsed:</span> <span className="v">{elapsed}</span></div>
                <div><span className="k">Samples:</span> <span className="v">{Number(activeRun.sample_count || 0)}</span></div>
              </div>
            )}
          </div>

          {showHistory && (
            <div className="history-card">
              <button
                type="button"
                className="history-toggle"
                onClick={() => setHistoryExpanded((prev) => !prev)}
                aria-expanded={historyExpanded}
              >
                <h3>Recent Runs</h3>
                <span className="history-toggle-meta">
                  {history.length} total · {historyExpanded ? 'Hide' : 'Show'}
                </span>
              </button>

              {historyExpanded && (
                history.length === 0 ? (
                  <div className="muted">No runs yet</div>
                ) : (
                  <div className="history-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Run ID</th>
                          <th>Name</th>
                          <th>State</th>
                          <th>Duration</th>
                          <th>Samples</th>
                          <th>Started</th>
                          <th>Download</th>
                          <th>Delete</th>
                          {showPlayback && <th>Recorded View</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {history.slice(0, 8).map((item) => (
                          <tr key={item.run_id}>
                            <td className="mono">{item.run_id}</td>
                            <td>{item.run_name || '--'}</td>
                            <td>{item.state || '--'}</td>
                            <td>{formatDuration(Number(item.duration_seconds || 0))}</td>
                            <td>{Number(item.sample_count || 0)}</td>
                            <td>{formatTimestamp(item.started_at)}</td>
                            <td>
                              <button
                                type="button"
                                className="download-btn"
                                onClick={() => handleDownload(item.run_id)}
                              >
                                Download
                              </button>
                            </td>
                            <td>
                              <button
                                type="button"
                                className="download-btn delete-btn"
                                onClick={() => handleDeleteRun(item.run_id)}
                                disabled={deletingRunId === item.run_id || item.state === 'active' || !!active?.active && active?.run?.run_id === item.run_id}
                              >
                                {deletingRunId === item.run_id ? 'Deleting…' : 'Delete'}
                              </button>
                            </td>
                            {showPlayback && (
                              <td>
                                <button
                                  type="button"
                                  className="download-btn"
                                  onClick={() => handlePlayback(item.run_id)}
                                  disabled={artifactLoadingRunId === item.run_id}
                                >
                                  {artifactLoadingRunId === item.run_id ? 'Loading…' : 'Load'}
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              )}
            </div>
          )}

          {showPlayback && (
            <div className="history-card">
              <h3>Playback</h3>
              {!playbackRunId ? (
                <div className="muted">Select a run and click Load to review Cam1/Cam2 recordings.</div>
              ) : (
                <div className="playback-grid">
                  <div className="playback-cell">
                    <div className="playback-cell-title">Cam 1 Recording</div>
                    {playbackCam1Url ? (
                      <>
                        <div className="playback-label mono">{playbackRunId} / {playbackCam1Label}</div>
                        {playbackCam1UsingRawFallback && <div className="playback-note">Using raw fallback stream.</div>}
                        {playbackCam1Error && <div className="playback-note warn">{playbackCam1Error}</div>}
                        <video
                          className="playback-video"
                          controls
                          playsInline
                          preload="metadata"
                          src={playbackCam1Url}
                          onLoadedData={handleCam1PlaybackLoaded}
                          onError={handleCam1PlaybackError}
                        />
                      </>
                    ) : (
                      <div className="muted">No Cam 1 recording found in this run.</div>
                    )}
                  </div>

                  <div className="playback-cell">
                    <div className="playback-cell-title">Cam 2 Recording</div>
                    {playbackCam2Url ? (
                      <>
                        <div className="playback-label mono">{playbackRunId} / {playbackCam2Label}</div>
                        {playbackCam2UsingRawFallback && <div className="playback-note">Using raw fallback stream.</div>}
                        {playbackCam2Error && <div className="playback-note warn">{playbackCam2Error}</div>}
                        <video
                          className="playback-video"
                          controls
                          playsInline
                          preload="metadata"
                          src={playbackCam2Url}
                          onLoadedData={handleCam2PlaybackLoaded}
                          onError={handleCam2PlaybackError}
                        />
                      </>
                    ) : (
                      <div className="muted">No Cam 2 recording found in this run.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {infoMessage && <div className="experiment-info">{infoMessage}</div>}
          {error && <div className="experiment-error">{error}</div>}
        </>
      )}
    </div>
  )
}

export default ExperimentControl

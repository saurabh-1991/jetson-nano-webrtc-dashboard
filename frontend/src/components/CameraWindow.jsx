import React, { useEffect, useMemo, useState } from 'react'
import VideoStream from './VideoStream'
import { experimentsAPI } from '../services/api'
import './CameraWindow.css'

const REQUEST_TIMEOUT = 9000

function pickCameraVideoPath(files, cameraId, manifest = null) {
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

export default function CameraWindow({
  cameraId,
  title,
  enabled,
  startLabel,
  stopLabel,
  forceMjpeg = false,
  autoLiveSignal = 0,
  autoConnectDelayMs = 0,
}) {
  const [mode, setMode] = useState('live')
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [rawVideoUrl, setRawVideoUrl] = useState('')
  const [videoLabel, setVideoLabel] = useState('')
  const [isLoadingPlayback, setIsLoadingPlayback] = useState(false)
  const [usingRawFallback, setUsingRawFallback] = useState(false)
  const [error, setError] = useState('')

  const hasPlayback = useMemo(() => history.length > 0, [history])

  const resetPlaybackSelection = () => {
    setSelectedRunId('')
    setVideoUrl('')
    setRawVideoUrl('')
    setVideoLabel('')
    setUsingRawFallback(false)
  }

  const loadHistory = async () => {
    try {
      setHistoryLoading(true)
      setError('')
      const response = await experimentsAPI.getHistory(25, { timeout: REQUEST_TIMEOUT })
      const runs = Array.isArray(response?.data?.runs) ? response.data.runs : []
      setHistory(runs)
      if (runs.length > 0 && !selectedRunId) {
        setSelectedRunId(runs[0].run_id)
      }
    } catch (_err) {
      setError('Failed to fetch experiment runs for playback.')
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (mode === 'playback' && history.length === 0 && !historyLoading) {
      loadHistory()
    }
  }, [mode])

  useEffect(() => {
    if (!autoLiveSignal || !enabled) {
      return
    }

    setMode('live')
    setError('')
  }, [autoLiveSignal, enabled])

  const onToggleMode = (nextMode) => {
    setMode(nextMode)
    setError('')
    if (nextMode === 'live') {
      resetPlaybackSelection()
    }
  }

  const loadPlayback = async () => {
    if (!selectedRunId) {
      setError('Select a run first to load playback.')
      return
    }

    try {
      setIsLoadingPlayback(true)
      setError('')
      setUsingRawFallback(false)

      const artifacts = await experimentsAPI.getArtifacts(selectedRunId)
      const files = Array.isArray(artifacts?.data?.files) ? artifacts.data.files : []
      const manifest = artifacts?.data?.manifest || null
      const selectedPath = pickCameraVideoPath(files, cameraId, manifest)

      if (!selectedPath) {
        setError(`No ${cameraId.toUpperCase()} recording found in selected run.`)
        setVideoUrl('')
        setRawVideoUrl('')
        setVideoLabel('')
        return
      }

      const nonce = Date.now()
      const playable = `${experimentsAPI.getPlayableMediaUrl(selectedRunId, selectedPath)}&v=${nonce}`
      const raw = `${experimentsAPI.getMediaUrl(selectedRunId, selectedPath)}&v=${nonce}`

      setVideoUrl(playable)
      setRawVideoUrl(raw)
      setVideoLabel(`${selectedRunId} / ${selectedPath}`)
    } catch (_err) {
      setError('Failed to load playback artifact for selected run.')
      setVideoUrl('')
      setRawVideoUrl('')
      setVideoLabel('')
    } finally {
      setIsLoadingPlayback(false)
    }
  }

  const handlePlaybackError = () => {
    if (!usingRawFallback && rawVideoUrl) {
      setUsingRawFallback(true)
      setError('Primary playback failed. Switched to raw fallback stream.')
      setVideoUrl(`${rawVideoUrl}${rawVideoUrl.includes('?') ? '&' : '?'}fallback=1`)
      return
    }

    setError('Playback failed. Try another run or download artifact from Experiment Control.')
  }

  const handlePlaybackLoaded = () => {
    if (!usingRawFallback) {
      setError('')
    }
  }

  return (
    <div className="camera-window">
      <div className="camera-window-header">
        <h2>{title}</h2>
        <div className="camera-mode-toggle" role="group" aria-label={`${cameraId} mode toggle`}>
          <button
            type="button"
            className={`mode-btn ${mode === 'live' ? 'active' : ''}`}
            onClick={() => onToggleMode('live')}
          >
            Live
          </button>
          <button
            type="button"
            className={`mode-btn ${mode === 'playback' ? 'active' : ''}`}
            onClick={() => onToggleMode('playback')}
          >
            Playback
          </button>
        </div>
      </div>

      {mode === 'live' ? (
        enabled ? (
          <VideoStream
            cameraId={cameraId}
            startLabel={startLabel}
            stopLabel={stopLabel}
            forceMjpeg={forceMjpeg}
            preferHardwareH264={!forceMjpeg}
            autoConnectSignal={autoLiveSignal}
            autoConnectDelayMs={autoConnectDelayMs}
          />
        ) : (
          <div className="camera-unavailable">{cameraId.toUpperCase()} is disabled in backend configuration.</div>
        )
      ) : (
        <div className="camera-playback">
          <div className="camera-playback-controls">
            <select
              value={selectedRunId}
              onChange={(e) => setSelectedRunId(e.target.value)}
              disabled={historyLoading || !hasPlayback}
            >
              {!hasPlayback ? (
                <option value="">No runs available</option>
              ) : (
                history.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {run.run_id} · {run.run_name || run.state || 'run'}
                  </option>
                ))
              )}
            </select>

            <button
              type="button"
              className="load-playback-btn"
              onClick={loadPlayback}
              disabled={isLoadingPlayback || historyLoading || !hasPlayback || !selectedRunId}
            >
              {isLoadingPlayback ? 'Loading…' : 'Load'}
            </button>

            <button
              type="button"
              className="load-playback-btn secondary"
              onClick={loadHistory}
              disabled={historyLoading || isLoadingPlayback}
            >
              {historyLoading ? 'Refreshing…' : 'Refresh Runs'}
            </button>
          </div>

          {videoLabel && <div className="playback-source-label">{videoLabel}</div>}
          {usingRawFallback && <div className="playback-fallback-note">Using raw fallback stream.</div>}

          {videoUrl ? (
            <video
              className="playback-video"
              controls
              playsInline
              preload="metadata"
              src={videoUrl}
              onError={handlePlaybackError}
              onLoadedData={handlePlaybackLoaded}
            />
          ) : (
            <div className="playback-placeholder">
              {historyLoading ? 'Loading runs…' : 'Select a run and click Load to play back this camera.'}
            </div>
          )}
        </div>
      )}

      {error && <div className="camera-window-error">{error}</div>}
    </div>
  )
}

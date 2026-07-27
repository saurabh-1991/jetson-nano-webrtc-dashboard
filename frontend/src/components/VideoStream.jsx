import React, { useState, useEffect, useRef } from 'react'
import './VideoStream.css'

export const VideoStream = ({
  apiBaseUrl = '',
  cameraId = 'cam1',
  startLabel = 'Start Video',
  stopLabel = 'Stop Video',
  forceMjpeg = false,
}) => {
  const videoRef = useRef(null)
  const imgRef = useRef(null)
  const popoutRef = useRef(null)
  const streamSessionIdRef = useRef(
    (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`
  )
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [streamMode, setStreamMode] = useState('none') // none | webrtc | mjpeg
  const [mjpegUrl, setMjpegUrl] = useState('')
  const [liveStats, setLiveStats] = useState(null)
  const [statsError, setStatsError] = useState(false)
  const pcRef = useRef(null)
  const fallbackActiveRef = useRef(false)
  const mjpegRetryTimerRef = useRef(null)
  const mjpegRetryCountRef = useRef(0)

  const getBaseUrl = () => apiBaseUrl || (
    import.meta.env.DEV
      ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
      : ''
  )

  const closePeerConnection = () => {
    if (pcRef.current) {
      pcRef.current.close()
      pcRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  const clearMjpegRetryTimer = () => {
    if (mjpegRetryTimerRef.current) {
      clearTimeout(mjpegRetryTimerRef.current)
      mjpegRetryTimerRef.current = null
    }
  }

  const startMJPEGFallback = (baseUrl, reason) => {
    fallbackActiveRef.current = true
    closePeerConnection()
    clearMjpegRetryTimer()

    setNotice(reason || 'Using MJPEG fallback stream')
    setStreamMode('mjpeg')
    setConnectionState('connecting')
    setIsConnecting(true)
    setIsConnected(false)
    setError(null)

    // timestamp prevents stale browser cache
    setMjpegUrl(
      `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
    )
  }

  const connectStream = async () => {
    if (isConnected || isConnecting) {
      return
    }

    setIsConnecting(true)
    setError(null)
    setNotice(null)
    fallbackActiveRef.current = false
    clearMjpegRetryTimer()
    mjpegRetryCountRef.current = 0

    const baseUrl = getBaseUrl()
    let usedMjpegFallback = false

    try {
      if (forceMjpeg) {
        usedMjpegFallback = true
        startMJPEGFallback(baseUrl, 'Using MJPEG mode for this camera')
        return
      }

      setStreamMode('webrtc')

      // Create peer connection
      const config = {
        iceServers: [
          { urls: ['stun:stun.l.google.com:19302'] },
          { urls: ['stun:stun1.l.google.com:19302'] },
        ]
      }

      const pc = new RTCPeerConnection(config)
      pcRef.current = pc

      // Request remote video from the server
      pc.addTransceiver('video', { direction: 'recvonly' })

      // Handle incoming stream
      pc.ontrack = (event) => {
        if (event.streams && event.streams[0] && videoRef.current) {
          videoRef.current.srcObject = event.streams[0]
          setIsConnected(true)
          setIsConnecting(false)
          setStreamMode('webrtc')
          setNotice(null)
        }
      }

      // Handle connection state
      pc.onconnectionstatechange = () => {
        if (fallbackActiveRef.current) {
          return
        }

        setConnectionState(pc.connectionState)
        if (pc.connectionState === 'connected') {
          setIsConnected(true)
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          setIsConnected(false)
        }
      }

      // Create and send offer
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      const offerController = new AbortController()
      const offerTimeout = setTimeout(() => {
        try {
          offerController.abort()
        } catch (_e) {
          // no-op
        }
      }, 4500)

      let response
      try {
        response = await fetch(`${baseUrl}/api/webrtc/offer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: offerController.signal,
          body: JSON.stringify({
            sdp: offer.sdp,
            type: offer.type,
            camera_id: cameraId,
          })
        })
      } finally {
        clearTimeout(offerTimeout)
      }

      if (!response.ok) {
        if (response.status === 503) {
          usedMjpegFallback = true
          startMJPEGFallback(
            baseUrl,
            'WebRTC unavailable on Jetson build. Switched to MJPEG streaming.'
          )
          return
        }
        throw new Error(`Server returned ${response.status}`)
      }

      const answer = await response.json()
      await pc.setRemoteDescription(new RTCSessionDescription(answer))

      setIsConnected(true)
      setConnectionState('connected')
    } catch (err) {
      console.error('WebRTC connection error:', err)

      // Auto-fallback to MJPEG for runtime streaming continuity
      const fallbackReason = `WebRTC failed (${err.message || 'unknown error'}). Switched to MJPEG.`
      usedMjpegFallback = true
      startMJPEGFallback(baseUrl, fallbackReason)
    } finally {
      // For MJPEG fallback, keep connecting state until the image stream loads.
      if (!usedMjpegFallback) {
        setIsConnecting(false)
      }
    }
  }

  const disconnect = () => {
    const baseUrl = getBaseUrl()
    clearMjpegRetryTimer()
    fallbackActiveRef.current = false
    mjpegRetryCountRef.current = 0
    closePeerConnection()
    if (imgRef.current) {
      imgRef.current.src = ''
    }
    setMjpegUrl('')
    setStreamMode('none')
    setNotice(null)
    setError(null)
    setIsConnecting(false)
    setIsConnected(false)
    setConnectionState('disconnected')

    if (popoutRef.current && !popoutRef.current.closed) {
      popoutRef.current.close()
      popoutRef.current = null
    }

    // Best-effort camera release request. Backend releases only when no active viewers.
    fetch(`${baseUrl}/api/camera/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        camera_id: cameraId,
        stream_session_id: streamSessionIdRef.current
      })
    }).catch((err) => {
      console.warn('Camera stop request failed:', err)
    })
  }

  const openLargeView = () => {
    const baseUrl = getBaseUrl()
    const streamUrl = `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&t=${Date.now()}`
    const dashboardUrl = window.location.href

    const popup = window.open(
      '',
      'jetson_camera_popout',
      'width=1280,height=840,resizable=yes,scrollbars=no,noopener,noreferrer'
    )

    if (!popup) {
      // Fallback: use same-tab navigation when pop-ups are blocked.
      window.open(streamUrl, '_blank', 'noopener,noreferrer')
      return
    }

    popup.document.write(`
      <!doctype html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>Live Camera - Large View</title>
        <style>
          html, body { margin: 0; width: 100%; height: 100%; background: #000; font-family: Arial, sans-serif; }
          .toolbar {
            position: fixed;
            top: 12px;
            left: 12px;
            z-index: 10;
            display: inline-flex;
            gap: 8px;
            background: rgba(0, 0, 0, 0.45);
            padding: 8px;
            border-radius: 8px;
            opacity: 1;
            transition: opacity 0.2s ease;
          }
          .toolbar.hidden { opacity: 0; pointer-events: none; }
          .btn {
            border: 1px solid rgba(255,255,255,0.25);
            color: #fff;
            background: rgba(17, 24, 39, 0.85);
            border-radius: 6px;
            padding: 6px 10px;
            text-decoration: none;
            font-size: 13px;
            cursor: pointer;
          }
          .viewer {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          img {
            width: 100%;
            height: 100%;
            object-fit: contain;
          }
        </style>
      </head>
      <body>
        <div class="toolbar">
          <a class="btn" href="${dashboardUrl}">← Back to Dashboard</a>
          <button class="btn" onclick="window.close()">Close</button>
        </div>
        <div class="viewer">
          <img src="${streamUrl}" alt="Live Camera Stream" />
        </div>
        <script>
          (function () {
            const toolbar = document.querySelector('.toolbar');
            if (!toolbar) return;

            let hideTimer = null;

            function showToolbar() {
              toolbar.classList.remove('hidden');
              if (hideTimer) clearTimeout(hideTimer);
              hideTimer = setTimeout(() => {
                toolbar.classList.add('hidden');
              }, 2500);
            }

            document.addEventListener('mousemove', showToolbar, { passive: true });
            document.addEventListener('keydown', showToolbar);
            toolbar.addEventListener('mouseenter', () => {
              if (hideTimer) clearTimeout(hideTimer);
              toolbar.classList.remove('hidden');
            });
            toolbar.addEventListener('mouseleave', showToolbar);

            showToolbar();
          })();
        </script>
      </body>
      </html>
    `)
    popup.document.close()
    popup.focus()
    popoutRef.current = popup
  }

  const onMjpegLoaded = () => {
    clearMjpegRetryTimer()
    mjpegRetryCountRef.current = 0
    setIsConnected(true)
    setIsConnecting(false)
    setConnectionState('connected')
  }

  const onMjpegError = () => {
    const baseUrl = getBaseUrl()
    const nextAttempt = mjpegRetryCountRef.current + 1
    mjpegRetryCountRef.current = nextAttempt

    setIsConnected(false)
    setIsConnecting(true)
    setConnectionState('connecting')

    const retryDelayMs = Math.min(1500 * nextAttempt, 6000)
    setError(`MJPEG stream load failed, retrying (${nextAttempt})...`)

    clearMjpegRetryTimer()
    mjpegRetryTimerRef.current = setTimeout(() => {
      if (!fallbackActiveRef.current) {
        return
      }

      setMjpegUrl(
        `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
      )
    }, retryDelayMs)
  }

  const pollLiveStats = async () => {
    try {
      const baseUrl = getBaseUrl()
      const response = await fetch(`${baseUrl}/api/stats`, {
        cache: 'no-store'
      })
      if (!response.ok) {
        throw new Error(`stats ${response.status}`)
      }

      const stats = await response.json()
      const cameraStats = stats?.cameras?.[cameraId] || null
      setLiveStats({ ...stats, cameraScoped: cameraStats })
      setStatsError(false)
    } catch (err) {
      setStatsError(true)
    }
  }

  useEffect(() => {
    pollLiveStats()
    const timer = setInterval(() => {
      pollLiveStats()
    }, 2000)

    return () => {
      clearInterval(timer)
      clearMjpegRetryTimer()
      disconnect()
    }
  }, [])

  const mjpegViewers = Number(liveStats?.cameraScoped?.active_mjpeg_clients ?? 0)
  const webrtcViewers = Number(liveStats?.webrtc_connections || 0)
  const totalViewers = mjpegViewers + (forceMjpeg ? 0 : webrtcViewers)
  const cameraPerf = liveStats?.cameraScoped?.camera_performance || liveStats?.camera_performance || null
  const frameHitRatio = cameraPerf?.frame_cache?.hit_ratio
  const jpegHitRatio = cameraPerf?.jpeg_cache?.hit_ratio
  const avgEncodeMs = cameraPerf?.jpeg_encode?.avg_ms

  const toPct = (v) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : 'NA')
  const toMs = (v) => (typeof v === 'number' ? `${v.toFixed(2)} ms` : 'NA')

  return (
    <div className="video-stream-container">
      <div className="video-wrapper">
        {streamMode === 'mjpeg' ? (
          <img
            ref={imgRef}
            src={mjpegUrl}
            alt="MJPEG Stream"
            className="video-element"
            onLoad={onMjpegLoaded}
            onError={onMjpegError}
            style={{
              width: '100%',
              height: '100%',
              backgroundColor: '#000',
              borderRadius: '8px'
            }}
          />
        ) : (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            className="video-element"
            style={{
              width: '100%',
              height: '100%',
              backgroundColor: '#000',
              borderRadius: '8px'
            }}
          />
        )}

        {!isConnected && (
          <div className="video-placeholder">
            {isConnecting
              ? streamMode === 'mjpeg'
                ? 'Loading MJPEG stream...'
                : 'Connecting WebRTC...'
              : `Click "${startLabel}" to begin`}
          </div>
        )}
      </div>

      <div className="video-controls">
        {!isConnected ? (
          <button
            onClick={connectStream}
            disabled={isConnecting}
            className="btn btn-primary"
          >
            {isConnecting ? 'Connecting...' : startLabel}
          </button>
        ) : (
          <button
            onClick={disconnect}
            className="btn btn-danger"
          >
            {stopLabel}
          </button>
        )}

        <button
          onClick={openLargeView}
          className="btn btn-secondary"
        >
          Open Large View
        </button>
      </div>

      <div className="video-status">
        <div className={`status-indicator ${connectionState}`}></div>
        <span className="status-text">
          {connectionState.charAt(0).toUpperCase() + connectionState.slice(1)}
        </span>
        {streamMode !== 'none' && (
          <span className="stream-mode">
            Mode: {streamMode.toUpperCase()}
          </span>
        )}
      </div>

      <div className="video-live-metrics">
        <span className="metrics-chip metrics-chip-viewers">
          Viewers: {totalViewers}
        </span>
        <span className="metrics-chip">MJPEG: {mjpegViewers}</span>
        {!forceMjpeg && <span className="metrics-chip">WebRTC: {webrtcViewers}</span>}
        <span className="metrics-chip">Frame Cache: {toPct(frameHitRatio)}</span>
        <span className="metrics-chip">JPEG Cache: {toPct(jpegHitRatio)}</span>
        <span className="metrics-chip">Avg JPEG Encode: {toMs(avgEncodeMs)}</span>
        {statsError && (
          <span className="metrics-chip metrics-chip-warning">Stats reconnecting...</span>
        )}
      </div>

      {notice && (
        <div className="fallback-notice">{notice}</div>
      )}

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}
    </div>
  )
}

export default VideoStream

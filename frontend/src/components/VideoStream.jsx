import React, { useState, useEffect, useRef } from 'react'
import './VideoStream.css'

export const VideoStream = ({ apiBaseUrl = '' }) => {
  const videoRef = useRef(null)
  const imgRef = useRef(null)
  const wrapperRef = useRef(null)
  const popoutRef = useRef(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [streamMode, setStreamMode] = useState('none') // none | webrtc | mjpeg
  const [mjpegUrl, setMjpegUrl] = useState('')
  const pcRef = useRef(null)

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

  const startMJPEGFallback = (baseUrl, reason) => {
    closePeerConnection()

    setNotice(reason || 'Using MJPEG fallback stream')
    setStreamMode('mjpeg')
    setConnectionState('connecting')
    setIsConnecting(true)
    setIsConnected(false)
    setError(null)

    // timestamp prevents stale browser cache
    setMjpegUrl(`${baseUrl}/api/camera/stream?t=${Date.now()}`)
  }

  const connectStream = async () => {
    if (isConnected || isConnecting) {
      return
    }

    setIsConnecting(true)
    setError(null)
    setNotice(null)

    const baseUrl = getBaseUrl()
    let usedMjpegFallback = false

    try {
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

      const response = await fetch(`${baseUrl}/api/webrtc/offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: offer.sdp,
          type: offer.type
        })
      })

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
  }

  const toggleFullscreen = async () => {
    try {
      const el = wrapperRef.current
      if (!el) return

      const requestFullscreen =
        el.requestFullscreen ||
        el.webkitRequestFullscreen ||
        el.msRequestFullscreen

      const exitFullscreen =
        document.exitFullscreen ||
        document.webkitExitFullscreen ||
        document.msExitFullscreen

      const fullscreenElement =
        document.fullscreenElement ||
        document.webkitFullscreenElement ||
        document.msFullscreenElement

      if (!fullscreenElement && requestFullscreen) {
        await requestFullscreen.call(el)
        setIsFullscreen(true)
      } else if (fullscreenElement && exitFullscreen) {
        await exitFullscreen.call(document)
        setIsFullscreen(false)
      }
    } catch (err) {
      console.error('Fullscreen toggle failed:', err)
      setError('Unable to toggle fullscreen mode')
    }
  }

  const openPopout = () => {
    const baseUrl = getBaseUrl()
    const streamUrl = `${baseUrl}/api/camera/stream?t=${Date.now()}`

    const popup = window.open(
      streamUrl,
      'jetson_camera_popout',
      'width=1280,height=840,resizable=yes,scrollbars=no,noopener,noreferrer'
    )

    if (!popup) {
      setError('Pop-out blocked by browser. Please allow pop-ups for this page.')
      return
    }
    popup.focus()
    popoutRef.current = popup
  }

  const onMjpegLoaded = () => {
    setIsConnected(true)
    setIsConnecting(false)
    setConnectionState('connected')
  }

  const onMjpegError = () => {
    setIsConnected(false)
    setIsConnecting(false)
    setConnectionState('failed')
    setError('Failed to load MJPEG stream from backend')
  }

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement))
    }

    document.addEventListener('fullscreenchange', handleFullscreenChange)

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
      disconnect()
    }
  }, [])

  return (
    <div className="video-stream-container">
      <div className="video-wrapper" ref={wrapperRef}>
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
              : 'Click "Start Stream" to begin'}
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
            {isConnecting ? 'Connecting...' : 'Start Stream'}
          </button>
        ) : (
          <button
            onClick={disconnect}
            className="btn btn-danger"
          >
            Stop Stream
          </button>
        )}

        <button
          onClick={toggleFullscreen}
          className="btn btn-secondary"
        >
          {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
        </button>

        <button
          onClick={openPopout}
          className="btn btn-secondary"
        >
          Pop-out
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

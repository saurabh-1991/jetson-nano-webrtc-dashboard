import React, { useState, useEffect, useRef } from 'react'
import './VideoStream.css'

const H264_CONTENT_TYPE = 'video/mp4; codecs="avc1.42E01E"'
const H264_COOLDOWN_STORAGE_PREFIX = 'jetson_h264_cooldown_v1_'
const h264FailureStateByCamera = new Map()

const readStoredH264Cooldown = (cameraId) => {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(`${H264_COOLDOWN_STORAGE_PREFIX}${cameraId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed.cooldownUntilTs !== 'number') {
      return null
    }
    return parsed
  } catch (_e) {
    return null
  }
}

const writeStoredH264Cooldown = (cameraId, state) => {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(`${H264_COOLDOWN_STORAGE_PREFIX}${cameraId}`, JSON.stringify(state))
  } catch (_e) {
    // no-op
  }
}

const clearStoredH264Cooldown = (cameraId) => {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.removeItem(`${H264_COOLDOWN_STORAGE_PREFIX}${cameraId}`)
  } catch (_e) {
    // no-op
  }
}

const getH264FailureState = (cameraId) => {
  const key = String(cameraId || '').toLowerCase()
  if (!key) {
    return {
      failures: 0,
      cooldownUntilTs: 0,
      reason: '',
    }
  }

  const current = h264FailureStateByCamera.get(key)
  if (current) {
    return current
  }

  const restored = readStoredH264Cooldown(key)
  const state = {
    failures: Number(restored?.failures || 0),
    cooldownUntilTs: Number(restored?.cooldownUntilTs || 0),
    reason: String(restored?.reason || ''),
  }
  h264FailureStateByCamera.set(key, state)
  return state
}

const getH264CooldownRemainingMs = (cameraId) => {
  const state = getH264FailureState(cameraId)
  const remaining = Math.max(0, Number(state.cooldownUntilTs || 0) - Date.now())
  return remaining
}

const markH264Failure = (cameraId, options = {}) => {
  const key = String(cameraId || '').toLowerCase()
  if (!key) return

  const state = getH264FailureState(key)
  const baseMs = Math.max(5000, Number(options.baseMs || 45000))
  const maxMs = Math.max(baseMs, Number(options.maxMs || 300000))

  state.failures = Number(state.failures || 0) + 1
  const multiplier = Math.pow(2, Math.max(0, state.failures - 1))
  const localCooldownMs = Math.min(maxMs, Math.round(baseMs * multiplier))
  const backendRetryMs = Math.max(0, Number(options.backendRetryMs || 0))
  const effectiveCooldownMs = Math.max(localCooldownMs, backendRetryMs)
  state.cooldownUntilTs = Date.now() + effectiveCooldownMs
  state.reason = String(options.reason || 'h264_failed')

  h264FailureStateByCamera.set(key, state)
  writeStoredH264Cooldown(key, state)
}

const markH264Success = (cameraId) => {
  const key = String(cameraId || '').toLowerCase()
  if (!key) return

  h264FailureStateByCamera.set(key, {
    failures: 0,
    cooldownUntilTs: 0,
    reason: '',
  })
  clearStoredH264Cooldown(key)
}

const probeH264DecodeCapabilities = async () => {
  try {
    if (typeof window === 'undefined') {
      return { checked: false, supported: false, hardwareLikely: false, reason: 'no_window' }
    }

    const mediaCapabilities = window.navigator?.mediaCapabilities
    if (mediaCapabilities && typeof mediaCapabilities.decodingInfo === 'function') {
      const result = await mediaCapabilities.decodingInfo({
        type: 'media-source',
        video: {
          contentType: H264_CONTENT_TYPE,
          width: 1280,
          height: 720,
          bitrate: 1200000,
          framerate: 20,
        },
      })

      return {
        checked: true,
        supported: Boolean(result?.supported),
        hardwareLikely: Boolean(result?.powerEfficient),
        smooth: Boolean(result?.smooth),
        reason: result?.supported ? 'media_capabilities_supported' : 'media_capabilities_unsupported',
      }
    }

    const probeVideo = document.createElement('video')
    const canPlayType = typeof probeVideo?.canPlayType === 'function'
      ? probeVideo.canPlayType(H264_CONTENT_TYPE)
      : ''
    const supported = canPlayType === 'probably' || canPlayType === 'maybe'

    return {
      checked: true,
      supported,
      hardwareLikely: supported,
      reason: supported ? 'canplaytype_supported' : 'canplaytype_unsupported',
    }
  } catch (_err) {
    return { checked: true, supported: false, hardwareLikely: false, reason: 'probe_exception' }
  }
}

export const VideoStream = ({
  apiBaseUrl = '',
  cameraId = 'cam1',
  startLabel = 'Start Video',
  stopLabel = 'Stop Video',
  forceMjpeg = false,
  enableH264Trial = true,
  preferHardwareH264 = true,
  autoConnectSignal = 0,
  autoConnectDelayMs = 0,
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
  const [streamMode, setStreamMode] = useState('none') // none | webrtc | mjpeg | h264
  const [mjpegUrl, setMjpegUrl] = useState('')
  const [mjpegGuardActive, setMjpegGuardActive] = useState(false)
  const [liveStats, setLiveStats] = useState(null)
  const [statsError, setStatsError] = useState(false)
  const pcRef = useRef(null)
  const gatewayWhepResourceUrlRef = useRef('')
  const gatewayWhepRequestUrlRef = useRef('')
  const fallbackActiveRef = useRef(false)
  const mjpegRetryTimerRef = useRef(null)
  const mjpegConnectWatchdogTimerRef = useRef(null)
  const mjpegRetryCountRef = useRef(0)
  const lastRecoverRequestTsRef = useRef(0)
  const statsPollTimerRef = useRef(null)
  const statsPollInFlightRef = useRef(false)
  const statsErrorStreakRef = useRef(0)
  const mjpegNoViewerStreakRef = useRef(0)
  const streamModeRef = useRef('none')
  const isConnectedRef = useRef(false)
  const isConnectingRef = useRef(false)
  const h264TrialFailedRef = useRef(false)
  const h264DecodeProbeRef = useRef(null)

  const buildIceServersConfig = () => {
    const fallback = [
      { urls: ['stun:stun.l.google.com:19302'] },
      { urls: ['stun:stun1.l.google.com:19302'] },
    ]

    const raw = import.meta.env.VITE_MEDIA_WEBRTC_ICE_SERVERS_JSON
    if (!raw || typeof raw !== 'string') {
      return fallback
    }

    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed
      }
    } catch (_err) {
      // fallback to defaults
    }

    return fallback
  }

  const getBaseUrl = () => apiBaseUrl || (
    import.meta.env.DEV
      ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
      : ''
  )

  const closePeerConnection = () => {
    const resourceUrl = gatewayWhepResourceUrlRef.current
    if (resourceUrl) {
      fetch(resourceUrl, { method: 'DELETE' }).catch(() => {
        // best effort cleanup
      })
    }
    gatewayWhepResourceUrlRef.current = ''
    gatewayWhepRequestUrlRef.current = ''

    if (pcRef.current) {
      pcRef.current.close()
      pcRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  const waitForIceGatheringComplete = (pc, timeoutMs = 2500) => new Promise((resolve) => {
    if (!pc || pc.iceGatheringState === 'complete') {
      resolve()
      return
    }

    let done = false
    const finish = () => {
      if (done) return
      done = true
      clearTimeout(timer)
      pc.removeEventListener('icegatheringstatechange', onStateChange)
      resolve()
    }

    const onStateChange = () => {
      if (pc.iceGatheringState === 'complete') {
        finish()
      }
    }

    const timer = setTimeout(finish, timeoutMs)
    pc.addEventListener('icegatheringstatechange', onStateChange)
  })

  const toAbsoluteUrl = (maybeRelativeUrl, baseUrl) => {
    try {
      return new URL(maybeRelativeUrl, baseUrl).toString()
    } catch (_e) {
      return ''
    }
  }

  const tryStartGatewayWebRTC = async (gatewayWhepUrl) => {
    if (!gatewayWhepUrl || !videoRef.current) {
      return false
    }

    closePeerConnection()
    fallbackActiveRef.current = false
    setStreamMode('webrtc')
    setConnectionState('connecting')
    setIsConnecting(true)
    setIsConnected(false)
    setNotice('Trying WebRTC gateway path...')

    const pc = new RTCPeerConnection({
      iceServers: buildIceServersConfig(),
    })
    pcRef.current = pc
    pc.addTransceiver('video', { direction: 'recvonly' })

    await pc.setLocalDescription(await pc.createOffer())
    await waitForIceGatheringComplete(pc, 2600)

    const localSdp = pc.localDescription?.sdp
    if (!localSdp) {
      throw new Error('Gateway WebRTC local SDP was not created')
    }

    const controller = new AbortController()
    const timeout = setTimeout(() => {
      try { controller.abort() } catch (_e) {}
    }, 5000)

    let response
    try {
      response = await fetch(gatewayWhepUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/sdp',
          Accept: 'application/sdp',
        },
        signal: controller.signal,
        body: localSdp,
      })
    } finally {
      clearTimeout(timeout)
    }

    if (!response.ok) {
      throw new Error(`Gateway WHEP returned ${response.status}`)
    }

    const answerSdp = (await response.text()) || ''
    if (!answerSdp.trim()) {
      throw new Error('Gateway WHEP returned empty SDP answer')
    }

    const locationHeader = response.headers.get('Location') || response.headers.get('location')
    const sessionUrl = locationHeader ? toAbsoluteUrl(locationHeader, gatewayWhepUrl) : ''
    gatewayWhepRequestUrlRef.current = gatewayWhepUrl
    gatewayWhepResourceUrlRef.current = sessionUrl

    await pc.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: answerSdp }))

    await new Promise((resolve, reject) => {
      let done = false

      const cleanup = () => {
        clearTimeout(timer)
        pc.removeEventListener('connectionstatechange', onConnectionStateChange)
      }

      const succeed = () => {
        if (done) return
        done = true
        cleanup()
        resolve(true)
      }

      const fail = (reason) => {
        if (done) return
        done = true
        cleanup()
        reject(new Error(reason))
      }

      const onConnectionStateChange = () => {
        if (pc.connectionState === 'connected') {
          succeed()
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
          fail(`Gateway WebRTC ${pc.connectionState}`)
        }
      }

      pc.ontrack = (event) => {
        if (event.streams && event.streams[0] && videoRef.current) {
          videoRef.current.srcObject = event.streams[0]
          succeed()
        }
      }

      pc.addEventListener('connectionstatechange', onConnectionStateChange)
      const timer = setTimeout(() => fail('Gateway WebRTC connection timeout'), 7000)
    })

    setIsConnected(true)
    setIsConnecting(false)
    setConnectionState('connected')
    setNotice('Using WebRTC gateway stream mode')
    return true
  }

  const clearMjpegRetryTimer = () => {
    if (mjpegRetryTimerRef.current) {
      clearTimeout(mjpegRetryTimerRef.current)
      mjpegRetryTimerRef.current = null
    }
  }

  const clearMjpegConnectWatchdogTimer = () => {
    if (mjpegConnectWatchdogTimerRef.current) {
      clearTimeout(mjpegConnectWatchdogTimerRef.current)
      mjpegConnectWatchdogTimerRef.current = null
    }
  }

  const clearStatsPollTimer = () => {
    if (statsPollTimerRef.current) {
      clearTimeout(statsPollTimerRef.current)
      statsPollTimerRef.current = null
    }
  }

  const bestEffortPrewarmCamera = async (baseUrl) => {
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => {
        try { controller.abort() } catch (_e) {}
      }, 2400)

      try {
        await fetch(`${baseUrl}/api/camera/prewarm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ camera_ids: [cameraId] }),
        })
      } finally {
        clearTimeout(timer)
      }
    } catch (_e) {
      // best effort
    }
  }

  const bestEffortRecoverCamera = (baseUrl, reason = 'mjpeg_retry') => {
    const now = Date.now()
    // Avoid flooding recover calls during unstable LAN periods.
    if ((now - lastRecoverRequestTsRef.current) < 7000) {
      return
    }
    lastRecoverRequestTsRef.current = now

    fetch(`${baseUrl}/api/camera/recover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        camera_id: cameraId,
        reason,
      })
    }).catch(() => {
      // best effort
    })
  }

  const startMJPEGFallback = (baseUrl, reason) => {
    fallbackActiveRef.current = true
    closePeerConnection()
    clearMjpegRetryTimer()
    clearMjpegConnectWatchdogTimer()

    setNotice(reason || 'Using MJPEG fallback stream')
    setStreamMode('mjpeg')
    setConnectionState('connecting')
    setIsConnecting(true)
    setIsConnected(false)
    setMjpegGuardActive(false)
    setError(null)

    // timestamp prevents stale browser cache
    setMjpegUrl(
      `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
    )
  }

  const tryStartH264Stream = async (baseUrl) => {
    if (!enableH264Trial || forceMjpeg || !videoRef.current) {
      return false
    }

    if (preferHardwareH264) {
      if (!h264DecodeProbeRef.current) {
        h264DecodeProbeRef.current = probeH264DecodeCapabilities()
      }

      const decodeProbe = await h264DecodeProbeRef.current
      if (!decodeProbe?.supported) {
        setNotice('Browser H.264 decode support unavailable; using fallback stream path.')
        return false
      }
    }

    const videoEl = videoRef.current
    const h264Url = `${baseUrl}/api/camera/stream_h264?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`

    setStreamMode('h264')
    setConnectionState('connecting')
    setIsConnecting(true)
    setIsConnected(false)

    if (preferHardwareH264) {
      const decodeProbe = await h264DecodeProbeRef.current
      const noticeText = decodeProbe?.hardwareLikely
        ? 'Trying H.264 live path (hardware decode preferred)...'
        : 'Trying H.264 live path (hardware decode not confirmed by browser)...'
      setNotice(noticeText)
    } else {
      setNotice('Trying H.264 live path...')
    }

    return await new Promise((resolve) => {
      let finished = false

      const cleanup = () => {
        videoEl.removeEventListener('playing', onPlaying)
        videoEl.removeEventListener('canplay', onCanPlay)
        videoEl.removeEventListener('error', onError)
        clearTimeout(timeout)
      }

      const fail = () => {
        if (finished) return
        finished = true
        cleanup()
        try {
          videoEl.pause()
          videoEl.removeAttribute('src')
          videoEl.load()
        } catch (_e) {
          // no-op
        }
        resolve(false)
      }

      const onPlaying = () => {
        if (finished) return
        finished = true
        cleanup()
        const decodeProbe = h264DecodeProbeRef.current
        if (preferHardwareH264 && decodeProbe && typeof decodeProbe.then === 'function') {
          decodeProbe.then((probe) => {
            if (probe?.hardwareLikely) {
              setNotice('Using H.264 live stream mode (hardware decode active/preferred).')
            } else {
              setNotice('Using H.264 live stream mode (browser hardware decode not confirmed).')
            }
          }).catch(() => {
            setNotice('Using H.264 live stream mode')
          })
        } else {
          setNotice('Using H.264 live stream mode')
        }
        setIsConnected(true)
        setIsConnecting(false)
        setConnectionState('connected')
        markH264Success(cameraId)
        resolve(true)
      }

      const onCanPlay = () => {
        try {
          const p = videoEl.play()
          if (p && typeof p.catch === 'function') {
            p.catch(() => {
              // ignore autoplay hiccups; playing/error/timeout handles state
            })
          }
        } catch (_e) {
          // ignore
        }
      }

      const onError = () => {
        fail()
      }

      const timeout = setTimeout(() => {
        fail()
      }, 5000)

      videoEl.addEventListener('playing', onPlaying)
      videoEl.addEventListener('canplay', onCanPlay)
      videoEl.addEventListener('error', onError)

      try {
        videoEl.srcObject = null
      } catch (_e) {
        // no-op
      }
      videoEl.src = h264Url
      videoEl.muted = true
      videoEl.autoplay = true
      videoEl.playsInline = true
      videoEl.load()
      onCanPlay()
    })
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
    let cameraInfoData = null
    let h264Hint = null

    try {
      if (forceMjpeg) {
        await bestEffortPrewarmCamera(baseUrl)
        usedMjpegFallback = true
        startMJPEGFallback(baseUrl, 'Using MJPEG mode for this camera')
        return
      }

      const infoResponse = await fetch(
        `${baseUrl}/api/camera/info?camera_id=${encodeURIComponent(cameraId)}`,
        { cache: 'no-store' }
      )
      const infoData = infoResponse.ok ? await infoResponse.json() : null
      cameraInfoData = infoData
      h264Hint = infoData?.h264_stream || null

      if (infoResponse.status === 404) {
        setError(`Camera ${cameraId} is not enabled in backend configuration.`)
        setConnectionState('disconnected')
        setIsConnecting(false)
        setIsConnected(false)
        return
      }

      const localH264CooldownMs = getH264CooldownRemainingMs(cameraId)
      const backendH264CooldownMs = Math.max(0, Number(h264Hint?.cooldown_remaining_ms || 0))
      const effectiveH264CooldownMs = Math.max(localH264CooldownMs, backendH264CooldownMs)
      const h264EnabledForCamera = h264Hint?.enabled !== false

      if (!h264TrialFailedRef.current && enableH264Trial && h264EnabledForCamera && effectiveH264CooldownMs <= 0) {
        await bestEffortPrewarmCamera(baseUrl)
        const h264Connected = await tryStartH264Stream(baseUrl)
        if (h264Connected) {
          return
        }

        markH264Failure(cameraId, {
          reason: 'h264_probe_failed',
          baseMs: Number(h264Hint?.failure_cooldown_base_ms || 45000),
          maxMs: Number(h264Hint?.failure_cooldown_max_ms || 300000),
          backendRetryMs: Number(h264Hint?.cooldown_remaining_ms || 0),
        })
        h264TrialFailedRef.current = true
        setNotice('H.264 trial unavailable; trying WebRTC next, then MJPEG fallback if needed.')
      } else if (enableH264Trial && h264EnabledForCamera && effectiveH264CooldownMs > 0) {
        const retrySeconds = Math.max(1, Math.ceil(effectiveH264CooldownMs / 1000))
        setNotice(`H.264 temporarily cooled down for ${cameraId}. Retrying in ~${retrySeconds}s; using fallback path now.`)
      }

      const gatewayEnabled = Boolean(cameraInfoData?.media_gateway?.enabled)
      const gatewayWhepUrl = (cameraInfoData?.media_gateway?.whep_url || '').trim()
      if (gatewayEnabled && gatewayWhepUrl) {
        try {
          const gatewayConnected = await tryStartGatewayWebRTC(gatewayWhepUrl)
          if (gatewayConnected) {
            return
          }
        } catch (gatewayErr) {
          closePeerConnection()
          setNotice(`Gateway WebRTC unavailable (${gatewayErr?.message || 'error'}). Trying backend WebRTC...`)
        }
      }

      if (cameraInfoData?.webrtc?.allowed_for_camera === false) {
        await bestEffortPrewarmCamera(baseUrl)
        usedMjpegFallback = true
        startMJPEGFallback(
          baseUrl,
          `WebRTC disabled for ${cameraId} on backend policy. Using MJPEG mode.`
        )
        return
      }

      setStreamMode('webrtc')

      // Create peer connection
      const config = {
        iceServers: buildIceServersConfig()
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
          await bestEffortPrewarmCamera(baseUrl)
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
      await bestEffortPrewarmCamera(baseUrl)
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
    clearMjpegConnectWatchdogTimer()
    fallbackActiveRef.current = false
    mjpegRetryCountRef.current = 0
    closePeerConnection()
    if (imgRef.current) {
      imgRef.current.src = ''
    }
    if (videoRef.current) {
      try {
        videoRef.current.pause()
        videoRef.current.removeAttribute('src')
        videoRef.current.load()
      } catch (_e) {
        // no-op
      }
    }
    setMjpegUrl('')
    setStreamMode('none')
    setNotice(null)
    setMjpegGuardActive(false)
    setError(null)
    setIsConnecting(false)
    setIsConnected(false)
    setConnectionState('disconnected')

    if (popoutRef.current && !popoutRef.current.closed) {
      popoutRef.current.close()
      popoutRef.current = null
    }

    const stopPayload = {
      camera_id: cameraId,
      stream_session_id: streamSessionIdRef.current,
    }

    // Best-effort camera release request. Backend releases only when no active viewers.
    fetch(`${baseUrl}/api/camera/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(stopPayload)
    }).catch((err) => {
      console.warn('Camera stop request failed:', err)
    })

    // Follow-up forced cleanup sweeps for network-jitter cases where browser-side
    // stream sockets can remain half-open and keep backend MJPEG sessions alive.
    ;[1200, 3000].forEach((delayMs) => {
      setTimeout(() => {
        if (fallbackActiveRef.current) {
          return
        }

        fetch(`${baseUrl}/api/camera/stop`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...stopPayload,
            force: true,
          })
        }).catch(() => {
          // best effort
        })
      }, delayMs)
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
    if (!fallbackActiveRef.current) {
      return
    }

    clearMjpegRetryTimer()
    clearMjpegConnectWatchdogTimer()
    mjpegRetryCountRef.current = 0
    setMjpegGuardActive(false)
    setError(null)
    setIsConnected(true)
    setIsConnecting(false)
    setConnectionState('connected')
  }

  const onMjpegError = () => {
    if (!fallbackActiveRef.current) {
      return
    }

    const baseUrl = getBaseUrl()
    const nextAttempt = mjpegRetryCountRef.current + 1
    mjpegRetryCountRef.current = nextAttempt

    setIsConnected(false)
    setIsConnecting(true)
    setConnectionState('connecting')

    const guardMode = nextAttempt >= 4
    const retryDelayMs = guardMode ? 5000 : Math.min(350 * nextAttempt, 1800)

    if (nextAttempt === 3 || (nextAttempt > 3 && nextAttempt % 4 === 0)) {
      bestEffortRecoverCamera(baseUrl, 'mjpeg_onerror_retry')
    }

    setMjpegGuardActive(guardMode)
    if (guardMode) {
      setError('Camera reconnect guard active: retrying every 5s to avoid thrashing.')
    } else {
      setError(`MJPEG stream load failed, retrying (${nextAttempt})...`)
    }

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
    if (statsPollInFlightRef.current) {
      return
    }
    statsPollInFlightRef.current = true
    try {
      const baseUrl = getBaseUrl()
      const response = await fetch(`${baseUrl}/api/stats`, {
        cache: 'no-store',
      })
      if (!response.ok) {
        throw new Error(`stats ${response.status}`)
      }

      const stats = await response.json()
      const cameraStats = stats?.cameras?.[cameraId] || null
      setLiveStats({ ...stats, cameraScoped: cameraStats })
      setStatsError(false)
      statsErrorStreakRef.current = 0

      if (streamModeRef.current === 'mjpeg' && fallbackActiveRef.current && isConnectedRef.current) {
        const viewerCount = Number(cameraStats?.active_mjpeg_clients ?? 0)
        if (viewerCount <= 0) {
          mjpegNoViewerStreakRef.current += 1
        } else {
          mjpegNoViewerStreakRef.current = 0
        }

        if (mjpegNoViewerStreakRef.current >= 3) {
          const baseUrl = getBaseUrl()
          mjpegNoViewerStreakRef.current = 0
          setNotice('Stream looked stale; reconnecting MJPEG automatically.')
          setIsConnected(false)
          setIsConnecting(true)
          setConnectionState('connecting')
          setMjpegUrl(
            `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
          )
        }
      }
    } catch (err) {
      setStatsError(true)
      statsErrorStreakRef.current += 1

      if (
        streamModeRef.current === 'mjpeg' &&
        fallbackActiveRef.current &&
        isConnectedRef.current &&
        statsErrorStreakRef.current >= 3
      ) {
        const baseUrl = getBaseUrl()
        statsErrorStreakRef.current = 0
        setNotice('Network jitter detected; reconnecting MJPEG stream.')
        setIsConnected(false)
        setIsConnecting(true)
        setConnectionState('connecting')
        setMjpegUrl(
          `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
        )
      }
    } finally {
      statsPollInFlightRef.current = false
    }
  }

  const scheduleStatsPoll = (delayMs = 3000) => {
    clearStatsPollTimer()
    statsPollTimerRef.current = setTimeout(async () => {
      if (isConnectedRef.current || isConnectingRef.current) {
        await pollLiveStats()
      }
      const nextDelay = isConnectedRef.current ? 6000 : 12000
      scheduleStatsPoll(nextDelay)
    }, delayMs)
  }

  useEffect(() => {
    isConnectedRef.current = isConnected
  }, [isConnected])

  useEffect(() => {
    isConnectingRef.current = isConnecting
  }, [isConnecting])

  useEffect(() => {
    streamModeRef.current = streamMode
  }, [streamMode])

  useEffect(() => {
    if (!autoConnectSignal) {
      return
    }

    const delayMs = Math.max(0, Number(autoConnectDelayMs) || 0)
    const timer = setTimeout(() => {
      if (!isConnectedRef.current && !isConnectingRef.current) {
        connectStream()
      }
    }, delayMs)

    return () => {
      clearTimeout(timer)
    }
  }, [autoConnectSignal, autoConnectDelayMs])

  useEffect(() => {
    pollLiveStats()
    scheduleStatsPoll(3500)

    return () => {
      clearStatsPollTimer()
      clearMjpegRetryTimer()
      clearMjpegConnectWatchdogTimer()
      disconnect()
    }
  }, [])

  useEffect(() => {
    if (!(streamMode === 'mjpeg' && isConnecting && !isConnected && mjpegUrl)) {
      clearMjpegConnectWatchdogTimer()
      return
    }

    clearMjpegConnectWatchdogTimer()
    mjpegConnectWatchdogTimerRef.current = setTimeout(() => {
      if (!fallbackActiveRef.current) {
        return
      }

      const baseUrl = getBaseUrl()
      const nextAttempt = mjpegRetryCountRef.current + 1
      mjpegRetryCountRef.current = nextAttempt

      const guardMode = nextAttempt >= 4
      if (nextAttempt === 3 || (nextAttempt > 3 && nextAttempt % 4 === 0)) {
        bestEffortRecoverCamera(baseUrl, 'mjpeg_watchdog_timeout')
      }
      setMjpegGuardActive(guardMode)
      setError(
        guardMode
          ? 'Camera reconnect guard active: retrying every 5s to avoid thrashing.'
          : `MJPEG stream connect timeout, retrying (${nextAttempt})...`
      )

      setMjpegUrl(
        `${baseUrl}/api/camera/stream?camera_id=${encodeURIComponent(cameraId)}&sid=${encodeURIComponent(streamSessionIdRef.current)}&t=${Date.now()}`
      )
    }, 9000)

    return () => {
      clearMjpegConnectWatchdogTimer()
    }
  }, [streamMode, isConnecting, isConnected, mjpegUrl, cameraId])

  const mjpegViewers = Number(liveStats?.cameraScoped?.active_mjpeg_clients ?? 0)
  const h264Viewers = Number(liveStats?.cameraScoped?.active_h264_clients ?? 0)
  const webrtcViewers = Number(liveStats?.webrtc_connections || 0)
  const totalViewers = mjpegViewers + h264Viewers + (forceMjpeg ? 0 : webrtcViewers)
  const cameraPerf = liveStats?.cameraScoped?.camera_performance || liveStats?.camera_performance || null
  const frameHitRatio = cameraPerf?.frame_cache?.hit_ratio
  const jpegHitRatio = cameraPerf?.jpeg_cache?.hit_ratio
  const avgEncodeMs = cameraPerf?.jpeg_encode?.avg_ms

  useEffect(() => {
    if (streamMode !== 'mjpeg') {
      return
    }

    if (mjpegViewers > 0 && isConnected) {
      clearMjpegRetryTimer()
      setMjpegGuardActive(false)
      if (typeof error === 'string' && error.startsWith('MJPEG stream load failed')) {
        setError(null)
      }
    }
  }, [streamMode, mjpegViewers, isConnected, error])

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
                : streamMode === 'h264'
                  ? 'Loading H.264 stream...'
                : 'Connecting WebRTC...'
              : `Click "${startLabel}" to begin`}
          </div>
        )}
      </div>

      <div className="video-controls">
        {!isConnected && !isConnecting ? (
          <button
            onClick={connectStream}
            className="btn btn-primary"
          >
            {startLabel}
          </button>
        ) : (
          <button
            onClick={disconnect}
            className="btn btn-danger"
          >
            {isConnecting ? 'Cancel Connect' : stopLabel}
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
        {mjpegGuardActive && streamMode === 'mjpeg' && (
          <span className="stream-mode">Retry Guard (5s)</span>
        )}
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
        <span className="metrics-chip">H264: {h264Viewers}</span>
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

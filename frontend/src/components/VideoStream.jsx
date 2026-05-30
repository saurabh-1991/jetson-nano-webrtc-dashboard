import React, { useState, useEffect, useRef } from 'react'
import './VideoStream.css'

export const VideoStream = ({ apiBaseUrl = '' }) => {
  const videoRef = useRef(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState('disconnected')
  const [error, setError] = useState(null)
  const pcRef = useRef(null)

  const connectWebRTC = async () => {
    if (isConnected || isConnecting) return

    setIsConnecting(true)
    setError(null)

    try {
      const baseUrl = apiBaseUrl || (
        process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : ''
      )

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
        throw new Error(`Server returned ${response.status}`)
      }

      const answer = await response.json()
      await pc.setRemoteDescription(new RTCSessionDescription(answer))

      setIsConnected(true)
      setConnectionState('connected')
    } catch (err) {
      console.error('WebRTC connection error:', err)
      setError(err.message)
      setIsConnected(false)
      setConnectionState('failed')
      if (pcRef.current) {
        pcRef.current.close()
        pcRef.current = null
      }
    } finally {
      setIsConnecting(false)
    }
  }

  const disconnect = () => {
    if (pcRef.current) {
      pcRef.current.close()
      pcRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setIsConnected(false)
    setConnectionState('disconnected')
  }

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [])

  return (
    <div className="video-stream-container">
      <div className="video-wrapper">
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
        {!isConnected && (
          <div className="video-placeholder">
            {isConnecting ? 'Connecting...' : 'Click "Start Stream" to begin'}
          </div>
        )}
      </div>

      <div className="video-controls">
        {!isConnected ? (
          <button
            onClick={connectWebRTC}
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
      </div>

      <div className="video-status">
        <div className={`status-indicator ${connectionState}`}></div>
        <span className="status-text">
          {connectionState.charAt(0).toUpperCase() + connectionState.slice(1)}
        </span>
      </div>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}
    </div>
  )
}

export default VideoStream

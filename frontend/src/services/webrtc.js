/**
 * WebRTC Service for video streaming
 * Handles peer connection, offer/answer exchange, and media streaming
 */

export class WebRTCService {
  constructor(apiBaseUrl = '') {
    this.pc = null
    this.videoElement = null
    this.apiBaseUrl = apiBaseUrl || (
      process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : ''
    )
    this.onConnectionStateChange = null
    this.onError = null
  }

  /**
   * Initialize WebRTC peer connection and establish connection
   * @param {HTMLVideoElement} videoElement - Video element to display stream
   * @returns {Promise<void>}
   */
  async connect(videoElement) {
    try {
      this.videoElement = videoElement

      // Create peer connection with STUN servers
      const config = {
        iceServers: [
          { urls: ['stun:stun.l.google.com:19302'] },
          { urls: ['stun:stun1.l.google.com:19302'] },
        ]
      }

      this.pc = new RTCPeerConnection(config)

      // Handle incoming stream
      this.pc.ontrack = (event) => {
        console.log('Received remote stream:', event.streams)
        if (event.streams && event.streams[0]) {
          this.videoElement.srcObject = event.streams[0]
        }
      }

      // Handle connection state changes
      this.pc.onconnectionstatechange = () => {
        console.log('Connection state:', this.pc.connectionState)
        if (this.onConnectionStateChange) {
          this.onConnectionStateChange(this.pc.connectionState)
        }

        if (this.pc.connectionState === 'failed' || this.pc.connectionState === 'disconnected') {
          this.disconnect()
        }
      }

      // Handle ICE connection state
      this.pc.oniceconnectionstatechange = () => {
        console.log('ICE connection state:', this.pc.iceConnectionState)
      }

      // Handle ICE candidates
      this.pc.onicecandidate = (event) => {
        if (event.candidate) {
          console.log('New ICE candidate:', event.candidate)
        }
      }

      // Create and send offer
      const offer = await this.pc.createOffer()
      await this.pc.setLocalDescription(offer)

      // Send offer to server and get answer
      const response = await fetch(`${this.apiBaseUrl}/api/webrtc/offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: offer.sdp,
          type: offer.type
        })
      })

      if (!response.ok) {
        throw new Error(`Failed to get WebRTC answer: ${response.statusText}`)
      }

      const answer = await response.json()
      await this.pc.setRemoteDescription(new RTCSessionDescription(answer))

      console.log('WebRTC connection established')
    } catch (error) {
      console.error('WebRTC connection error:', error)
      if (this.onError) {
        this.onError(error)
      }
      throw error
    }
  }

  /**
   * Close WebRTC connection
   */
  disconnect() {
    if (this.pc) {
      this.pc.close()
      this.pc = null
    }
    if (this.videoElement) {
      this.videoElement.srcObject = null
    }
  }

  /**
   * Get connection state
   * @returns {string}
   */
  getConnectionState() {
    return this.pc ? this.pc.connectionState : null
  }

  /**
   * Get ICE connection state
   * @returns {string}
   */
  getIceConnectionState() {
    return this.pc ? this.pc.iceConnectionState : null
  }
}

export default WebRTCService

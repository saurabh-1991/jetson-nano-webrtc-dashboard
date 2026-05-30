"""WebRTC streaming for real-time video"""

import logging
import asyncio
import cv2
import numpy as np
from typing import Optional
from aiortc import RTCPeerConnection, VideoStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaStreamTrack
import av
from .config import STUN_SERVERS
from .camera import get_camera

logger = logging.getLogger(__name__)


class CameraVideoTrack(VideoStreamTrack):
    """Custom video track that captures from camera"""

    def __init__(self):
        super().__init__()
        self.camera = get_camera()
        self.frame_count = 0

    async def recv(self) -> av.VideoFrame:
        """Receive next video frame"""
        # Get frame from camera
        success, frame = self.camera.get_frame()

        if not success or frame is None:
            # Return a black frame if camera fails
            pts, time_base = await self.next_timestamp()
            black_frame = av.VideoFrame.from_ndarray(
                np.zeros((480, 640, 3), dtype=np.uint8),
                format="bgr24"
            )
            black_frame.pts = pts
            black_frame.time_base = time_base
            return black_frame

        self.frame_count += 1

        # Convert frame to VideoFrame
        pts, time_base = await self.next_timestamp()
        
        # Ensure frame is in BGR format and correct dimensions
        if frame.shape[2] == 3:
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        else:
            video_frame = av.VideoFrame.from_ndarray(frame[:, :, :3], format="bgr24")

        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame


class WebRTCManager:
    """Manage WebRTC connections"""

    def __init__(self):
        self.peer_connections = set()
        self.stun_servers = [
            RTCIceServer(urls=[server]) for server in STUN_SERVERS
        ]
        logger.info("WebRTC Manager initialized")

    def create_peer_connection(self) -> RTCPeerConnection:
        """Create a new WebRTC peer connection"""
        try:
            config = RTCConfiguration(iceServers=self.stun_servers)
            pc = RTCPeerConnection(configuration=config)

            @pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                logger.info(f"ICE connection state: {pc.iceConnectionState}")
                if pc.iceConnectionState == "failed":
                    await pc.close()
                    self.peer_connections.discard(pc)

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"Connection state: {pc.connectionState}")
                if pc.connectionState in ["failed", "closed"]:
                    await pc.close()
                    self.peer_connections.discard(pc)

            self.peer_connections.add(pc)
            logger.info(f"New peer connection created. Total: {len(self.peer_connections)}")
            return pc

        except Exception as e:
            logger.error(f"Failed to create peer connection: {e}")
            raise

    async def close_peer_connection(self, pc: RTCPeerConnection):
        """Close a peer connection"""
        try:
            await pc.close()
            self.peer_connections.discard(pc)
            logger.info(f"Peer connection closed. Remaining: {len(self.peer_connections)}")
        except Exception as e:
            logger.error(f"Error closing peer connection: {e}")

    async def close_all_connections(self):
        """Close all peer connections"""
        for pc in list(self.peer_connections):
            await self.close_peer_connection(pc)
        logger.info("All peer connections closed")

    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.peer_connections)


# Global WebRTC manager
webrtc_manager = None


def get_webrtc_manager() -> WebRTCManager:
    """Get or create WebRTC manager"""
    global webrtc_manager
    if webrtc_manager is None:
        webrtc_manager = WebRTCManager()
    return webrtc_manager

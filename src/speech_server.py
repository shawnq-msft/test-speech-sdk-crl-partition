"""
speech_server.py — Mock HTTPS/WebSocket server simulating Azure Speech Service.

Listens on port 8443 with TLS using a certificate that contains CRL Distribution
Points (CDP) extension pointing to the CRL server.

Features:
  - Serves HTTPS with custom CA-signed certificates
  - Implements minimal WebSocket upgrade for Speech SDK connection
  - Supports certificate hot-reload (simulates certificate rotation)
  - Tracks active partition and connection metrics
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import ssl
import time
from pathlib import Path

import websockets
import websockets.server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Speech-Server] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class SpeechServer:
    def __init__(self, port: int = 8443, certs_dir: str | None = None):
        self.port = port
        self.certs_dir = Path(certs_dir) if certs_dir else Path(__file__).parent.parent / "certs"
        self.current_partition = 1
        self._connection_count = 0
        self._server = None
        self._ssl_context = None

    def _build_ssl_context(self) -> ssl.SSLContext:
        """Build SSL context with current partition's certificate."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cert_file = self.certs_dir / f"server-part{self.current_partition}-cert.pem"
        key_file = self.certs_dir / f"server-part{self.current_partition}-key.pem"

        if not cert_file.exists():
            raise FileNotFoundError(f"Certificate not found: {cert_file}")
        if not key_file.exists():
            raise FileNotFoundError(f"Key not found: {key_file}")

        ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
        log.info(f"Loaded certificate: partition{self.current_partition}")
        log.info(f"  Cert: {cert_file}")
        log.info(f"  Key:  {key_file}")
        return ctx

    def rotate_certificate(self, new_partition: int):
        """Rotate to a new certificate partition.
        
        In production, this simulates Azure rotating their TLS certificate
        to one issued from a different CRL partition.
        """
        old_partition = self.current_partition
        self.current_partition = new_partition
        self._ssl_context = self._build_ssl_context()
        log.warning(
            f"=== CERTIFICATE ROTATED: partition{old_partition} → partition{new_partition} ==="
        )
        log.warning(
            f"    New CDP: http://localhost:9000/crl/partition{new_partition}.crl"
        )

    async def _handle_connection(self, websocket):
        """Handle incoming WebSocket connection (Speech SDK protocol)."""
        self._connection_count += 1
        conn_id = self._connection_count
        remote = websocket.remote_address

        log.info(f"[Conn #{conn_id}] New connection from {remote}")
        log.info(f"[Conn #{conn_id}] Path: {websocket.request.path if hasattr(websocket, 'request') and websocket.request else 'N/A'}")
        log.info(f"[Conn #{conn_id}] Active partition: {self.current_partition}")

        try:
            # Implement minimal Speech SDK WebSocket protocol
            # The SDK sends a speech.config message first, then audio
            async for message in websocket:
                if isinstance(message, str):
                    log.info(f"[Conn #{conn_id}] Text message ({len(message)} chars)")
                    # Parse Speech SDK protocol headers
                    if "speech.config" in message.lower():
                        log.info(f"[Conn #{conn_id}] → speech.config received")
                        # Send turn.start response
                        await self._send_turn_start(websocket, conn_id)
                    elif "speech.context" in message.lower():
                        log.info(f"[Conn #{conn_id}] → speech.context received")
                    else:
                        log.info(f"[Conn #{conn_id}] → Unknown text: {message[:100]}")
                elif isinstance(message, bytes):
                    log.info(f"[Conn #{conn_id}] Binary message ({len(message)} bytes)")
                    # Audio data — send a mock recognition result
                    await self._send_speech_hypothesis(websocket, conn_id)
        except websockets.exceptions.ConnectionClosed as e:
            log.info(f"[Conn #{conn_id}] Connection closed: {e.code} {e.reason}")
        except Exception as e:
            log.error(f"[Conn #{conn_id}] Error: {e}")

    async def _send_turn_start(self, websocket, conn_id: int):
        """Send turn.start message (minimal Speech protocol response)."""
        response = (
            "Path: turn.start\r\n"
            "X-RequestId: 00000000000000000000000000000001\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"
            '{"context":{"serviceTag":"mock-crl-test"}}'
        )
        await websocket.send(response)
        log.info(f"[Conn #{conn_id}] ← turn.start sent")

    async def _send_speech_hypothesis(self, websocket, conn_id: int):
        """Send a mock speech.hypothesis message."""
        response = (
            "Path: speech.hypothesis\r\n"
            "X-RequestId: 00000000000000000000000000000001\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"
            '{"Text":"hello","Offset":0,"Duration":10000000}'
        )
        await websocket.send(response)
        log.info(f"[Conn #{conn_id}] ← speech.hypothesis sent")

    async def run(self):
        """Start the WebSocket server with TLS."""
        self._ssl_context = self._build_ssl_context()

        # Register SIGHUP handler for cert rotation (Linux only)
        if hasattr(signal, "SIGHUP"):
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(
                signal.SIGHUP,
                lambda: self.rotate_certificate(
                    2 if self.current_partition == 1 else 1
                ),
            )
            log.info("SIGHUP handler registered (send SIGHUP to rotate cert)")

        log.info(f"Mock Speech Service starting on wss://localhost:{self.port}")
        log.info(f"  Active partition: {self.current_partition}")
        log.info(f"  CDP: http://localhost:9000/crl/partition{self.current_partition}.crl")

        async with websockets.server.serve(
            self._handle_connection,
            "127.0.0.1",
            self.port,
            ssl=self._ssl_context,
            # Allow all origins (mock server)
            origins=None,
        ) as server:
            self._server = server
            log.info(f"Server ready. Waiting for connections...")
            await asyncio.Future()  # Run forever

    async def run_with_rotation(self, rotate_after: float = 10.0):
        """Run server and automatically rotate cert after specified seconds."""
        self._ssl_context = self._build_ssl_context()

        log.info(f"Mock Speech Service starting on wss://localhost:{self.port}")
        log.info(f"  Initial partition: {self.current_partition}")
        log.info(f"  Will rotate to partition 2 after {rotate_after}s")

        async def rotation_task():
            await asyncio.sleep(rotate_after)
            self.rotate_certificate(2)

        async with websockets.server.serve(
            self._handle_connection,
            "127.0.0.1",
            self.port,
            ssl=self._ssl_context,
            origins=None,
        ) as server:
            self._server = server
            log.info(f"Server ready. Waiting for connections...")
            asyncio.create_task(rotation_task())
            await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description="Mock Speech Service HTTPS/WSS server")
    parser.add_argument("--port", type=int, default=8443, help="Listen port (default: 8443)")
    parser.add_argument("--certs-dir", type=str, default=None, help="Certificates directory")
    parser.add_argument("--partition", type=int, default=1, help="Initial cert partition (1 or 2)")
    parser.add_argument(
        "--auto-rotate",
        type=float,
        default=0,
        help="Auto-rotate cert after N seconds (0=disabled)",
    )
    args = parser.parse_args()

    server = SpeechServer(port=args.port, certs_dir=args.certs_dir)
    server.current_partition = args.partition

    if args.auto_rotate > 0:
        asyncio.run(server.run_with_rotation(rotate_after=args.auto_rotate))
    else:
        asyncio.run(server.run())


if __name__ == "__main__":
    main()

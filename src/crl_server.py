"""
crl_server.py — HTTP server that serves CRL files for partition testing.

Listens on port 9000 and serves:
  GET /crl/partition1.crl
  GET /crl/partition2.crl

Features:
  - Logs all CRL fetch requests with timestamps
  - Can block/delay specific partitions (simulates partition removal)
  - Can return 404 for decommissioned partitions
"""

import argparse
import logging
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CRL-Server] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Global state for partition availability control
_state_lock = Lock()
_blocked_partitions: set[int] = set()
_delay_seconds: dict[int, float] = {}
_request_log: list[dict] = []


class CRLHandler(BaseHTTPRequestHandler):
    certs_dir: Path = Path(__file__).parent.parent / "certs"

    def do_GET(self):
        # Parse partition from path: /crl/partitionN.crl
        if self.path.startswith("/crl/partition") and self.path.endswith(".crl"):
            try:
                part_str = self.path.replace("/crl/partition", "").replace(".crl", "")
                partition_id = int(part_str)
            except ValueError:
                self.send_error(400, "Invalid partition format")
                return

            # Log the request
            entry = {
                "time": time.time(),
                "partition": partition_id,
                "client": self.client_address[0],
            }
            with _state_lock:
                _request_log.append(entry)
                blocked = partition_id in _blocked_partitions
                delay = _delay_seconds.get(partition_id, 0)

            log.info(
                f"CRL request: partition{partition_id} from {self.client_address[0]}"
                f"{' [BLOCKED]' if blocked else ''}"
                f"{f' [DELAY {delay}s]' if delay > 0 else ''}"
            )

            # Simulate partition removal (404)
            if blocked:
                log.warning(f"  → Returning 404 (partition{partition_id} removed)")
                self.send_error(404, f"CRL partition{partition_id} not found")
                return

            # Simulate network delay
            if delay > 0:
                log.info(f"  → Delaying response by {delay}s")
                time.sleep(delay)

            # Serve CRL file
            crl_path = self.certs_dir / f"partition{partition_id}.crl"
            if not crl_path.exists():
                log.error(f"  → CRL file not found: {crl_path}")
                self.send_error(404, "CRL file not generated yet")
                return

            crl_data = crl_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pkix-crl")
            self.send_header("Content-Length", str(len(crl_data)))
            # Simulate long cache lifetime (mimics real CRL servers)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("X-Partition-Id", str(partition_id))
            self.end_headers()
            self.wfile.write(crl_data)
            log.info(f"  → Served {len(crl_data)} bytes")

        elif self.path == "/status":
            # Control endpoint: show request log
            import json

            with _state_lock:
                status = {
                    "requests": _request_log[-20:],
                    "blocked_partitions": list(_blocked_partitions),
                    "delayed_partitions": _delay_seconds,
                    "total_requests": len(_request_log),
                }
            body = json.dumps(status, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/control/block/"):
            # Control: block a partition
            part_id = int(self.path.split("/")[-1])
            with _state_lock:
                _blocked_partitions.add(part_id)
            log.warning(f"CONTROL: Blocked partition{part_id}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Blocked partition{part_id}\n".encode())

        elif self.path.startswith("/control/unblock/"):
            # Control: unblock a partition
            part_id = int(self.path.split("/")[-1])
            with _state_lock:
                _blocked_partitions.discard(part_id)
            log.info(f"CONTROL: Unblocked partition{part_id}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Unblocked partition{part_id}\n".encode())

        elif self.path.startswith("/control/delay/"):
            # Control: set delay for a partition (e.g., /control/delay/1/5.0)
            parts = self.path.split("/")
            part_id = int(parts[-2])
            delay_s = float(parts[-1])
            with _state_lock:
                if delay_s <= 0:
                    _delay_seconds.pop(part_id, None)
                else:
                    _delay_seconds[part_id] = delay_s
            log.info(f"CONTROL: Set delay for partition{part_id} = {delay_s}s")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Delay partition{part_id} = {delay_s}s\n".encode())

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # Suppress default access log (we have our own)
        pass


def get_request_log() -> list[dict]:
    """Get copy of request log (for use by orchestrator)."""
    with _state_lock:
        return list(_request_log)


def block_partition(partition_id: int):
    """Block a partition (for programmatic use by orchestrator)."""
    with _state_lock:
        _blocked_partitions.add(partition_id)
    log.warning(f"API: Blocked partition{partition_id}")


def unblock_partition(partition_id: int):
    """Unblock a partition (for programmatic use by orchestrator)."""
    with _state_lock:
        _blocked_partitions.discard(partition_id)
    log.info(f"API: Unblocked partition{partition_id}")


def reset_state():
    """Reset all state (for testing)."""
    with _state_lock:
        _blocked_partitions.clear()
        _delay_seconds.clear()
        _request_log.clear()


def run_server(port: int = 9000, certs_dir: str | None = None):
    """Start the CRL server."""
    if certs_dir:
        CRLHandler.certs_dir = Path(certs_dir)

    server = HTTPServer(("127.0.0.1", port), CRLHandler)
    log.info(f"CRL server listening on http://127.0.0.1:{port}")
    log.info(f"  CRL directory: {CRLHandler.certs_dir}")
    log.info(f"  Endpoints:")
    log.info(f"    GET /crl/partition1.crl")
    log.info(f"    GET /crl/partition2.crl")
    log.info(f"    GET /status")
    log.info(f"    GET /control/block/<N>")
    log.info(f"    GET /control/unblock/<N>")
    log.info(f"    GET /control/delay/<N>/<seconds>")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("CRL server shutting down")
        server.shutdown()

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CRL Distribution Point mock server")
    parser.add_argument("--port", type=int, default=9000, help="Listen port (default: 9000)")
    parser.add_argument("--certs-dir", type=str, default=None, help="Directory containing CRL files")
    args = parser.parse_args()
    run_server(port=args.port, certs_dir=args.certs_dir)

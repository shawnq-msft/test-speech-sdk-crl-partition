"""
reproduce.py — Full orchestrator for reproducing the Speech SDK CRL partition conflict.

This script automates the complete scenario:
  1. Starts CRL server (serves partition CRL files)
  2. Starts mock Speech Service with partition1 certificate
  3. Client connects → CRL from partition1 cached
  4. Rotates server to partition2 certificate
  5. Blocks partition1 CRL (simulates URI decommission)
  6. Client reconnects → observes CRL validation failure
  7. Tests recovery with CRL bypass

Usage:
  # Full PKI setup first (one-time):
  bash scripts/setup_all.sh

  # Run the reproduction:
  python src/reproduce.py

  # Run with Speech SDK client (requires SDK installed):
  python src/reproduce.py --use-sdk
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Orchestrator] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CERTS_DIR = PROJECT_ROOT / "certs"
CACHE_DIR = PROJECT_ROOT / "tmp_crl_cache"

sys.path.insert(0, str(Path(__file__).parent))


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> bool:
    """Wait until a port is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=1.0)
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    return False


def start_crl_server(port: int = 9000) -> subprocess.Popen:
    """Start CRL server as a subprocess."""
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "crl_server.py"), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log.info(f"CRL server starting (PID {proc.pid})...")
    if not wait_for_port(port):
        log.error("CRL server failed to start!")
        proc.terminate()
        raise RuntimeError("CRL server failed to start")
    log.info(f"CRL server ready on port {port}")
    return proc


def start_speech_server(port: int = 8443, partition: int = 1) -> subprocess.Popen:
    """Start mock Speech Service as a subprocess."""
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / "speech_server.py"),
            "--port", str(port),
            "--partition", str(partition),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log.info(f"Speech server starting (PID {proc.pid}, partition{partition})...")
    if not wait_for_port(port):
        log.error("Speech server failed to start!")
        proc.terminate()
        raise RuntimeError("Speech server failed to start")
    log.info(f"Speech server ready on port {port} (partition{partition})")
    return proc


def block_crl_partition(partition: int, crl_port: int = 9000):
    """Tell CRL server to block a partition (return 404)."""
    try:
        urlopen(f"http://127.0.0.1:{crl_port}/control/block/{partition}", timeout=2)
        log.warning(f"Blocked CRL partition{partition} → will return 404")
    except Exception as e:
        log.error(f"Failed to block partition: {e}")


def unblock_crl_partition(partition: int, crl_port: int = 9000):
    """Tell CRL server to unblock a partition."""
    try:
        urlopen(f"http://127.0.0.1:{crl_port}/control/unblock/{partition}", timeout=2)
        log.info(f"Unblocked CRL partition{partition}")
    except Exception as e:
        log.error(f"Failed to unblock partition: {e}")


def get_crl_status(crl_port: int = 9000) -> dict:
    """Get CRL server request log."""
    try:
        resp = urlopen(f"http://127.0.0.1:{crl_port}/status", timeout=2)
        return json.loads(resp.read())
    except Exception as e:
        log.error(f"Failed to get CRL status: {e}")
        return {}


def clear_crl_cache():
    """Clear the local CRL cache directory."""
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        log.info(f"Cleared CRL cache: {CACHE_DIR}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def run_raw_tls_test(scenario: str, port: int = 8443) -> dict:
    """Run raw TLS client test."""
    from test_client_raw import run_scenario
    return run_scenario(scenario=scenario, port=port)


def run_sdk_test(attempt: int, port: int = 8443, **kwargs) -> dict:
    """Run Speech SDK client test."""
    from test_client import attempt_connection, setup_environment
    setup_environment(CACHE_DIR)
    return attempt_connection(
        endpoint=f"wss://localhost:{port}",
        timeout=10.0,
        **kwargs,
    )


def print_section(title: str):
    """Print a section header."""
    log.info("")
    log.info(f"{'#'*70}")
    log.info(f"# {title}")
    log.info(f"{'#'*70}")
    log.info("")


def run_full_scenario(use_sdk: bool = False, speech_port: int = 8443, crl_port: int = 9000):
    """Run the complete CRL partition conflict reproduction scenario."""

    print_section("PHASE 0: Precondition Check")

    # Check that PKI artifacts exist
    required_files = [
        CERTS_DIR / "ca-cert.pem",
        CERTS_DIR / "ca-key.pem",
        CERTS_DIR / "server-part1-cert.pem",
        CERTS_DIR / "server-part1-key.pem",
        CERTS_DIR / "server-part2-cert.pem",
        CERTS_DIR / "server-part2-key.pem",
        CERTS_DIR / "partition1.crl",
        CERTS_DIR / "partition2.crl",
    ]
    missing = [f for f in required_files if not f.exists()]
    if missing:
        log.error("Missing PKI artifacts! Run: bash scripts/setup_all.sh")
        for f in missing:
            log.error(f"  Missing: {f}")
        return False

    log.info("All PKI artifacts present ✓")
    clear_crl_cache()

    # ─── Start servers ──────────────────────────────────────────────────
    print_section("PHASE 1: Start Servers (partition1)")

    crl_proc = start_crl_server(port=crl_port)
    speech_proc = start_speech_server(port=speech_port, partition=1)
    time.sleep(1)

    results = {}

    try:
        # ─── Step 1: Initial connection ─────────────────────────────────
        print_section("PHASE 2: Initial Connection (partition1 cert + CRL)")
        log.info("Client connects to server with partition1 certificate.")
        log.info("Expected: CRL fetched from http://localhost:9000/crl/partition1.crl")
        log.info("")

        if use_sdk:
            results["step1"] = run_sdk_test(attempt=1, port=speech_port)
        else:
            results["step1"] = run_raw_tls_test("basic", port=speech_port)

        # Check CRL server was hit
        time.sleep(0.5)
        status = get_crl_status(crl_port)
        log.info(f"CRL server requests so far: {status.get('total_requests', 0)}")

        # ─── Step 2: Rotate certificate ─────────────────────────────────
        print_section("PHASE 3: Certificate Rotation (partition1 → partition2)")
        log.info("Simulating Azure certificate rotation.")
        log.info("New cert has CDP: http://localhost:9000/crl/partition2.crl")
        log.info("")

        # Stop speech server and restart with partition2
        speech_proc.terminate()
        try:
            speech_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            speech_proc.kill()
        time.sleep(0.5)

        speech_proc = start_speech_server(port=speech_port, partition=2)
        time.sleep(1)
        log.info("Server restarted with partition2 certificate ✓")

        # ─── Step 3: Block old partition ────────────────────────────────
        print_section("PHASE 4: Decommission Old Partition")
        log.info("Blocking partition1 CRL (simulates old CDN partition removed).")
        log.info("Now: GET /crl/partition1.crl → 404")
        log.info("     GET /crl/partition2.crl → 200")
        log.info("")

        block_crl_partition(1, crl_port)

        # ─── Step 4: Client reconnects (conflict!) ──────────────────────
        print_section("PHASE 5: Client Reconnects (CRL Partition Conflict)")
        log.info("Client reconnects to server (now serving partition2 cert).")
        log.info("SDK will try to validate cert → needs CRL from partition2.")
        log.info("If SDK has stale partition1 CRL cached → potential conflict!")
        log.info("")

        if use_sdk:
            results["step4"] = run_sdk_test(attempt=2, port=speech_port)
        else:
            results["step4"] = run_raw_tls_test("stale_cache_conflict", port=speech_port)

        # Check what CRL server saw
        time.sleep(0.5)
        status = get_crl_status(crl_port)
        log.info(f"CRL server total requests: {status.get('total_requests', 0)}")
        log.info(f"Blocked partitions: {status.get('blocked_partitions', [])}")

        # ─── Step 5: Recovery with bypass ───────────────────────────────
        print_section("PHASE 6: Recovery (CRL Check Bypass)")
        log.info("Testing recovery: disable CRL check to restore connectivity.")
        log.info("SDK property: OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true")
        log.info("")

        if use_sdk:
            results["step5"] = run_sdk_test(
                attempt=3,
                port=speech_port,
                continue_on_crl_failure=True,
            )
        else:
            results["step5"] = run_raw_tls_test("recovery_with_bypass", port=speech_port)

        # ─── Summary ────────────────────────────────────────────────────
        print_section("SUMMARY")
        log.info("Scenario Results:")
        log.info(f"  Step 1 (initial connect):   {results['step1'].get('status', '?')}")
        log.info(f"  Step 4 (after rotation):    {results['step4'].get('status', '?')}")
        log.info(f"  Step 5 (CRL bypass):        {results['step5'].get('status', '?')}")
        log.info("")

        step4_status = results["step4"].get("status", "")
        if step4_status in ("cert_verification_error", "canceled", "ssl_error"):
            log.info("✓ CRL PARTITION CONFLICT REPRODUCED!")
            log.info("  The stale CRL cache caused a connection failure after rotation.")
        elif step4_status == "connected":
            log.info("⚠ Connection succeeded after rotation.")
            log.info("  Possible reasons:")
            log.info("  - CRL check not enforced in this configuration")
            log.info("  - Both CRLs from same CA → both valid for all certs")
            log.info("  - To force conflict: revoke partition2 cert only in partition1 scope")
        else:
            log.info(f"? Unexpected result: {step4_status}")

        log.info("")
        final_status = get_crl_status(crl_port)
        log.info(f"CRL Server Stats:")
        log.info(f"  Total requests: {final_status.get('total_requests', 0)}")
        log.info(f"  Blocked: {final_status.get('blocked_partitions', [])}")

        return True

    finally:
        # Cleanup
        log.info("\nCleaning up processes...")
        speech_proc.terminate()
        crl_proc.terminate()
        try:
            speech_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            speech_proc.kill()
        try:
            crl_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            crl_proc.kill()
        log.info("Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Reproduce Speech SDK CRL partition caching conflict"
    )
    parser.add_argument(
        "--use-sdk",
        action="store_true",
        help="Use actual Speech SDK client (requires azure-cognitiveservices-speech)",
    )
    parser.add_argument("--speech-port", type=int, default=8443)
    parser.add_argument("--crl-port", type=int, default=9000)
    args = parser.parse_args()

    log.info("╔══════════════════════════════════════════════════════════════════╗")
    log.info("║  Speech SDK CRL Partition Caching Conflict — Reproduction Tool  ║")
    log.info("╚══════════════════════════════════════════════════════════════════╝")
    log.info("")
    log.info(f"Mode: {'Speech SDK' if args.use_sdk else 'Raw TLS'}")
    log.info(f"Speech port: {args.speech_port}")
    log.info(f"CRL port: {args.crl_port}")
    log.info("")

    success = run_full_scenario(
        use_sdk=args.use_sdk,
        speech_port=args.speech_port,
        crl_port=args.crl_port,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

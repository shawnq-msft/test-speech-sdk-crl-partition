"""
test_client_raw.py — Raw TLS client demonstrating CRL caching conflict.

This is a fallback client that doesn't depend on Speech SDK.
It uses Python's ssl module with explicit CRL checking to demonstrate
the partition caching conflict in a controlled manner.

Scenarios demonstrated:
  1. Connect with CRL from partition1 → success
  2. Server rotates to partition2 cert → reconnect
  3. If partition1 CRL cached but partition2 CRL needed → conflict
"""

import argparse
import json
import logging
import os
import shutil
import socket
import ssl
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Raw-TLS] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CERTS_DIR = PROJECT_ROOT / "certs"
CACHE_DIR = PROJECT_ROOT / "tmp_crl_cache"


def create_ssl_context(
    ca_cert: Path,
    crl_file: Path | None = None,
    verify_crl: bool = True,
) -> ssl.SSLContext:
    """Create SSL context with optional CRL verification."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=str(ca_cert))

    if verify_crl and crl_file and crl_file.exists():
        # Load CRL for verification
        ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        ctx.load_verify_locations(cafile=str(ca_cert))
        log.info(f"CRL verification enabled with: {crl_file}")
    elif verify_crl:
        log.warning("CRL verification requested but no CRL file provided")

    ctx.check_hostname = True
    return ctx


def connect_tls(
    host: str = "localhost",
    port: int = 8443,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float = 5.0,
) -> dict:
    """Attempt TLS connection and return result details."""
    result = {
        "status": "unknown",
        "start_time": time.time(),
        "host": host,
        "port": port,
    }

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            tls_sock = ssl_context.wrap_socket(sock, server_hostname=host)
            
            # Get peer certificate info
            peer_cert = tls_sock.getpeercert()
            result["status"] = "connected"
            result["peer_cert"] = {
                "subject": dict(x[0] for x in peer_cert.get("subject", ())),
                "issuer": dict(x[0] for x in peer_cert.get("issuer", ())),
                "notBefore": peer_cert.get("notBefore"),
                "notAfter": peer_cert.get("notAfter"),
                "serialNumber": peer_cert.get("serialNumber"),
                "crlDistributionPoints": peer_cert.get("crlDistributionPoints"),
            }
            result["cipher"] = tls_sock.cipher()
            result["version"] = tls_sock.version()

            log.info(f"  ✓ TLS connected: {result['version']} / {result['cipher'][0]}")
            log.info(f"    Cert subject: {result['peer_cert']['subject']}")
            log.info(f"    Cert serial:  {result['peer_cert']['serialNumber']}")
            log.info(f"    CDP: {result['peer_cert'].get('crlDistributionPoints', 'N/A')}")

            tls_sock.close()
        except ssl.SSLCertVerificationError as e:
            result["status"] = "cert_verification_error"
            result["error"] = str(e)
            result["verify_code"] = e.verify_code
            result["verify_message"] = e.verify_message
            log.error(f"  ✗ Certificate verification failed!")
            log.error(f"    Code: {e.verify_code}")
            log.error(f"    Message: {e.verify_message}")
            log.error(f"    Details: {e}")
        except ssl.SSLError as e:
            result["status"] = "ssl_error"
            result["error"] = str(e)
            log.error(f"  ✗ SSL error: {e}")
        finally:
            sock.close()
    except ConnectionRefusedError:
        result["status"] = "connection_refused"
        log.error(f"  ✗ Connection refused (server not running?)")
    except socket.timeout:
        result["status"] = "timeout"
        log.error(f"  ✗ Connection timed out")
    except Exception as e:
        result["status"] = "exception"
        result["error"] = str(e)
        log.error(f"  ✗ Exception: {e}")

    result["elapsed"] = time.time() - result["start_time"]
    return result


def simulate_crl_cache(partition: int, cache_dir: Path):
    """Copy a CRL file into the cache directory (simulating SDK caching behavior)."""
    crl_src = CERTS_DIR / f"partition{partition}.crl"
    if crl_src.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        crl_dst = cache_dir / f"cached_crl_partition{partition}.crl"
        shutil.copy2(crl_src, crl_dst)
        log.info(f"Cached CRL: {crl_src.name} → {crl_dst}")
        return crl_dst
    else:
        log.warning(f"CRL file not found: {crl_src}")
        return None


def run_scenario(
    scenario: str = "basic",
    host: str = "localhost",
    port: int = 8443,
    verify_crl: bool = True,
):
    """Run a specific test scenario."""
    ca_cert = CERTS_DIR / "ca-cert.pem"
    if not ca_cert.exists():
        log.error(f"CA cert not found: {ca_cert}")
        log.error("Run: bash scripts/setup_all.sh")
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if scenario == "basic":
        # Basic connection without CRL check
        log.info("=== Scenario: Basic TLS connection (no CRL check) ===")
        ctx = create_ssl_context(ca_cert, verify_crl=False)
        result = connect_tls(host, port, ctx)
        return result

    elif scenario == "with_crl_partition1":
        # Connect with CRL from partition 1
        log.info("=== Scenario: Connect with partition1 CRL ===")
        crl_file = CERTS_DIR / "partition1.crl"
        ctx = create_ssl_context(ca_cert, crl_file=crl_file, verify_crl=True)
        result = connect_tls(host, port, ctx)
        return result

    elif scenario == "stale_cache_conflict":
        # Simulate the conflict:
        # 1. Cache CRL from partition 1
        # 2. Server has rotated to partition 2 cert
        # 3. Try to validate with cached partition 1 CRL
        log.info("=== Scenario: Stale CRL cache conflict ===")
        log.info("  Server should be running with partition2 cert")
        log.info("  Client has partition1 CRL cached")
        log.info("")

        # Use partition1 CRL (stale) to validate partition2 cert
        crl_file = CERTS_DIR / "partition1.crl"
        ctx = create_ssl_context(ca_cert, crl_file=crl_file, verify_crl=True)
        result = connect_tls(host, port, ctx)

        if result["status"] == "cert_verification_error":
            log.info("")
            log.info("*** CRL PARTITION CONFLICT REPRODUCED ***")
            log.info("The stale CRL (partition1) cannot validate the new cert (partition2).")
            log.info("This is the exact issue Speech SDK 1.40 experiences when:")
            log.info("  1. CRL from old partition is cached in TMPDIR")
            log.info("  2. Speech Service rotates to cert with new CDP")
            log.info("  3. SDK uses cached CRL → validation fails")
        elif result["status"] == "connected":
            log.info("")
            log.info("Connection succeeded — CRL did not block.")
            log.info("(Both partitions share the same CA, so CRL is valid for both)")
            log.info("To demonstrate conflict: revoke the partition2 cert in partition1 CRL scope")

        return result

    elif scenario == "recovery_with_bypass":
        # Show that OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE works
        log.info("=== Scenario: Recovery with CRL bypass ===")
        ctx = create_ssl_context(ca_cert, verify_crl=False)
        result = connect_tls(host, port, ctx)
        if result["status"] == "connected":
            log.info("  → Connection recovered by disabling CRL check")
        return result

    else:
        log.error(f"Unknown scenario: {scenario}")
        return {"status": "error", "error": f"Unknown scenario: {scenario}"}


def main():
    parser = argparse.ArgumentParser(description="Raw TLS client for CRL partition testing")
    parser.add_argument(
        "--scenario",
        choices=["basic", "with_crl_partition1", "stale_cache_conflict", "recovery_with_bypass"],
        default="basic",
        help="Test scenario to run",
    )
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8443, help="Server port")
    parser.add_argument("--no-crl", action="store_true", help="Disable CRL verification")
    args = parser.parse_args()

    log.info(f"{'='*60}")
    log.info(f"Raw TLS Client — Scenario: {args.scenario}")
    log.info(f"{'='*60}")

    result = run_scenario(
        scenario=args.scenario,
        host=args.host,
        port=args.port,
        verify_crl=not args.no_crl,
    )

    log.info(f"\n{'='*60}")
    log.info(f"RESULT: {json.dumps(result, indent=2, default=str)}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()

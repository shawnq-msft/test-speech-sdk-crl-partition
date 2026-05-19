"""
test_client.py — Speech SDK client that connects to the mock Speech Service.

Demonstrates CRL caching behavior:
  1. Connects to wss://localhost:8443 using Speech SDK
  2. Uses custom CA trust (our test CA)
  3. CRL is fetched from http://localhost:9000/crl/partitionN.crl
  4. CRL is cached in $TMPDIR (controlled directory for observation)

Usage:
  python src/test_client.py --attempt 1   # First connection (cache miss)
  python src/test_client.py --attempt 2   # After rotation (potential cache conflict)
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SDK-Client] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CERTS_DIR = PROJECT_ROOT / "certs"
CACHE_DIR = PROJECT_ROOT / "tmp_crl_cache"


def setup_environment(cache_dir: Path):
    """Configure environment for CRL caching control."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Speech SDK on Linux uses TMPDIR for CRL cache
    os.environ["TMPDIR"] = str(cache_dir)
    os.environ["TMP"] = str(cache_dir)

    # Point OpenSSL to our custom CA
    ca_cert = CERTS_DIR / "ca-cert.pem"
    if ca_cert.exists():
        os.environ["SSL_CERT_FILE"] = str(ca_cert)
        log.info(f"SSL_CERT_FILE = {ca_cert}")

    log.info(f"TMPDIR = {cache_dir} (CRL cache location)")
    log.info(f"Cache contents before connection: {list(cache_dir.iterdir())}")


def list_cache_contents(cache_dir: Path) -> list[str]:
    """List all files in the CRL cache directory."""
    if not cache_dir.exists():
        return []
    files = []
    for f in cache_dir.rglob("*"):
        if f.is_file():
            stat = f.stat()
            files.append(f"{f.relative_to(cache_dir)} ({stat.st_size} bytes, mtime={time.ctime(stat.st_mtime)})")
    return files


def attempt_connection(
    endpoint: str = "wss://localhost:8443",
    subscription_key: str = "mock-key-not-used",
    region: str = "local",
    continue_on_crl_failure: bool = False,
    disable_crl_check: bool = False,
    timeout: float = 10.0,
    sdk_log_file: str | None = None,
):
    """Attempt to connect to the mock Speech Service using Speech SDK."""
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        log.error("azure-cognitiveservices-speech not installed!")
        log.error("  pip install azure-cognitiveservices-speech==1.40.0")
        return {"status": "import_error", "error": "SDK not installed"}

    log.info(f"Speech SDK version: {speechsdk.__version__}")
    log.info(f"Connecting to: {endpoint}")

    # Create config with endpoint override
    speech_config = speechsdk.SpeechConfig(
        subscription=subscription_key,
        endpoint=endpoint,
    )

    if sdk_log_file:
        speech_config.set_property(
            speechsdk.PropertyId.Speech_LogFilename,
            sdk_log_file,
        )
        log.info(f"  SDK native log file: {sdk_log_file}")

    # CRL behavior configuration
    if continue_on_crl_failure:
        speech_config.set_property_by_name(
            "OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE", "true"
        )
        log.info("  CRL download failure: CONTINUE")
    
    if disable_crl_check:
        speech_config.set_property_by_name(
            "OPENSSL_DISABLE_CRL_CHECK", "true"
        )
        log.info("  CRL check: DISABLED")

    # Connection attempt
    result = {"status": "unknown", "start_time": time.time()}

    # Use speech recognizer with audio from file (or no audio for connection test)
    audio_config = speechsdk.audio.AudioConfig(
        stream=speechsdk.audio.PushAudioInputStream()
    )
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    # Track connection events. SpeechRecognizer itself does not expose
    # connected/disconnected signals in Speech SDK 1.40; those are on the
    # Connection object returned by Connection.from_recognizer().
    connection_established = False
    connection_error = None
    canceled_reason = None

    connection = speechsdk.Connection.from_recognizer(recognizer)

    def on_connected(evt):
        nonlocal connection_established
        connection_established = True
        log.info(f"  ✓ Connected! (event: {evt})")

    def on_disconnected(evt):
        log.info(f"  ✗ Disconnected (event: {evt})")

    def on_canceled(evt):
        nonlocal canceled_reason
        cancellation = evt.result.cancellation_details
        canceled_reason = {
            "reason": str(cancellation.reason),
            "error_code": str(cancellation.error_code),
            "error_details": cancellation.error_details,
        }
        log.warning(f"  ✗ Canceled: {cancellation.reason}")
        log.warning(f"    Error: {cancellation.error_code}")
        log.warning(f"    Details: {cancellation.error_details}")

    connection.connected.connect(on_connected)
    connection.disconnected.connect(on_disconnected)
    recognizer.canceled.connect(on_canceled)

    log.info("Starting connection attempt...")
    start = time.time()

    try:
        # Start recognition (triggers connection)
        recognizer.start_continuous_recognition()
        
        # Wait for connection or timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            if connection_established or canceled_reason:
                break
            time.sleep(0.1)

        elapsed = time.time() - start

        if connection_established:
            result["status"] = "connected"
            result["elapsed"] = elapsed
            log.info(f"  Connection successful in {elapsed:.2f}s")
        elif canceled_reason:
            result["status"] = "canceled"
            result["canceled"] = canceled_reason
            result["elapsed"] = elapsed
            log.error(f"  Connection failed in {elapsed:.2f}s")
        else:
            result["status"] = "timeout"
            result["elapsed"] = timeout
            log.error(f"  Connection timed out after {timeout}s")

    except Exception as e:
        result["status"] = "exception"
        result["error"] = str(e)
        log.error(f"  Exception: {e}")
    finally:
        try:
            recognizer.stop_continuous_recognition()
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser(description="Speech SDK CRL test client")
    parser.add_argument("--attempt", type=int, default=1, help="Attempt number (for logging)")
    parser.add_argument("--endpoint", default="wss://localhost:8443", help="Speech service endpoint")
    parser.add_argument("--timeout", type=float, default=10.0, help="Connection timeout (seconds)")
    parser.add_argument("--continue-on-crl-failure", action="store_true", help="Set OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE")
    parser.add_argument("--disable-crl", action="store_true", help="Disable CRL check entirely")
    parser.add_argument("--sdk-log-file", default=None, help="Speech SDK native log file path")
    parser.add_argument("--cache-dir", type=str, default=None, help="CRL cache directory")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else CACHE_DIR

    log.info(f"{'='*60}")
    log.info(f"Speech SDK CRL Test — Attempt #{args.attempt}")
    log.info(f"{'='*60}")

    # Setup environment
    setup_environment(cache_dir)

    # Show cache state before
    cache_before = list_cache_contents(cache_dir)
    log.info(f"Cache before: {len(cache_before)} files")
    for f in cache_before:
        log.info(f"  {f}")

    # Attempt connection
    result = attempt_connection(
        endpoint=args.endpoint,
        continue_on_crl_failure=args.continue_on_crl_failure,
        disable_crl_check=args.disable_crl,
        timeout=args.timeout,
        sdk_log_file=args.sdk_log_file,
    )

    # Show cache state after
    cache_after = list_cache_contents(cache_dir)
    log.info(f"Cache after: {len(cache_after)} files")
    for f in cache_after:
        log.info(f"  {f}")

    # New files in cache
    new_files = set(cache_after) - set(cache_before)
    if new_files:
        log.info(f"New cache entries: {new_files}")

    # Summary
    log.info(f"\n{'='*60}")
    log.info(f"RESULT: {result['status']}")
    log.info(f"{'='*60}")

    return result


if __name__ == "__main__":
    main()

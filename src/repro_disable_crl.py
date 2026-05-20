"""
repro_disable_crl.py — Azure Speech SDK CRL failure then disable-CRL recovery.

This orchestrator focuses on the authentic Speech SDK behavior requested in the
Microsoft Learn CRL compatibility guidance:

  1. Start CRL server and mock Speech server with partition1 certificate.
  2. Run Speech SDK connection with CRL checking enabled.
  3. Rotate mock Speech server to partition2 certificate.
  4. Block old partition1 CRL endpoint.
  5. Run Speech SDK connection with CRL checking enabled and capture the
     OpenSSL rejection / SDK failure evidence.
  6. Run the same Speech SDK connection with OPENSSL_DISABLE_CRL_CHECK=true
     and verify that connection succeeds.

The Speech SDK native logs are written to reports/logs/sdk-native-*.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from reproduce import (
    CACHE_DIR,
    CERTS_DIR,
    get_crl_status,
    print_section,
    start_crl_server,
    start_speech_server,
    wait_for_port,
)
from test_client import attempt_connection, setup_environment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Disable-CRL-Repro] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
REPORT_LOG_DIR = PROJECT_ROOT / "reports" / "logs"


def clear_crl_cache() -> None:
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        log.info("Cleared CRL cache: %s", CACHE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def block_crl_partition(partition: int, crl_port: int) -> None:
    urlopen(f"http://127.0.0.1:{crl_port}/control/block/{partition}", timeout=2)
    log.warning("Blocked CRL partition%s → will return 404", partition)


def run_sdk_attempt(label: str, speech_port: int, *, disable_crl: bool, timeout: float) -> dict:
    REPORT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    sdk_log_file = REPORT_LOG_DIR / f"sdk-native-{label}.log"
    if sdk_log_file.exists():
        sdk_log_file.unlink()

    setup_environment(CACHE_DIR)
    result = attempt_connection(
        endpoint=f"wss://localhost:{speech_port}",
        timeout=timeout,
        disable_crl_check=disable_crl,
        sdk_log_file=str(sdk_log_file),
    )
    result["sdk_log_file"] = str(sdk_log_file)
    return result


def summarize_native_log(path: str) -> None:
    p = Path(path)
    if not p.exists():
        log.warning("SDK native log not found: %s", p)
        return
    text = p.read_text(errors="replace")
    log.info("SDK native log: %s (%d bytes)", p, len(text.encode()))
    interesting = []
    needles = (
        "OPENSSL",
        "CRL",
        "X509",
        "CERTIFICATE",
        "WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED",
        "error",
        "failed",
    )
    for line in text.splitlines():
        if any(n.lower() in line.lower() for n in needles):
            interesting.append(line)
    if interesting:
        log.info("SDK native log interesting lines (last 40):")
        for line in interesting[-40:]:
            log.info("  %s", line)
    else:
        log.info("No OpenSSL/CRL/error keywords found in native log.")


def run_scenario(speech_port: int, crl_port: int, timeout: float, expect_failure: bool = True) -> bool:
    print_section("PHASE 0: Precondition Check")
    required_files = [
        CERTS_DIR / "ca-cert.pem",
        CERTS_DIR / "server-part1-cert.pem",
        CERTS_DIR / "server-part1-key.pem",
        CERTS_DIR / "server-part2-cert.pem",
        CERTS_DIR / "server-part2-key.pem",
        CERTS_DIR / "partition1.crl",
        CERTS_DIR / "partition2.crl",
    ]
    missing = [str(p) for p in required_files if not p.exists()]
    if missing:
        log.error("Missing PKI artifacts. Run: bash scripts/setup_all.sh")
        log.error("Missing: %s", missing)
        return False
    log.info("All PKI artifacts present ✓")
    clear_crl_cache()

    crl_proc = start_crl_server(port=crl_port)
    speech_proc = start_speech_server(port=speech_port, partition=1)
    time.sleep(1)

    results: dict[str, dict] = {}
    try:
        print_section("PHASE 1: SDK Initial Connection With CRL Checking Enabled")
        results["initial_crl_enabled"] = run_sdk_attempt(
            "initial-crl-enabled",
            speech_port,
            disable_crl=False,
            timeout=timeout,
        )
        summarize_native_log(results["initial_crl_enabled"]["sdk_log_file"])
        log.info("CRL server status after initial attempt: %s", json.dumps(get_crl_status(crl_port), indent=2))

        print_section("PHASE 2: Rotate Certificate To Partition2")
        speech_proc.terminate()
        try:
            speech_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            speech_proc.kill()
        time.sleep(0.5)
        speech_proc = start_speech_server(port=speech_port, partition=2)
        time.sleep(1)
        log.info("Server restarted with partition2 certificate ✓")

        print_section("PHASE 3: Block Old CRL Partition1")
        block_crl_partition(1, crl_port)
        log.info("CRL server status after block: %s", json.dumps(get_crl_status(crl_port), indent=2))

        print_section("PHASE 4: Reproduce SDK/OpenSSL Failure With CRL Checking Enabled")
        results["after_rotation_crl_enabled"] = run_sdk_attempt(
            "after-rotation-crl-enabled",
            speech_port,
            disable_crl=False,
            timeout=timeout,
        )
        summarize_native_log(results["after_rotation_crl_enabled"]["sdk_log_file"])
        log.info("CRL server status after failure attempt: %s", json.dumps(get_crl_status(crl_port), indent=2))

        print_section("PHASE 5: Disable CRL Checking And Try Again")
        log.info("Applying Microsoft Learn workaround: OPENSSL_DISABLE_CRL_CHECK=true")
        results["after_rotation_crl_disabled"] = run_sdk_attempt(
            "after-rotation-crl-disabled",
            speech_port,
            disable_crl=True,
            timeout=timeout,
        )
        summarize_native_log(results["after_rotation_crl_disabled"]["sdk_log_file"])
        log.info("CRL server status after disable-CRL attempt: %s", json.dumps(get_crl_status(crl_port), indent=2))

        print_section("SUMMARY")
        for key, value in results.items():
            log.info("%s: status=%s elapsed=%s sdk_log=%s", key, value.get("status"), value.get("elapsed"), value.get("sdk_log_file"))

        failure_status = results["after_rotation_crl_enabled"].get("status")
        disabled_status = results["after_rotation_crl_disabled"].get("status")
        if expect_failure:
            if failure_status != "connected" and disabled_status == "connected":
                log.info("✓ Reproduced SDK/OpenSSL failure with CRL checking enabled and recovered with OPENSSL_DISABLE_CRL_CHECK=true")
                return True
            log.warning("Expected enabled attempt to fail and disabled attempt to connect; observed enabled=%s disabled=%s", failure_status, disabled_status)
            return False

        if failure_status == "connected" and disabled_status == "connected":
            log.info("✓ CRL checking enabled path connected; disable-CRL path also connected")
            return True

        log.warning("Expected both enabled and disabled attempts to connect; observed enabled=%s disabled=%s", failure_status, disabled_status)
        return False
    finally:
        log.info("\nCleaning up processes...")
        speech_proc.terminate()
        crl_proc.terminate()
        for proc in (speech_proc, crl_proc):
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.info("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce Speech SDK CRL failure then disable CRL checking")
    parser.add_argument("--speech-port", type=int, default=8443)
    parser.add_argument("--crl-port", type=int, default=9000)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--expect-success-with-crl",
        action="store_true",
        help="Pass when validating a fixed harness where CRL checking should succeed",
    )
    args = parser.parse_args()

    success = run_scenario(
        args.speech_port,
        args.crl_port,
        args.timeout,
        expect_failure=not args.expect_success_with_crl,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

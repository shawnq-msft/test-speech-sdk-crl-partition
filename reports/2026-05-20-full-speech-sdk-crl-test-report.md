# Azure Speech SDK CRL Partition Full Test Report

Date: 2026-05-20T13:48:52+08:00
Repository: shawnq-msft/test-speech-sdk-crl-partition
Environment: WSL Linux, Python venv `.venv`, Azure Speech SDK for Python `azure-cognitiveservices-speech==1.40.0`

## Purpose

Run the full Azure Speech SDK reproduction requested for the CRL partition/cache scenario:

1. Start with a clean local CRL cache and a mock Speech endpoint using the partition1 TLS certificate.
2. Confirm the first CRL-enabled Speech SDK connection succeeds. This first phase should not be an SSL failure; it only primes the local SDK/OpenSSL CRL cache with partition1 CRL data.
3. Rotate the mock Speech endpoint to a partition2 certificate.
4. Keep both CRL endpoints reachable. This test does not disable, delay, or 404 partition1.
5. Reconnect with CRL checking still enabled and verify the SDK/OpenSSL failure caused by stale local CRL cache vs the rotated certificate's partition2 CDP/scope.
6. Reconnect with `OPENSSL_DISABLE_CRL_CHECK=true` and verify the Microsoft Learn mitigation restores connectivity.

## Important correction from the previous run

The earlier report incorrectly showed Phase 1 as an SSL verification failure. That was a harness issue, not the intended scenario.

Root cause: the Speech SDK/OpenSSL path enables CRL checking for the chain. The test CA is self-signed, so the CA certificate also needed a CDP compatible with the initial partition1 CRL. Without that, the first connection could fail before the partition-switch scenario was exercised.

Harness fix now applied:

- The local test CA certificate includes `crlDistributionPoints = URI:http://localhost:9000/crl/partition1.crl`.
- The generated CRLs remain DER-encoded.
- Each partition CRL includes an Issuing Distribution Point URI:
  - partition1 CRL: `http://localhost:9000/crl/partition1.crl`
  - partition2 CRL: `http://localhost:9000/crl/partition2.crl`
- No CRL endpoint is blocked during the switch-partition test.
- The repro runner now fails the run if the initial CRL-enabled connection does not connect.

## Commands run

```bash
rm -rf certs tmp_crl_cache
. .venv/bin/activate
bash scripts/setup_all.sh > reports/logs/full_test_setup.log 2>&1

python -m py_compile src/repro_disable_crl.py src/test_client.py
rm -rf tmp_crl_cache
python src/repro_disable_crl.py --timeout 10 \
  2>&1 | tee reports/logs/full_test_speech_sdk.log
```

## Setup validation

Setup log: `reports/logs/full_test_setup.log`

OpenSSL sanity checks appended to the setup log:

```text
OpenSSL sanity check after CA CDP + IDP URI scope:
certs/server-part1-cert.pem: OK
certs/server-part1-cert.pem: OK
C = US, O = Speech SDK CRL Test, CN = localhost
error 44 at 0 depth lookup: different CRL scope
error certs/server-part2-cert.pem: verification failed
```

Meaning:

- partition1 certificate validates with partition1 CRL.
- a rotated partition2 certificate does not validate against stale partition1 CRL because the CRL scope is different.
- this confirms the harness can reproduce the intended stale-cache/CDP-scope conflict without relying on a 404.

## Phase 1 — initial connection with CRL checking enabled

Observed public SDK result:

```text
initial_crl_enabled: status=connected elapsed=0.10162043571472168
```

Native SDK evidence from `reports/logs/sdk-native-initial-crl-enabled.log`:

```text
tlsio_openssl.c:2027 create_openssl_instance by TLS_method.
tlsio_openssl.c:1849 load_system_store not implemented on this platform
tlsio_openssl.c:1882 CRL check enabled.
```

The local CRL server was reached for partition1, and the SDK cached the fetched CRL under `tmp_crl_cache/ec1457bb.crl.0`:

```text
CRL server status after initial attempt: {
  "requests": [
    {
      "partition": 1,
      "client": "127.0.0.1"
    }
  ],
  "blocked_partitions": [],
  "delayed_partitions": {},
  "total_requests": 1
}
```

Conclusion for Phase 1: the first CRL-enabled SDK connection is now normal. It connects successfully and primes the local CRL cache.

## Phase 2 — switch Speech endpoint to partition2 certificate

The mock Speech server was restarted with the partition2 TLS certificate:

```text
PHASE 2: Rotate Certificate To Partition2
Speech server starting (..., partition2)...
Speech server ready on port 8443 (partition2)
Server restarted with partition2 certificate ✓
```

The partition2 certificate's CDP points to:

```text
http://localhost:9000/crl/partition2.crl
```

## Phase 3 — keep both CRL endpoints reachable

This is the key correction: partition1 was not blocked.

Observed log:

```text
No CRL endpoint is blocked or disabled in this test.
Verified partition1 CRL endpoint reachable: HTTP 200, 771 bytes
Verified partition2 CRL endpoint reachable: HTTP 200, 771 bytes
```

CRL server status before the after-rotation attempt:

```text
"blocked_partitions": [],
"delayed_partitions": {},
"total_requests": 3
```

Conclusion for Phase 3: both CRL files were reachable. The after-rotation failure is not caused by HTTP 404 or CRL server unavailability.

## Phase 4 — after rotation, CRL checking still enabled

Observed public SDK result:

```text
after_rotation_crl_enabled: status=timeout elapsed=10.0
```

Native SDK evidence from `reports/logs/sdk-native-after-rotation-crl-enabled.log`:

```text
tlsio_openssl.c:2027 create_openssl_instance by TLS_method.
tlsio_openssl.c:1849 load_system_store not implemented on this platform
tlsio_openssl.c:1882 CRL check enabled.
tlsio_openssl.c:691 error:0A000086:SSL routines::certificate verify failed
tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED)
```

CRL server status after this failure still shows no blocked partition and no extra partition2 fetch by the SDK during the failed attempt:

```text
"blocked_partitions": [],
"delayed_partitions": {},
"total_requests": 3
```

Interpretation:

- The initial connection cached partition1 CRL locally as `tmp_crl_cache/ec1457bb.crl.0`.
- After server certificate rotation, the endpoint presents a partition2 certificate whose CDP/scope differs.
- The SDK/OpenSSL path uses the stale local CRL cache instead of successfully refreshing to the partition2 CRL for that verification attempt.
- OpenSSL rejects the TLS handshake with certificate verification failure.
- The public Python SDK waits until timeout because the connection event never succeeds.

## Phase 5 — mitigation with `OPENSSL_DISABLE_CRL_CHECK=true`

Observed public SDK result:

```text
after_rotation_crl_disabled: status=connected elapsed=0.10134553909301758
```

Native SDK evidence from `reports/logs/sdk-native-after-rotation-crl-disabled.log`:

```text
name='OPENSSL_DISABLE_CRL_CHECK'; value='true'
tlsio_openssl.c:2027 create_openssl_instance by TLS_method.
tlsio_openssl.c:1849 load_system_store not implemented on this platform
tlsio_openssl.c:1878 CRL check off, as requested.
```

Conclusion for Phase 5: setting `OPENSSL_DISABLE_CRL_CHECK=true` mitigates the partition-switch failure and restores SDK connectivity.

## Final result

```text
initial_crl_enabled: status=connected elapsed=0.10162043571472168
after_rotation_crl_enabled: status=timeout elapsed=10.0
after_rotation_crl_disabled: status=connected elapsed=0.10134553909301758
✓ Initial CRL-enabled connection succeeded; after rotation reproduced SDK/OpenSSL failure; OPENSSL_DISABLE_CRL_CHECK=true recovered connectivity
```

## Evidence files

- `reports/logs/full_test_setup.log`
- `reports/logs/full_test_speech_sdk.log`
- `reports/logs/sdk-native-initial-crl-enabled.log`
- `reports/logs/sdk-native-after-rotation-crl-enabled.log`
- `reports/logs/sdk-native-after-rotation-crl-disabled.log`

Sensitive SDK property values in the native logs were redacted before commit.

## Conclusion

The corrected full test now matches the expected model:

1. Initial CRL-enabled Speech SDK connection succeeds.
2. Both partition CRL endpoints remain reachable during certificate rotation.
3. After rotation, the SDK/OpenSSL path fails while CRL checking is enabled, consistent with stale local CRL cache vs changed certificate CDP/scope.
4. `OPENSSL_DISABLE_CRL_CHECK=true` mitigates the failure and reconnects successfully.

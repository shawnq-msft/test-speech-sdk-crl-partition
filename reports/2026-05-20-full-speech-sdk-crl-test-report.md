# Azure Speech SDK CRL Partition Full Test Report

Date: 2026-05-20T10:38:00+08:00
Repository: shawnq-msft/test-speech-sdk-crl-partition
Environment: WSL Linux, Python venv `.venv`, Azure Speech SDK for Python 1.40.0, OpenSSL 3.0.13

## Purpose

Run a clean full test using the authentic Azure Speech SDK path only:

1. Create fresh local CA, two localhost server certificates, and two CRL partitions.
2. Verify the CRL artifacts are real partition-scoped DER CRLs.
3. Run the Speech SDK connection path with CRL checking enabled and confirm the OpenSSL/Speech SDK failure is reproduced.
4. Run the same connection path with `OPENSSL_DISABLE_CRL_CHECK=true` and confirm this mitigates the failure.

## Important harness detail

The CRLs are DER-encoded and now include partition-specific Issuing Distribution Point extensions:

- `partition1.crl` has IDP `URI:http://localhost:9000/crl/partition1.crl`
- `partition2.crl` has IDP `URI:http://localhost:9000/crl/partition2.crl`

This is required to make the stale-CRL-cache test meaningful. OpenSSL now treats a partition1 CRL as out of scope for a partition2 certificate.

Direct OpenSSL sanity check after setup:

```text
verify partition1 cert with partition1 CRL:
certs/server-part1-cert.pem: OK

verify partition2 cert with stale partition1 CRL:
C = US, O = Speech SDK CRL Test, CN = localhost
error 44 at 0 depth lookup: different CRL scope
error certs/server-part2-cert.pem: verification failed

verify partition2 cert with partition2 CRL:
certs/server-part2-cert.pem: OK
```

## Commands run

```bash
rm -rf certs tmp_crl_cache
. .venv/bin/activate
bash scripts/setup_all.sh 2>&1 | tee reports/logs/full_test_setup.log
python src/repro_disable_crl.py --timeout 10 2>&1 | tee reports/logs/full_test_speech_sdk.log
```

## Setup result

The fresh setup succeeded and generated two partitioned DER CRLs.

Evidence from `reports/logs/full_test_setup.log`:

```text
=== Generating CRL files ===
Using configuration from .../certs/openssl.cnf
[OK] partition1.crl generated (DER)
Using configuration from .../certs/openssl.cnf
[OK] partition2.crl generated (DER)

--- partition1.crl info ---
        Issuer: CN = Test CRL Partition CA, O = Speech SDK CRL Test, C = US
        Last Update: May 20 02:35:05 2026 GMT
        Next Update: Jun 19 02:35:05 2026 GMT
            X509v3 Issuing Distribution Point: critical
                Full Name:
                  URI:http://localhost:9000/crl/partition1.crl

--- partition2.crl info ---
        Issuer: CN = Test CRL Partition CA, O = Speech SDK CRL Test, C = US
        Last Update: May 20 02:35:05 2026 GMT
        Next Update: Jun 19 02:35:05 2026 GMT
            X509v3 Issuing Distribution Point: critical
                Full Name:
                  URI:http://localhost:9000/crl/partition2.crl
```

## Full Speech SDK test flow

The full test used `src/repro_disable_crl.py` and captured native Speech SDK logs for each phase.

### Phase 1 — initial connection with CRL checking enabled

Observed public SDK result:

```text
initial_crl_enabled: status=timeout elapsed=10.0
```

Native SDK evidence from `reports/logs/sdk-native-initial-crl-enabled.log`:

```text
tlsio_openssl.c:1882 CRL check enabled.
tlsio_openssl.c:691 error:0A000086:SSL routines::certificate verify failed
tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED)
```

The local CRL server was reached once for partition1, and the SDK cached the fetched CRL under `tmp_crl_cache/ec1457bb.crl.0`.

### Phase 2 — rotate server certificate to partition2 and block partition1

The server was restarted with the partition2 certificate. The CRL server was then configured to return 404 for partition1.

The cache before the next SDK attempt contained the stale partition1 CRL:

```text
Cache contents before connection: [PosixPath('.../tmp_crl_cache/ec1457bb.crl.0')]
```

### Phase 3 — reproduce failure with CRL checking enabled

Observed public SDK result:

```text
after_rotation_crl_enabled: status=timeout elapsed=10.0
```

Native SDK evidence from `reports/logs/sdk-native-after-rotation-crl-enabled.log`:

```text
tlsio_openssl.c:1882 CRL check enabled.
tlsio_openssl.c:691 error:0A000086:SSL routines::certificate verify failed
tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED)
```

This confirms the issue is reproduced through the real Speech SDK/OpenSSL path when CRL checking is enabled.

### Phase 4 — mitigate with `OPENSSL_DISABLE_CRL_CHECK=true`

Observed public SDK result:

```text
after_rotation_crl_disabled: status=connected elapsed=0.10087871551513672
```

Native SDK evidence from `reports/logs/sdk-native-after-rotation-crl-disabled.log`:

```text
ISpxNamedProperties::GetStringValue: ... name='OPENSSL_DISABLE_CRL_CHECK'; value='true'
tlsio_openssl.c:1878 CRL check off, as requested.
```

The SDK connection event fired successfully:

```text
✓ Connected! (event: ConnectionEventArgs(...))
Connection successful in 0.10s
```

## Final result

The full test reproduced the issue and confirmed mitigation:

```text
initial_crl_enabled: status=timeout elapsed=10.0
 after_rotation_crl_enabled: status=timeout elapsed=10.0
 after_rotation_crl_disabled: status=connected elapsed=0.10087871551513672
 ✓ Reproduced SDK/OpenSSL failure with CRL checking enabled and recovered with OPENSSL_DISABLE_CRL_CHECK=true
```

Conclusion:

- Repro: YES. With CRL checking enabled, Azure Speech SDK/OpenSSL fails the TLS/WebSocket open path with `certificate verify failed` and `WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED`.
- Mitigation: YES. Setting `OPENSSL_DISABLE_CRL_CHECK=true` disables CRL checking in the native SDK/OpenSSL path and the connection succeeds.

## Evidence files kept

- `reports/logs/full_test_setup.log`
- `reports/logs/full_test_speech_sdk.log`
- `reports/logs/sdk-native-initial-crl-enabled.log`
- `reports/logs/sdk-native-after-rotation-crl-enabled.log`
- `reports/logs/sdk-native-after-rotation-crl-disabled.log`

Old reports and obsolete logs were removed so this report is the single current test report.

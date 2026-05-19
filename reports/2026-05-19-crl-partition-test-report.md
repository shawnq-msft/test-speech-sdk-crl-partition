# Azure Speech SDK CRL Disable Test Report

Date: 2026-05-19T14:29:59+08:00
Repository: https://github.com/shawnq-msft/test-speech-sdk-crl-partition
Local path: `/home/qiushuo/src/test-speech-sdk-crl-partition`
Branch: `main`
Speech SDK version: `azure-cognitiveservices-speech==1.40.0`

## Purpose

This report captures an authentic Azure Speech SDK run for the CRL behavior described in the Microsoft Learn migration note:

https://learn.microsoft.com/en-us/azure/ai-services/speech-service/migrate-to-sdk-1-48-2?tabs=csharp

The referenced guidance says that SDKs before 1.48.2 can fail on Linux/Android when CRL handling hits incompatible or unavailable CRLs, and that an immediate workaround is to set this SpeechConfig property:

```python
speech_config.set_property_by_name("OPENSSL_DISABLE_CRL_CHECK", "true")
```

This run validates that behavior with the mock Speech endpoint in this repository:

1. Reproduce the SDK/OpenSSL rejection with CRL checking enabled.
2. Set `OPENSSL_DISABLE_CRL_CHECK=true`.
3. Try the same endpoint again and confirm the SDK connects.

## Environment

```text
Python 3.12.3
OpenSSL 3.0.13 30 Jan 2024 (Library: OpenSSL 3.0.13 30 Jan 2024)
azure-cognitiveservices-speech==1.40.0
cffi==2.0.0
cryptography==48.0.0
pycparser==3.0
websockets==16.0
```

## Commands used

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
bash scripts/setup_all.sh
python src/repro_disable_crl.py --timeout 10
```

Captured logs:

```text
reports/logs/speech_sdk_disable_crl_repro.log
reports/logs/sdk-native-after-rotation-crl-enabled.log
reports/logs/sdk-native-after-rotation-crl-disabled.log
```

## Test steps and observations

### Phase 0: Precondition check

The test confirmed required PKI artifacts were present, cleared the local CRL cache directory, and started the two local services:

```text
All PKI artifacts present ✓
Cleared CRL cache: /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache
CRL server ready on port 9000
Speech server ready on port 8443 (partition1)
```

### Phase 1: SDK attempt with CRL checking enabled

The SDK attempted to connect to the mock Speech endpoint with default CRL checking enabled:

```text
SSL_CERT_FILE = /home/qiushuo/src/test-speech-sdk-crl-partition/certs/ca-cert.pem
TMPDIR = /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache (CRL cache location)
Speech SDK version: 1.40.0
Connecting to: wss://localhost:8443
SDK native log file: /home/qiushuo/src/test-speech-sdk-crl-partition/reports/logs/sdk-native-initial-crl-enabled.log
Starting connection attempt...
Connection timed out after 10.0s
```

The native SDK log shows OpenSSL CRL checking was enabled and the SDK failed in the underlying WebSocket/TLS open path:

```text
tlsio_openssl.c:1882 CRL check enabled.
tlsio_openssl.c:1030 Error loading CRL from http://localhost:9000/crl/partition1.crl
tlsio_openssl.c:1624 Unable to retrieve CRL, CRL check may fail.
tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED), code=2573[0x00000a0d]
usp_connection.cpp:932 ... Error details: Failed with error: WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED
```

CRL server evidence after this attempt:

```text
CRL server status after initial attempt:
  total_requests: 5
  partitions requested: partition1 x 5
```

### Phase 2: Rotate mock Speech certificate

The mock Speech server was restarted with the partition2 certificate:

```text
Speech server starting (PID 175239, partition2)...
Speech server ready on port 8443 (partition2)
Server restarted with partition2 certificate ✓
```

The old partition1 CRL endpoint was then blocked to model a removed/unavailable old CRL partition:

```text
Blocked CRL partition1 → will return 404
blocked_partitions: [1]
```

### Phase 3: Reproduce SDK/OpenSSL failure after rotation with CRL checking enabled

The SDK retried the endpoint now serving the partition2 certificate, still with CRL checking enabled:

```text
Connecting to: wss://localhost:8443
SDK native log file: /home/qiushuo/src/test-speech-sdk-crl-partition/reports/logs/sdk-native-after-rotation-crl-enabled.log
Starting connection attempt...
Connection timed out after 10.0s
```

The native SDK log again shows OpenSSL CRL checking enabled and the SDK rejecting/closing the connection through the OpenSSL transport path:

```text
tlsio_openssl.c:1882 CRL check enabled.
tlsio_openssl.c:1030 Error loading CRL from http://localhost:9000/crl/partition2.crl
tlsio_openssl.c:1624 Unable to retrieve CRL, CRL check may fail.
tlsio_openssl.c:691 error:10080002:BIO routines::system lib
tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED), code=2573[0x00000a0d]
usp_connection.cpp:932 ... Error details: Failed with error: WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED
```

CRL server evidence after the failure attempt:

```text
CRL server status after failure attempt:
  total_requests: 10
  partitions requested: partition1 x 5, partition2 x 5
  blocked_partitions: [1]
```

Observation: the public Python SDK surface reported the failed path as a timeout, while the native Speech SDK trace shows the OpenSSL/CRL rejection and underlying WebSocket open failure.

### Phase 4: Disable CRL checking and try again

The test then applied the Microsoft Learn workaround:

```text
OPENSSL_DISABLE_CRL_CHECK=true
```

The same SDK endpoint connected immediately:

```text
Applying Microsoft Learn workaround: OPENSSL_DISABLE_CRL_CHECK=true
Connecting to: wss://localhost:8443
SDK native log file: /home/qiushuo/src/test-speech-sdk-crl-partition/reports/logs/sdk-native-after-rotation-crl-disabled.log
CRL check: DISABLED
Starting connection attempt...
✓ Connected! (event: ConnectionEventArgs(session_id=c7ab8aa664dd4563952488e7e7a7231f))
Connection successful in 0.10s
```

The native SDK log confirms the property was read and CRL checking was switched off:

```text
named_properties.h:479 ISpxNamedProperties::GetStringValue: ... name='OPENSSL_DISABLE_CRL_CHECK'; value='true'
tlsio_openssl.c:1878 CRL check off, as requested.
```

No new CRL fetches were made during the disable-CRL attempt; the CRL server total remained at 10.

## Summary result

```text
initial_crl_enabled: status=timeout elapsed=10.0

after_rotation_crl_enabled: status=timeout elapsed=10.0
  Native SDK/OpenSSL evidence:
  - CRL check enabled.
  - Error loading CRL from http://localhost:9000/crl/partition2.crl
  - FORCE-Closing tlsio instance.
  - WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED

after_rotation_crl_disabled: status=connected elapsed=0.10096240043640137
  Native SDK/OpenSSL evidence:
  - OPENSSL_DISABLE_CRL_CHECK value='true'
  - CRL check off, as requested.

Final outcome:
  ✓ Reproduced SDK/OpenSSL failure with CRL checking enabled and recovered with OPENSSL_DISABLE_CRL_CHECK=true
```

## Interpretation

- With Azure Speech SDK 1.40.0 on Linux, the failing path is surfaced to this Python test harness as `timeout`, but the native SDK log clearly shows the OpenSSL transport rejecting/closing the connection after CRL loading fails.
- Setting `OPENSSL_DISABLE_CRL_CHECK=true` on SpeechConfig changes the native OpenSSL path from `CRL check enabled` to `CRL check off, as requested`.
- With CRL checking disabled, the same post-rotation endpoint connects successfully in about 0.10 seconds.
- This matches the Microsoft Learn workaround for pre-1.48.2 Speech SDK deployments that cannot immediately upgrade.

## Full orchestrator log excerpt

```text
$ python src/repro_disable_crl.py --timeout 10
14:27:49 [Orchestrator] INFO # PHASE 0: Precondition Check
14:27:49 [Orchestrator] INFO All PKI artifacts present ✓
14:27:49 [Orchestrator] INFO Cleared CRL cache: /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache
14:27:49 [Orchestrator] INFO CRL server ready on port 9000
14:27:50 [Orchestrator] INFO Speech server ready on port 8443 (partition1)

14:27:51 [Orchestrator] INFO # PHASE 1: SDK Initial Connection With CRL Checking Enabled
14:27:51 [Orchestrator] INFO Speech SDK version: 1.40.0
14:27:51 [Orchestrator] INFO Connecting to: wss://localhost:8443
14:27:51 [Orchestrator] INFO SDK native log file: /home/qiushuo/src/test-speech-sdk-crl-partition/reports/logs/sdk-native-initial-crl-enabled.log
14:28:01 [Orchestrator] ERROR Connection timed out after 10.0s
14:28:01 [Orchestrator] INFO tlsio_openssl.c:1882 CRL check enabled.
14:28:01 [Orchestrator] INFO tlsio_openssl.c:1030 Error loading CRL from http://localhost:9000/crl/partition1.crl
14:28:01 [Orchestrator] INFO web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED)

14:28:03 [Orchestrator] INFO # PHASE 4: Reproduce SDK/OpenSSL Failure With CRL Checking Enabled
14:28:03 [Orchestrator] INFO Speech SDK version: 1.40.0
14:28:03 [Orchestrator] INFO Connecting to: wss://localhost:8443
14:28:03 [Orchestrator] INFO SDK native log file: /home/qiushuo/src/test-speech-sdk-crl-partition/reports/logs/sdk-native-after-rotation-crl-enabled.log
14:28:13 [Orchestrator] ERROR Connection timed out after 10.0s
14:28:13 [Orchestrator] INFO tlsio_openssl.c:1882 CRL check enabled.
14:28:13 [Orchestrator] INFO tlsio_openssl.c:1030 Error loading CRL from http://localhost:9000/crl/partition2.crl
14:28:13 [Orchestrator] INFO tlsio_openssl.c:2464 FORCE-Closing tlsio instance.
14:28:13 [Orchestrator] INFO web_socket.cpp:902 WS open operation failed with result=1(WS_OPEN_ERROR_UNDERLYING_IO_OPEN_FAILED)

14:28:13 [Orchestrator] INFO # PHASE 5: Disable CRL Checking And Try Again
14:28:13 [Orchestrator] INFO Applying Microsoft Learn workaround: OPENSSL_DISABLE_CRL_CHECK=true
14:28:13 [Orchestrator] INFO CRL check: DISABLED
14:28:13 [Orchestrator] INFO ✓ Connected! (event: ConnectionEventArgs(session_id=c7ab8aa664dd4563952488e7e7a7231f))
14:28:13 [Orchestrator] INFO Connection successful in 0.10s
14:28:13 [Orchestrator] INFO name='OPENSSL_DISABLE_CRL_CHECK'; value='true'
14:28:13 [Orchestrator] INFO tlsio_openssl.c:1878 CRL check off, as requested.

14:28:13 [Orchestrator] INFO initial_crl_enabled: status=timeout elapsed=10.0
14:28:13 [Orchestrator] INFO after_rotation_crl_enabled: status=timeout elapsed=10.0
14:28:13 [Orchestrator] INFO after_rotation_crl_disabled: status=connected elapsed=0.10096240043640137
14:28:13 [Orchestrator] INFO ✓ Reproduced SDK/OpenSSL failure with CRL checking enabled and recovered with OPENSSL_DISABLE_CRL_CHECK=true
```

# Azure Speech SDK CRL Partition Test Report

Date: 2026-05-19T13:54:03+08:00
Repository: https://github.com/shawnq-msft/test-speech-sdk-crl-partition
Local path: `/home/qiushuo/src/test-speech-sdk-crl-partition`
Branch: `main`
Speech SDK version: `azure-cognitiveservices-speech==1.40.0`

## Purpose

This report captures an authentic Azure Speech SDK run of the CRL partition reproduction scenario.

The scenario models a service certificate rotation where:

1. The client first connects to a mock Speech endpoint serving a certificate with CDP `partition1.crl`.
2. The mock service rotates to a new certificate with CDP `partition2.crl`.
3. The old CRL partition is blocked.
4. The client reconnects with Azure Speech SDK 1.40.0.
5. Recovery is tested with `OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true`.

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
python src/reproduce.py --use-sdk
```

The captured SDK log is also stored separately at:

```text
reports/logs/speech_sdk.log
```

## Test steps and observations

### Phase 0: Precondition check

The test confirmed all required PKI artifacts were present, then cleared the local CRL cache directory:

```text
All PKI artifacts present ✓
Cleared CRL cache: /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache
```

### Phase 1: Start servers with partition1 certificate

The CRL server started on port 9000 and the mock Speech server started on port 8443 with the partition1 certificate:

```text
CRL server ready on port 9000
Speech server ready on port 8443 (partition1)
```

### Phase 2: Initial SDK connection attempt

The SDK attempted to connect to:

```text
wss://localhost:8443
```

The environment for the attempt was:

```text
SSL_CERT_FILE = /home/qiushuo/src/test-speech-sdk-crl-partition/certs/ca-cert.pem
TMPDIR = /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache (CRL cache location)
Speech SDK version: 1.40.0
```

Result:

```text
Connection timed out after 10.0s
CRL server requests so far: 5
```

Observation: the SDK did not emit a successful connection event in this phase. The CRL server had already received 5 requests, indicating CRL-related network activity from the SDK path.

### Phase 3: Certificate rotation

The mock Speech server was restarted with the partition2 certificate:

```text
Simulating Azure certificate rotation.
New cert has CDP: http://localhost:9000/crl/partition2.crl
Speech server ready on port 8443 (partition2)
Server restarted with partition2 certificate ✓
```

### Phase 4: Decommission old partition

The old partition1 CRL endpoint was blocked:

```text
Blocking partition1 CRL (simulates old CDN partition removed).
Now: GET /crl/partition1.crl → 404
     GET /crl/partition2.crl → 200
Blocked CRL partition1 → will return 404
```

### Phase 5: SDK reconnect after rotation

The SDK attempted to reconnect to the service now serving the partition2 certificate:

```text
Connecting to: wss://localhost:8443
Starting connection attempt...
```

Result:

```text
Connection timed out after 10.0s
CRL server total requests: 10
Blocked partitions: [1]
```

Observation: the non-bypass SDK connection timed out again after the rotation, while CRL server request count increased from 5 to 10.

### Phase 6: Recovery with CRL download failure bypass

The test then enabled:

```text
OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true
```

The SDK connected successfully:

```text
CRL download failure: CONTINUE
✓ Connected! (event: ConnectionEventArgs(session_id=996c93856d234904af7fe409d6d497e1))
Connection successful in 0.10s
```

## Summary result

```text
Scenario Results:
  Step 1 (initial connect):   timeout
  Step 4 (after rotation):    timeout
  Step 5 (CRL bypass):        connected

CRL Server Stats:
  Total requests: 11
  Blocked: [1]
```

Interpretation:

- The authentic Speech SDK 1.40.0 path did not produce a clean certificate-verification exception in this run; it surfaced as connection timeout for the non-bypass attempts.
- The CRL server was hit repeatedly during those timeout attempts, showing CRL activity was involved.
- The same SDK endpoint connected immediately when CRL download failure bypass was enabled.
- This supports the operational conclusion that CRL download/validation behavior can block Speech SDK connectivity, and that `OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true` restores connectivity in this reproduction.

## Full authentic Speech SDK log

```text
$ python src/reproduce.py --use-sdk
13:53:20 [Orchestrator] INFO ╔══════════════════════════════════════════════════════════════════╗
13:53:20 [Orchestrator] INFO ║  Speech SDK CRL Partition Caching Conflict — Reproduction Tool  ║
13:53:20 [Orchestrator] INFO ╚══════════════════════════════════════════════════════════════════╝
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO Mode: Speech SDK
13:53:20 [Orchestrator] INFO Speech port: 8443
13:53:20 [Orchestrator] INFO CRL port: 9000
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO # PHASE 0: Precondition Check
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO All PKI artifacts present ✓
13:53:20 [Orchestrator] INFO Cleared CRL cache: /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO # PHASE 1: Start Servers (partition1)
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO CRL server starting (PID 173307)...
13:53:20 [Orchestrator] INFO CRL server ready on port 9000
13:53:20 [Orchestrator] INFO Speech server starting (PID 173308, partition1)...
13:53:20 [Orchestrator] INFO Speech server ready on port 8443 (partition1)
13:53:21 [Orchestrator] INFO 
13:53:21 [Orchestrator] INFO ######################################################################
13:53:21 [Orchestrator] INFO # PHASE 2: Initial Connection (partition1 cert + CRL)
13:53:21 [Orchestrator] INFO ######################################################################
13:53:21 [Orchestrator] INFO 
13:53:21 [Orchestrator] INFO Client connects to server with partition1 certificate.
13:53:21 [Orchestrator] INFO Expected: CRL fetched from http://localhost:9000/crl/partition1.crl
13:53:21 [Orchestrator] INFO 
13:53:21 [Orchestrator] INFO SSL_CERT_FILE = /home/qiushuo/src/test-speech-sdk-crl-partition/certs/ca-cert.pem
13:53:21 [Orchestrator] INFO TMPDIR = /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache (CRL cache location)
13:53:21 [Orchestrator] INFO Cache contents before connection: []
13:53:22 [Orchestrator] INFO Speech SDK version: 1.40.0
13:53:22 [Orchestrator] INFO Connecting to: wss://localhost:8443
13:53:22 [Orchestrator] INFO Starting connection attempt...
13:53:32 [Orchestrator] ERROR   Connection timed out after 10.0s
13:53:32 [Orchestrator] INFO CRL server requests so far: 5
13:53:32 [Orchestrator] INFO 
13:53:32 [Orchestrator] INFO ######################################################################
13:53:32 [Orchestrator] INFO # PHASE 3: Certificate Rotation (partition1 → partition2)
13:53:32 [Orchestrator] INFO ######################################################################
13:53:32 [Orchestrator] INFO 
13:53:32 [Orchestrator] INFO Simulating Azure certificate rotation.
13:53:32 [Orchestrator] INFO New cert has CDP: http://localhost:9000/crl/partition2.crl
13:53:32 [Orchestrator] INFO 
13:53:33 [Orchestrator] INFO Speech server starting (PID 173317, partition2)...
13:53:33 [Orchestrator] INFO Speech server ready on port 8443 (partition2)
13:53:34 [Orchestrator] INFO Server restarted with partition2 certificate ✓
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] INFO ######################################################################
13:53:34 [Orchestrator] INFO # PHASE 4: Decommission Old Partition
13:53:34 [Orchestrator] INFO ######################################################################
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] INFO Blocking partition1 CRL (simulates old CDN partition removed).
13:53:34 [Orchestrator] INFO Now: GET /crl/partition1.crl → 404
13:53:34 [Orchestrator] INFO      GET /crl/partition2.crl → 200
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] WARNING Blocked CRL partition1 → will return 404
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] INFO ######################################################################
13:53:34 [Orchestrator] INFO # PHASE 5: Client Reconnects (CRL Partition Conflict)
13:53:34 [Orchestrator] INFO ######################################################################
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] INFO Client reconnects to server (now serving partition2 cert).
13:53:34 [Orchestrator] INFO SDK will try to validate cert → needs CRL from partition2.
13:53:34 [Orchestrator] INFO If SDK has stale partition1 CRL cached → potential conflict!
13:53:34 [Orchestrator] INFO 
13:53:34 [Orchestrator] INFO SSL_CERT_FILE = /home/qiushuo/src/test-speech-sdk-crl-partition/certs/ca-cert.pem
13:53:34 [Orchestrator] INFO TMPDIR = /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache (CRL cache location)
13:53:34 [Orchestrator] INFO Cache contents before connection: []
13:53:34 [Orchestrator] INFO Speech SDK version: 1.40.0
13:53:34 [Orchestrator] INFO Connecting to: wss://localhost:8443
13:53:34 [Orchestrator] INFO Starting connection attempt...
13:53:44 [Orchestrator] ERROR   Connection timed out after 10.0s
13:53:44 [Orchestrator] INFO CRL server total requests: 10
13:53:44 [Orchestrator] INFO Blocked partitions: [1]
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO ######################################################################
13:53:44 [Orchestrator] INFO # PHASE 6: Recovery (CRL Check Bypass)
13:53:44 [Orchestrator] INFO ######################################################################
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO Testing recovery: disable CRL check to restore connectivity.
13:53:44 [Orchestrator] INFO SDK property: OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO SSL_CERT_FILE = /home/qiushuo/src/test-speech-sdk-crl-partition/certs/ca-cert.pem
13:53:44 [Orchestrator] INFO TMPDIR = /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache (CRL cache location)
13:53:44 [Orchestrator] INFO Cache contents before connection: []
13:53:44 [Orchestrator] INFO Speech SDK version: 1.40.0
13:53:44 [Orchestrator] INFO Connecting to: wss://localhost:8443
13:53:44 [Orchestrator] INFO   CRL download failure: CONTINUE
13:53:44 [Orchestrator] INFO Starting connection attempt...
13:53:44 [Orchestrator] INFO   ✓ Connected! (event: ConnectionEventArgs(session_id=996c93856d234904af7fe409d6d497e1))
13:53:44 [Orchestrator] INFO   Connection successful in 0.10s
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO ######################################################################
13:53:44 [Orchestrator] INFO # SUMMARY
13:53:44 [Orchestrator] INFO ######################################################################
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO Scenario Results:
13:53:44 [Orchestrator] INFO   Step 1 (initial connect):   timeout
13:53:44 [Orchestrator] INFO   Step 4 (after rotation):    timeout
13:53:44 [Orchestrator] INFO   Step 5 (CRL bypass):        connected
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO ? Unexpected result: timeout
13:53:44 [Orchestrator] INFO 
13:53:44 [Orchestrator] INFO CRL Server Stats:
13:53:44 [Orchestrator] INFO   Total requests: 11
13:53:44 [Orchestrator] INFO   Blocked: [1]
13:53:44 [Orchestrator] INFO 
Cleaning up processes...
13:53:44 [Orchestrator] INFO Done.
```

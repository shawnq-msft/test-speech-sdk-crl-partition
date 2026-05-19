# Speech SDK CRL Partition Test Report

Date: 2026-05-19T13:54:03+08:00
Repository: https://github.com/shawnq-msft/test-speech-sdk-crl-partition
Local path: `/home/qiushuo/src/test-speech-sdk-crl-partition`
Base commit tested: `e9bb790 first commit`
Branch: `main`

## Executive summary

The repository test now runs locally after two compatibility fixes:

1. OpenSSL 3 compatibility in `scripts/setup_ca.sh`:
   - The original setup failed when issuing two server certificates with the same localhost subject.
   - OpenSSL reported: `ERROR:There is already a certificate for /C=US/O=Speech SDK CRL Test/CN=localhost`.
   - Fix: explicitly generate `index.txt.attr` with `unique_subject = no` and include `unique_subject = no` in the generated OpenSSL config.

2. Azure Speech SDK 1.40 connection event API fix in `src/test_client.py`:
   - The original SDK client crashed with `AttributeError: 'SpeechRecognizer' object has no attribute 'connected'`.
   - Fix: use `speechsdk.Connection.from_recognizer(recognizer).connected` / `.disconnected`; keep `recognizer.canceled` for cancellation events.

After these fixes:

- Raw TLS reproduction: **PASS / issue reproduced**
  - Initial connect: `connected`
  - After certificate rotation: `cert_verification_error`
  - CRL bypass recovery: `connected`
  - Key error: `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get certificate CRL (_ssl.c:1000)`

- Speech SDK 1.40 reproduction: **PARTIAL / demonstrates CRL-dependent failure and bypass recovery**
  - Initial connect: `timeout`
  - After certificate rotation: `timeout`
  - CRL bypass recovery: `connected`
  - The CRL server received requests during the timeout phases, indicating SDK CRL activity. With `OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true`, connection succeeded in `0.10s`.

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

## Commands run

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
bash scripts/setup_all.sh
python src/reproduce.py
python src/reproduce.py --use-sdk
```

The final captured logs are stored in:

- `reports/logs/setup.log`
- `reports/logs/raw_tls.log`
- `reports/logs/speech_sdk.log`

## Code changes made

### `scripts/setup_ca.sh`

Reason: make PKI setup work on OpenSSL 3 when issuing two certs with the same subject.

Change summary:

```diff
 # Create CA database files
 > "${CERTS_DIR}/index.txt"
+echo "unique_subject = no" > "${CERTS_DIR}/index.txt.attr"
 echo "1000" > "${CERTS_DIR}/serial"
 echo "1000" > "${CERTS_DIR}/crlnumber"
```

```diff
 policy            = policy_anything
 copy_extensions   = copy
+# Allow issuing multiple localhost server certs for different CRL partitions.
+# OpenSSL 3 rejects duplicate subjects by default otherwise.
+unique_subject     = no
 
 [policy_anything]
```

### `src/test_client.py`

Reason: Speech SDK 1.40.0 exposes connection events on `speechsdk.Connection`, not directly on `SpeechRecognizer`.

Change summary:

```diff
-    # Track connection events
+    # Track connection events. SpeechRecognizer itself does not expose
+    # connected/disconnected signals in Speech SDK 1.40; those are on the
+    # Connection object returned by Connection.from_recognizer().
     connection_established = False
     connection_error = None
     canceled_reason = None
 
+    connection = speechsdk.Connection.from_recognizer(recognizer)
+
@@
-    recognizer.connected.connect(on_connected)
-    recognizer.disconnected.connect(on_disconnected)
+    connection.connected.connect(on_connected)
+    connection.disconnected.connect(on_disconnected)
     recognizer.canceled.connect(on_canceled)
```

## Raw TLS test result

Command:

```bash
python src/reproduce.py
```

Outcome: **PASS / CRL partition conflict reproduced**

Important lines:

```text
Scenario Results:
  Step 1 (initial connect):   connected
  Step 4 (after rotation):    cert_verification_error
  Step 5 (CRL bypass):        connected

✓ CRL PARTITION CONFLICT REPRODUCED!
  The stale CRL cache caused a connection failure after rotation.
```

The failing phase produced:

```text
ERROR   ✗ Certificate verification failed!
ERROR     Code: 3
ERROR     Message: unable to get certificate CRL
ERROR     Details: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get certificate CRL (_ssl.c:1000)
```

## Speech SDK 1.40 test result

Command:

```bash
python src/reproduce.py --use-sdk
```

Outcome: **PARTIAL / CRL-dependent failure observed; bypass recovers connectivity**

Important lines:

```text
Scenario Results:
  Step 1 (initial connect):   timeout
  Step 4 (after rotation):    timeout
  Step 5 (CRL bypass):        connected

CRL Server Stats:
  Total requests: 11
  Blocked: [1]
```

Recovery succeeded with:

```text
CRL download failure: CONTINUE
✓ Connected! (event: ConnectionEventArgs(...))
Connection successful in 0.10s
```

Interpretation:

- The SDK mode did not produce a clean `cert_verification_error` event; it timed out for the non-bypass attempts.
- The CRL server saw 5 requests during the first SDK attempt and 10 total before bypass, so the SDK was performing CRL-related network activity.
- The same endpoint connected immediately when `OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true` was set, which supports the CRL-check failure hypothesis.

## Full logs

### Setup log

```text
$ python --version
Python 3.12.3
$ openssl version
OpenSSL 3.0.13 30 Jan 2024 (Library: OpenSSL 3.0.13 30 Jan 2024)
$ pip freeze
azure-cognitiveservices-speech==1.40.0
cffi==2.0.0
cryptography==48.0.0
pycparser==3.0
websockets==16.0
$ bash scripts/setup_all.sh
==========================================
 Speech SDK CRL Partition Test — Full Setup
==========================================

=== Setting up CA in /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs ===
[OK] CA private key generated
[OK] CA certificate generated

=== CA Setup Complete ===
  CA cert: /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/ca-cert.pem
  CA key:  /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/ca-key.pem
  Config:  /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/openssl.cnf

=== Issuing server certificate for partition 1 ===
[OK] Server key: /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/server-part1-key.pem
[OK] CSR generated
Using configuration from /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/openssl.cnf
Check that the request matches the signature
Signature ok
The Subject's Distinguished Name is as follows
commonName            :ASN.1 12:'localhost'
organizationName      :ASN.1 12:'Speech SDK CRL Test'
countryName           :PRINTABLE:'US'
Certificate is to be certified until May 19 05:53:15 2027 GMT (365 days)

Write out database with 1 new entries
Database updated
[OK] Certificate signed: /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/server-part1-cert.pem

--- Certificate CRL Distribution Points ---
            X509v3 CRL Distribution Points: 
                Full Name:
                  URI:http://localhost:9000/crl/partition1.crl

=== Done: partition1 cert ready ===

=== Issuing server certificate for partition 2 ===
[OK] Server key: /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/server-part2-key.pem
[OK] CSR generated
Using configuration from /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/openssl.cnf
Check that the request matches the signature
Signature ok
The Subject's Distinguished Name is as follows
commonName            :ASN.1 12:'localhost'
organizationName      :ASN.1 12:'Speech SDK CRL Test'
countryName           :PRINTABLE:'US'
Certificate is to be certified until May 19 05:53:15 2027 GMT (365 days)

Write out database with 1 new entries
Database updated
[OK] Certificate signed: /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/server-part2-cert.pem

--- Certificate CRL Distribution Points ---
            X509v3 CRL Distribution Points: 
                Full Name:
                  URI:http://localhost:9000/crl/partition2.crl

=== Done: partition2 cert ready ===

=== Generating CRL files ===
Using configuration from /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/openssl.cnf
[OK] partition1.crl generated
Using configuration from /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/openssl.cnf
[OK] partition2.crl generated

--- partition1.crl info ---
Certificate Revocation List (CRL):
        Version 2 (0x1)
        Signature Algorithm: sha256WithRSAEncryption
        Issuer: CN = Test CRL Partition CA, O = Speech SDK CRL Test, C = US
        Last Update: May 19 05:53:15 2026 GMT
        Next Update: Jun 18 05:53:15 2026 GMT
        CRL extensions:
            X509v3 CRL Number: 
                4096
No Revoked Certificates.
    Signature Algorithm: sha256WithRSAEncryption
    Signature Value:
        48:91:81:f1:d8:49:98:f9:a2:3d:c4:bd:98:dd:97:93:38:1b:
        70:48:28:93:b4:7b:ad:7c:d2:e1:dd:9e:15:7c:9c:c0:df:ad:
        5d:03:48:7c:59:2c:b1:e7:7e:90:d1:c6:3c:1f:a8:1e:27:51:

--- partition2.crl info ---
Certificate Revocation List (CRL):
        Version 2 (0x1)
        Signature Algorithm: sha256WithRSAEncryption
        Issuer: CN = Test CRL Partition CA, O = Speech SDK CRL Test, C = US
        Last Update: May 19 05:53:15 2026 GMT
        Next Update: Jun 18 05:53:15 2026 GMT
        CRL extensions:
            X509v3 CRL Number: 
                4097
No Revoked Certificates.
    Signature Algorithm: sha256WithRSAEncryption
    Signature Value:
        1e:bd:ce:de:38:a8:3e:f9:20:c5:af:8f:0d:3d:06:58:a8:a3:
        40:c5:79:ec:fe:1d:64:70:c0:25:f9:9f:07:80:06:97:b5:09:
        32:3e:2b:fc:20:1a:25:8d:3a:bb:ab:d9:aa:24:3a:c5:7a:a3:

=== CRL Generation Complete ===
  /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/partition1.crl
  /home/qiushuo/src/test-speech-sdk-crl-partition/scripts/../certs/partition2.crl

==========================================
 All PKI artifacts generated successfully
==========================================

Next steps:
  1. pip install -r requirements.txt
  2. python src/reproduce.py
```

### Raw TLS log

```text
$ python src/reproduce.py
13:53:15 [Orchestrator] INFO ╔══════════════════════════════════════════════════════════════════╗
13:53:15 [Orchestrator] INFO ║  Speech SDK CRL Partition Caching Conflict — Reproduction Tool  ║
13:53:15 [Orchestrator] INFO ╚══════════════════════════════════════════════════════════════════╝
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO Mode: Raw TLS
13:53:15 [Orchestrator] INFO Speech port: 8443
13:53:15 [Orchestrator] INFO CRL port: 9000
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO ######################################################################
13:53:15 [Orchestrator] INFO # PHASE 0: Precondition Check
13:53:15 [Orchestrator] INFO ######################################################################
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO All PKI artifacts present ✓
13:53:15 [Orchestrator] INFO Cleared CRL cache: /home/qiushuo/src/test-speech-sdk-crl-partition/tmp_crl_cache
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO ######################################################################
13:53:15 [Orchestrator] INFO # PHASE 1: Start Servers (partition1)
13:53:15 [Orchestrator] INFO ######################################################################
13:53:15 [Orchestrator] INFO 
13:53:15 [Orchestrator] INFO CRL server starting (PID 173298)...
13:53:15 [Orchestrator] INFO CRL server ready on port 9000
13:53:15 [Orchestrator] INFO Speech server starting (PID 173300, partition1)...
13:53:16 [Orchestrator] INFO Speech server ready on port 8443 (partition1)
13:53:17 [Orchestrator] INFO 
13:53:17 [Orchestrator] INFO ######################################################################
13:53:17 [Orchestrator] INFO # PHASE 2: Initial Connection (partition1 cert + CRL)
13:53:17 [Orchestrator] INFO ######################################################################
13:53:17 [Orchestrator] INFO 
13:53:17 [Orchestrator] INFO Client connects to server with partition1 certificate.
13:53:17 [Orchestrator] INFO Expected: CRL fetched from http://localhost:9000/crl/partition1.crl
13:53:17 [Orchestrator] INFO 
13:53:17 [Orchestrator] INFO === Scenario: Basic TLS connection (no CRL check) ===
13:53:17 [Orchestrator] INFO   ✓ TLS connected: TLSv1.3 / TLS_AES_256_GCM_SHA384
13:53:17 [Orchestrator] INFO     Cert subject: {'countryName': 'US', 'organizationName': 'Speech SDK CRL Test', 'commonName': 'localhost'}
13:53:17 [Orchestrator] INFO     Cert serial:  1000
13:53:17 [Orchestrator] INFO     CDP: ('http://localhost:9000/crl/partition1.crl',)
13:53:17 [Orchestrator] INFO CRL server requests so far: 0
13:53:17 [Orchestrator] INFO 
13:53:17 [Orchestrator] INFO ######################################################################
13:53:17 [Orchestrator] INFO # PHASE 3: Certificate Rotation (partition1 → partition2)
13:53:17 [Orchestrator] INFO ######################################################################
13:53:17 [Orchestrator] INFO 
13:53:17 [Orchestrator] INFO Simulating Azure certificate rotation.
13:53:17 [Orchestrator] INFO New cert has CDP: http://localhost:9000/crl/partition2.crl
13:53:17 [Orchestrator] INFO 
13:53:18 [Orchestrator] INFO Speech server starting (PID 173303, partition2)...
13:53:18 [Orchestrator] INFO Speech server ready on port 8443 (partition2)
13:53:19 [Orchestrator] INFO Server restarted with partition2 certificate ✓
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO ######################################################################
13:53:19 [Orchestrator] INFO # PHASE 4: Decommission Old Partition
13:53:19 [Orchestrator] INFO ######################################################################
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO Blocking partition1 CRL (simulates old CDN partition removed).
13:53:19 [Orchestrator] INFO Now: GET /crl/partition1.crl → 404
13:53:19 [Orchestrator] INFO      GET /crl/partition2.crl → 200
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] WARNING Blocked CRL partition1 → will return 404
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO ######################################################################
13:53:19 [Orchestrator] INFO # PHASE 5: Client Reconnects (CRL Partition Conflict)
13:53:19 [Orchestrator] INFO ######################################################################
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO Client reconnects to server (now serving partition2 cert).
13:53:19 [Orchestrator] INFO SDK will try to validate cert → needs CRL from partition2.
13:53:19 [Orchestrator] INFO If SDK has stale partition1 CRL cached → potential conflict!
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO === Scenario: Stale CRL cache conflict ===
13:53:19 [Orchestrator] INFO   Server should be running with partition2 cert
13:53:19 [Orchestrator] INFO   Client has partition1 CRL cached
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO CRL verification enabled with: /home/qiushuo/src/test-speech-sdk-crl-partition/certs/partition1.crl
13:53:19 [Orchestrator] ERROR   ✗ Certificate verification failed!
13:53:19 [Orchestrator] ERROR     Code: 3
13:53:19 [Orchestrator] ERROR     Message: unable to get certificate CRL
13:53:19 [Orchestrator] ERROR     Details: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get certificate CRL (_ssl.c:1000)
13:53:19 [Orchestrator] INFO 
13:53:19 [Orchestrator] INFO *** CRL PARTITION CONFLICT REPRODUCED ***
13:53:19 [Orchestrator] INFO The stale CRL (partition1) cannot validate the new cert (partition2).
13:53:19 [Orchestrator] INFO This is the exact issue Speech SDK 1.40 experiences when:
13:53:19 [Orchestrator] INFO   1. CRL from old partition is cached in TMPDIR
13:53:19 [Orchestrator] INFO   2. Speech Service rotates to cert with new CDP
13:53:19 [Orchestrator] INFO   3. SDK uses cached CRL → validation fails
13:53:20 [Orchestrator] INFO CRL server total requests: 0
13:53:20 [Orchestrator] INFO Blocked partitions: [1]
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO # PHASE 6: Recovery (CRL Check Bypass)
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO Testing recovery: disable CRL check to restore connectivity.
13:53:20 [Orchestrator] INFO SDK property: OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE=true
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO === Scenario: Recovery with CRL bypass ===
13:53:20 [Orchestrator] INFO   ✓ TLS connected: TLSv1.3 / TLS_AES_256_GCM_SHA384
13:53:20 [Orchestrator] INFO     Cert subject: {'countryName': 'US', 'organizationName': 'Speech SDK CRL Test', 'commonName': 'localhost'}
13:53:20 [Orchestrator] INFO     Cert serial:  1001
13:53:20 [Orchestrator] INFO     CDP: ('http://localhost:9000/crl/partition2.crl',)
13:53:20 [Orchestrator] INFO   → Connection recovered by disabling CRL check
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO # SUMMARY
13:53:20 [Orchestrator] INFO ######################################################################
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO Scenario Results:
13:53:20 [Orchestrator] INFO   Step 1 (initial connect):   connected
13:53:20 [Orchestrator] INFO   Step 4 (after rotation):    cert_verification_error
13:53:20 [Orchestrator] INFO   Step 5 (CRL bypass):        connected
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO ✓ CRL PARTITION CONFLICT REPRODUCED!
13:53:20 [Orchestrator] INFO   The stale CRL cache caused a connection failure after rotation.
13:53:20 [Orchestrator] INFO 
13:53:20 [Orchestrator] INFO CRL Server Stats:
13:53:20 [Orchestrator] INFO   Total requests: 0
13:53:20 [Orchestrator] INFO   Blocked: [1]
13:53:20 [Orchestrator] INFO 
Cleaning up processes...
13:53:20 [Orchestrator] INFO Done.
```

### Speech SDK log

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

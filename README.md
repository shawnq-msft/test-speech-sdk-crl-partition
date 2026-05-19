# Speech SDK CRL Partition Caching Conflict — Reproduction Test

Reproduces the issue where Azure Speech SDK 1.40 caches CRL (Certificate Revocation
List) responses, and when the Speech Service rotates its HTTPS certificate to one
with a different CRL Distribution Point (CDP) URI (partition change), the stale
cached CRL causes connection failures.

## Problem Description

```
Timeline:
  t0: Client connects to Speech Service
      → Server cert has CDP: http://crl.azure.com/partition1.crl
      → SDK downloads partition1.crl, caches in $TMPDIR
      
  t1: Azure rotates certificate (routine maintenance)
      → New cert has CDP: http://crl.azure.com/partition2.crl
      → Old partition1.crl URI may become unavailable
      
  t2: Client reconnects
      → SDK has stale partition1.crl in cache
      → New cert references partition2.crl
      → Validation fails OR stale cache used incorrectly
```

## Architecture

```
┌─────────────────┐        ┌──────────────────────┐       ┌──────────────────┐
│  Speech SDK     │──TLS──▶│  Mock HTTPS/WSS      │       │  CRL Server      │
│  Python Client  │        │  Server (:8443)      │       │  (:9000)         │
│                 │        │  cert with CDP→CRL   │       │  partition1.crl  │
│  CRL cache in   │        └──────────────────────┘       │  partition2.crl  │
│  $TMPDIR        │──HTTP──────────────────────────────▶  └──────────────────┘
└─────────────────┘
```

## Quick Start (Linux)

### Prerequisites

- Python 3.10+
- OpenSSL CLI
- Bash

### Setup

```bash
# 1. Generate all PKI artifacts (CA, certs, CRLs)
bash scripts/setup_all.sh

# 2. Install Python dependencies
pip install -r requirements.txt
```

### Run Reproduction

```bash
# Run with raw TLS client (no Speech SDK dependency):
python src/reproduce.py

# Run with actual Speech SDK client:
python src/reproduce.py --use-sdk
```

## Manual Step-by-Step

### Step 1: Start CRL server

```bash
python src/crl_server.py --port 9000
```

### Step 2: Start mock Speech Service (partition 1)

```bash
python src/speech_server.py --port 8443 --partition 1
```

### Step 3: Client connects (partition 1 CRL cached)

```bash
python src/test_client_raw.py --scenario basic
```

### Step 4: Rotate certificate to partition 2

Stop the speech server, restart with `--partition 2`:
```bash
python src/speech_server.py --port 8443 --partition 2
```

### Step 5: Block old partition (simulate decommission)

```bash
curl http://localhost:9000/control/block/1
```

### Step 6: Client reconnects (conflict!)

```bash
python src/test_client_raw.py --scenario stale_cache_conflict
```

### Step 7: Recovery with CRL bypass

```bash
python src/test_client_raw.py --scenario recovery_with_bypass
```

## Relevant Speech SDK Properties

| Property | Effect |
|----------|--------|
| `OPENSSL_CONTINUE_ON_CRL_DOWNLOAD_FAILURE` = `"true"` | Continue connection even if CRL download fails |
| `OPENSSL_DISABLE_CRL_CHECK` = `"true"` | Skip CRL validation entirely |
| `CONFIG_MAX_CRL_SIZE_KB` = `"150000"` | Max CRL file size (default 100MB) |

## CRL Server Control API

| Endpoint | Effect |
|----------|--------|
| `GET /crl/partitionN.crl` | Serve CRL for partition N |
| `GET /status` | Show request log and state |
| `GET /control/block/N` | Make partition N return 404 |
| `GET /control/unblock/N` | Restore partition N |
| `GET /control/delay/N/S` | Add S second delay to partition N |

## Files

```
├── scripts/
│   ├── setup_all.sh        # Full PKI setup (run once)
│   ├── setup_ca.sh         # Create CA
│   ├── issue_cert.sh       # Issue cert with specific CDP
│   └── gen_crl.sh          # Generate CRL files
├── src/
│   ├── crl_server.py       # CRL distribution HTTP server
│   ├── speech_server.py    # Mock Speech Service (HTTPS/WSS)
│   ├── test_client.py      # Speech SDK client
│   ├── test_client_raw.py  # Raw TLS client (fallback)
│   └── reproduce.py        # Full orchestrator
├── certs/                  # Generated PKI artifacts (gitignored)
├── tmp_crl_cache/          # CRL cache observation dir (gitignored)
├── requirements.txt
└── README.md
```

## Expected Results

| Phase | Expected Behavior |
|-------|-------------------|
| Initial connect (partition1) | Success. CRL fetched and cached. |
| After rotation (partition2 cert, partition1 blocked) | **Failure** — CRL validation error |
| Recovery (CRL bypass enabled) | Success — SDK continues despite CRL issue |

## Notes

- CRL checks are **disabled by default** in Speech SDK 1.48+. This issue primarily
  affects SDK versions 1.40–1.47 where CRL checks are enabled by default.
- On Linux, the SDK caches CRLs in the directory specified by `$TMPDIR` or `$TMP`.
- The exact cache key strategy (URI-based vs issuer-based) can be observed by
  monitoring file system changes in the cache directory during the test.

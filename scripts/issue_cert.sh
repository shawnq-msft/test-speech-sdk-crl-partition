#!/usr/bin/env bash
# issue_cert.sh — Issue a server certificate with a specific CRL partition CDP
# Usage: ./issue_cert.sh <partition_number>
#   e.g. ./issue_cert.sh 1  → cert with CDP http://localhost:9000/crl/partition1.crl
#   e.g. ./issue_cert.sh 2  → cert with CDP http://localhost:9000/crl/partition2.crl
set -euo pipefail

PARTITION="${1:?Usage: $0 <partition_number> (1 or 2)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CERTS_DIR="${SCRIPT_DIR}/../certs"
CNF="${CERTS_DIR}/openssl.cnf"

if [[ ! -f "${CNF}" ]]; then
    echo "ERROR: openssl.cnf not found. Run setup_ca.sh first."
    exit 1
fi

echo "=== Issuing server certificate for partition ${PARTITION} ==="

KEY_FILE="${CERTS_DIR}/server-part${PARTITION}-key.pem"
CSR_FILE="${CERTS_DIR}/server-part${PARTITION}.csr"
CERT_FILE="${CERTS_DIR}/server-part${PARTITION}-cert.pem"

# Generate server private key
openssl genrsa -out "${KEY_FILE}" 2048
echo "[OK] Server key: ${KEY_FILE}"

# Generate CSR
openssl req -new \
    -key "${KEY_FILE}" \
    -out "${CSR_FILE}" \
    -subj "/CN=localhost/O=Speech SDK CRL Test/C=US"
echo "[OK] CSR generated"

# Sign with CA using partition-specific extensions
openssl ca -batch -notext \
    -config "${CNF}" \
    -extensions "v3_server_partition${PARTITION}" \
    -in "${CSR_FILE}" \
    -out "${CERT_FILE}"
echo "[OK] Certificate signed: ${CERT_FILE}"

# Show CDP in the issued certificate
echo ""
echo "--- Certificate CRL Distribution Points ---"
openssl x509 -in "${CERT_FILE}" -noout -text | grep -A2 "CRL Distribution"
echo ""
echo "=== Done: partition${PARTITION} cert ready ==="

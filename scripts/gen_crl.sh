#!/usr/bin/env bash
# gen_crl.sh — Generate CRL files for each partition
# Usage: ./gen_crl.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CERTS_DIR="${SCRIPT_DIR}/../certs"
CNF="${CERTS_DIR}/openssl.cnf"

if [[ ! -f "${CNF}" ]]; then
    echo "ERROR: openssl.cnf not found. Run setup_ca.sh first."
    exit 1
fi

echo "=== Generating CRL files ==="

# Generate CRL for partition 1 (valid for 30 days)
openssl ca -gencrl \
    -config "${CNF}" \
    -crlexts crl_ext_partition1 \
    -out "${CERTS_DIR}/partition1.crl.pem" \
    -crldays 30
openssl crl \
    -in "${CERTS_DIR}/partition1.crl.pem" \
    -outform DER \
    -out "${CERTS_DIR}/partition1.crl"
echo "[OK] partition1.crl generated (DER)"

# Generate CRL for partition 2 (valid for 30 days)
# In real scenarios, partition2 would be a separate CRL scope
# Here we generate the same CA's CRL but as a "different partition"
openssl ca -gencrl \
    -config "${CNF}" \
    -crlexts crl_ext_partition2 \
    -out "${CERTS_DIR}/partition2.crl.pem" \
    -crldays 30
openssl crl \
    -in "${CERTS_DIR}/partition2.crl.pem" \
    -outform DER \
    -out "${CERTS_DIR}/partition2.crl"
echo "[OK] partition2.crl generated (DER)"

# Verify CRL files
echo ""
echo "--- partition1.crl info ---"
openssl crl -inform DER -in "${CERTS_DIR}/partition1.crl" -noout -text | grep -E "(Issuer:|Last Update:|Next Update:|Issuing Distribution Point|Full Name|URI:)" | head -20

echo ""
echo "--- partition2.crl info ---"
openssl crl -inform DER -in "${CERTS_DIR}/partition2.crl" -noout -text | grep -E "(Issuer:|Last Update:|Next Update:|Issuing Distribution Point|Full Name|URI:)" | head -20

echo ""
echo "=== CRL Generation Complete ==="
echo "  ${CERTS_DIR}/partition1.crl"
echo "  ${CERTS_DIR}/partition2.crl"

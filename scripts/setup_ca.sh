#!/usr/bin/env bash
# setup_ca.sh — Initialize a local Certificate Authority for CRL partition testing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CERTS_DIR="${SCRIPT_DIR}/../certs"

echo "=== Setting up CA in ${CERTS_DIR} ==="

mkdir -p "${CERTS_DIR}/newcerts"

# Create CA database files
> "${CERTS_DIR}/index.txt"
echo "unique_subject = no" > "${CERTS_DIR}/index.txt.attr"
echo "1000" > "${CERTS_DIR}/serial"
echo "1000" > "${CERTS_DIR}/crlnumber"

# Generate OpenSSL configuration
cat > "${CERTS_DIR}/openssl.cnf" <<'EOF'
# OpenSSL CA configuration for CRL partition testing

[ca]
default_ca = CA_default

[CA_default]
dir               = CERTS_DIR_PLACEHOLDER
database          = $dir/index.txt
serial            = $dir/serial
crlnumber         = $dir/crlnumber
new_certs_dir     = $dir/newcerts
certificate       = $dir/ca-cert.pem
private_key       = $dir/ca-key.pem
default_md        = sha256
default_days      = 365
default_crl_days  = 30
policy            = policy_anything
copy_extensions   = copy
# Allow issuing multiple localhost server certs for different CRL partitions.
# OpenSSL 3 rejects duplicate subjects by default otherwise.
unique_subject     = no

[policy_anything]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[req]
default_bits       = 2048
distinguished_name = req_distinguished_name
prompt             = no

[req_distinguished_name]
CN = Test CRL Partition CA
O  = Speech SDK CRL Test
C  = US

# Server cert extensions with CRL partition 1
[v3_server_partition1]
basicConstraints       = CA:FALSE
keyUsage               = digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth
subjectAltName         = DNS:localhost, IP:127.0.0.1
crlDistributionPoints  = URI:http://localhost:9000/crl/partition1.crl

# Server cert extensions with CRL partition 2
[v3_server_partition2]
basicConstraints       = CA:FALSE
keyUsage               = digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth
subjectAltName         = DNS:localhost, IP:127.0.0.1
crlDistributionPoints  = URI:http://localhost:9000/crl/partition2.crl

[v3_ca]
basicConstraints       = critical, CA:TRUE
keyUsage               = critical, keyCertSign, cRLSign
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer

[crl_ext]
authorityKeyIdentifier = keyid:always

[crl_ext_partition1]
authorityKeyIdentifier = keyid:always
issuingDistributionPoint = critical, @idp_partition1

[crl_ext_partition2]
authorityKeyIdentifier = keyid:always
issuingDistributionPoint = critical, @idp_partition2

[idp_partition1]
fullname = URI:http://localhost:9000/crl/partition1.crl

[idp_partition2]
fullname = URI:http://localhost:9000/crl/partition2.crl
EOF

# Replace placeholder with actual path
sed -i "s|CERTS_DIR_PLACEHOLDER|${CERTS_DIR}|g" "${CERTS_DIR}/openssl.cnf"

# Generate CA private key
openssl genrsa -out "${CERTS_DIR}/ca-key.pem" 4096
echo "[OK] CA private key generated"

# Generate self-signed CA certificate
openssl req -new -x509 -days 3650 \
    -key "${CERTS_DIR}/ca-key.pem" \
    -out "${CERTS_DIR}/ca-cert.pem" \
    -config "${CERTS_DIR}/openssl.cnf" \
    -extensions v3_ca
echo "[OK] CA certificate generated"

echo ""
echo "=== CA Setup Complete ==="
echo "  CA cert: ${CERTS_DIR}/ca-cert.pem"
echo "  CA key:  ${CERTS_DIR}/ca-key.pem"
echo "  Config:  ${CERTS_DIR}/openssl.cnf"

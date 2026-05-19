#!/usr/bin/env bash
# setup_all.sh — Run all setup steps in order
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo " Speech SDK CRL Partition Test — Full Setup"
echo "=========================================="
echo ""

# Step 1: Create CA
bash "${SCRIPT_DIR}/setup_ca.sh"
echo ""

# Step 2: Issue certificate for partition 1
bash "${SCRIPT_DIR}/issue_cert.sh" 1
echo ""

# Step 3: Issue certificate for partition 2
bash "${SCRIPT_DIR}/issue_cert.sh" 2
echo ""

# Step 4: Generate CRLs
bash "${SCRIPT_DIR}/gen_crl.sh"
echo ""

echo "=========================================="
echo " All PKI artifacts generated successfully"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. pip install -r requirements.txt"
echo "  2. python src/reproduce.py"

"""
setup_pki.py — Python-based PKI setup (cross-platform alternative to shell scripts).

Generates all PKI artifacts using the `cryptography` library:
  - CA key + cert
  - Server certs for partition 1 and partition 2 (with different CDP URIs)
  - CRL files for each partition

Usage:
  python src/setup_pki.py
"""

import datetime
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.x509 import (
    CRLDistributionPoints,
    DistributionPoint,
    UniformResourceIdentifier,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PKI-Setup] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CERTS_DIR = PROJECT_ROOT / "certs"

CRL_BASE_URL = "http://localhost:9000/crl"


def generate_ca() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Generate a self-signed CA certificate."""
    log.info("Generating CA key pair...")
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test CRL Partition CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Speech SDK CRL Test"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    log.info(f"  CA cert serial: {ca_cert.serial_number}")
    return ca_key, ca_cert


def generate_server_cert(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    partition: int,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Generate a server certificate with CDP pointing to specific partition."""
    log.info(f"Generating server certificate for partition {partition}...")

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Speech SDK CRL Test"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    ])

    crl_url = f"{CRL_BASE_URL}/partition{partition}.crl"
    now = datetime.datetime.now(datetime.timezone.utc)

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress_from_str("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.CRLDistributionPoints([
                x509.DistributionPoint(
                    full_name=[x509.UniformResourceIdentifier(crl_url)],
                    relative_name=None,
                    crl_issuer=None,
                    reasons=None,
                )
            ]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    log.info(f"  Server cert serial: {server_cert.serial_number}")
    log.info(f"  CDP: {crl_url}")
    return server_key, server_cert


def generate_crl(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    partition: int,
    revoked_serials: list[int] | None = None,
) -> x509.CertificateRevocationList:
    """Generate a CRL for a specific partition."""
    log.info(f"Generating CRL for partition {partition}...")

    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca_cert.subject)
        .last_update(now)
        .next_update(now + datetime.timedelta(days=30))
    )

    # Add revoked certificates if any
    if revoked_serials:
        for serial in revoked_serials:
            revoked = (
                x509.RevokedCertificateBuilder()
                .serial_number(serial)
                .revocation_date(now)
                .build()
            )
            builder = builder.add_revoked_certificate(revoked)
            log.info(f"  Revoked serial: {serial}")

    crl = builder.sign(ca_key, hashes.SHA256())
    log.info(f"  CRL entries: {len(crl) if revoked_serials else 0}")
    return crl


def ipaddress_from_str(addr: str):
    """Convert string IP to ipaddress object."""
    import ipaddress
    return ipaddress.IPv4Address(addr)


def save_key(key: rsa.RSAPrivateKey, path: Path):
    """Save private key to PEM file."""
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def save_cert(cert: x509.Certificate, path: Path):
    """Save certificate to PEM file."""
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def save_crl(crl: x509.CertificateRevocationList, path: Path):
    """Save CRL to DER file (standard format for CRL distribution)."""
    path.write_bytes(crl.public_bytes(serialization.Encoding.DER))


def main():
    log.info("=" * 60)
    log.info("Speech SDK CRL Partition Test — PKI Setup")
    log.info("=" * 60)

    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Generate CA
    log.info("")
    log.info("--- Step 1: Generate CA ---")
    ca_key, ca_cert = generate_ca()
    save_key(ca_key, CERTS_DIR / "ca-key.pem")
    save_cert(ca_cert, CERTS_DIR / "ca-cert.pem")
    log.info(f"  Saved: {CERTS_DIR / 'ca-key.pem'}")
    log.info(f"  Saved: {CERTS_DIR / 'ca-cert.pem'}")

    # Step 2: Generate server cert for partition 1
    log.info("")
    log.info("--- Step 2: Server cert (partition 1) ---")
    srv1_key, srv1_cert = generate_server_cert(ca_key, ca_cert, partition=1)
    save_key(srv1_key, CERTS_DIR / "server-part1-key.pem")
    save_cert(srv1_cert, CERTS_DIR / "server-part1-cert.pem")
    log.info(f"  Saved: server-part1-key.pem, server-part1-cert.pem")

    # Step 3: Generate server cert for partition 2
    log.info("")
    log.info("--- Step 3: Server cert (partition 2) ---")
    srv2_key, srv2_cert = generate_server_cert(ca_key, ca_cert, partition=2)
    save_key(srv2_key, CERTS_DIR / "server-part2-key.pem")
    save_cert(srv2_cert, CERTS_DIR / "server-part2-cert.pem")
    log.info(f"  Saved: server-part2-key.pem, server-part2-cert.pem")

    # Step 4: Generate CRL for partition 1 (empty — no revoked certs)
    log.info("")
    log.info("--- Step 4: CRL (partition 1) ---")
    crl1 = generate_crl(ca_key, ca_cert, partition=1)
    save_crl(crl1, CERTS_DIR / "partition1.crl")
    log.info(f"  Saved: partition1.crl")

    # Step 5: Generate CRL for partition 2 (empty — no revoked certs)
    log.info("")
    log.info("--- Step 5: CRL (partition 2) ---")
    crl2 = generate_crl(ca_key, ca_cert, partition=2)
    save_crl(crl2, CERTS_DIR / "partition2.crl")
    log.info(f"  Saved: partition2.crl")

    # Step 6: Generate a "conflict" CRL for partition 1 that revokes partition 2's cert
    # This creates the scenario where the stale cached CRL says "cert is revoked"
    log.info("")
    log.info("--- Step 6: Conflict CRL (partition1 with partition2 cert revoked) ---")
    crl1_conflict = generate_crl(
        ca_key, ca_cert, partition=1,
        revoked_serials=[srv2_cert.serial_number],
    )
    save_crl(crl1_conflict, CERTS_DIR / "partition1_conflict.crl")
    log.info(f"  Saved: partition1_conflict.crl")
    log.info(f"  (This CRL marks partition2's cert as REVOKED)")

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("PKI Setup Complete!")
    log.info("=" * 60)
    log.info("")
    log.info("Generated files:")
    for f in sorted(CERTS_DIR.glob("*")):
        if f.is_file():
            log.info(f"  {f.name} ({f.stat().st_size} bytes)")
    log.info("")
    log.info("To reproduce the CRL conflict:")
    log.info("  1. Copy partition1_conflict.crl → partition1.crl")
    log.info("     (makes cached CRL claim partition2 cert is revoked)")
    log.info("  2. Run: python src/reproduce.py")
    log.info("")
    log.info("Cert serial numbers (for reference):")
    log.info(f"  Partition 1 cert: {srv1_cert.serial_number}")
    log.info(f"  Partition 2 cert: {srv2_cert.serial_number}")


if __name__ == "__main__":
    main()

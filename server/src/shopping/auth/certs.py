"""Client certificates for mTLS (optional second lock in front of the API).

A small private CA lives in DATA_DIR/ca (key file mode 0600). The reverse proxy trusts ca.pem and passes
each verified client certificate's SHA-256 fingerprint to the app, which matches it to the device record.
Certificates are issued as password-protected PKCS#12 files for importing into Firefox.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def init_ca(ca_dir: Path, name: str = "vibe-groceries client CA", *, public_dir: Path | None = None) -> Path:
    """Create the CA once; returns the path of the public ca.pem for the proxy. The private key stays in
    ca_dir (mode 0700); only the certificate is copied to public_dir, which the proxy mounts read-only."""
    ca_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ca_dir, 0o700)
    key_path, pem_path = ca_dir / "ca.key", ca_dir / "ca.pem"
    if key_path.exists() and pem_path.exists():
        return _publish(pem_path, public_dir)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    _write_private(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pem_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return _publish(pem_path, public_dir)


def _publish(pem_path: Path, public_dir: Path | None) -> Path:
    if public_dir is None:
        return pem_path
    public_dir.mkdir(parents=True, exist_ok=True)
    out = public_dir / "ca.pem"
    out.write_bytes(pem_path.read_bytes())
    os.chmod(out, 0o644)
    return out


def issue_client_cert(ca_dir: Path, device_name: str, *, days: int = 730) -> tuple[bytes, str, str]:
    """Returns (pkcs12 bytes, import password, sha256 fingerprint hex of the certificate)."""
    ca_key = serialization.load_pem_private_key((ca_dir / "ca.key").read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate((ca_dir / "ca.pem").read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"vibe-groceries: {device_name}"[:64])]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    password = secrets.token_urlsafe(12)
    p12 = pkcs12.serialize_key_and_certificates(f"vibe-groceries {device_name}".encode(), key, cert, [ca_cert],
                                                serialization.BestAvailableEncryption(password.encode()))
    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return p12, password, fingerprint

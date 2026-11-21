"""Paired devices: how a browser proves it's one of ours.

1. Pairing: a person creates a one-time code (CLI on the server, or an already-paired device). The browser
   generates an ECDSA P-256 key pair that can't be exported, and sends the public half with the code.
2. Each session: the browser asks for a challenge, signs it, and gets a short-lived access token (memory
   only, on both sides). Revoking a device kills its tokens at once.
3. Optionally (MTLS_REQUIRED), the reverse proxy verifies a per-device client certificate and passes its
   SHA-256 fingerprint; the app checks it belongs to the same device as the token.

The signed message is `vibe-groceries:auth:v1:<device_id>:<challenge>`; WebCrypto signatures are raw r||s
(IEEE P1363), converted to DER here for verification.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select
from sqlalchemy.orm import Session

from shopping.models import Device, PairingCode, utcnow

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L, U
CODE_LENGTH = 16  # ~78 bits
PAIRING_TTL = timedelta(minutes=10)
CHALLENGE_TTL_SECONDS = 120


class DeviceAuthError(Exception):
    """Authentication failed. Messages are safe to show to the client (no detail about which check failed
    beyond what the legitimate user needs)."""


# -- helpers ------------------------------------------------------------------------------

def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize_fingerprint(fp: str | None) -> str | None:
    if not fp:
        return None
    fp = fp.replace(":", "").strip().lower()
    return fp if len(fp) == 64 and all(c in "0123456789abcdef" for c in fp) else None


def load_public_key(jwk: dict) -> ec.EllipticCurvePublicKey:
    """A P-256 public key from a JWK, validated (right curve, point on the curve, no private part)."""
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise DeviceAuthError("Device key must be an EC P-256 public key.")
    if "d" in jwk:
        raise DeviceAuthError("Send only the public key.")
    try:
        x, y = _b64url_decode(jwk["x"]), _b64url_decode(jwk["y"])
        if len(x) != 32 or len(y) != 32:
            raise ValueError
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()).public_key()
    except (KeyError, ValueError) as exc:
        raise DeviceAuthError("Device key is malformed.") from exc


def verify_signature(public_key: ec.EllipticCurvePublicKey, message: bytes, signature_b64url: str) -> bool:
    try:
        raw = _b64url_decode(signature_b64url)
    except ValueError:
        return False
    if len(raw) == 64:  # WebCrypto: r||s
        sig = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    else:
        sig = raw  # already DER
    try:
        public_key.verify(sig, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


def auth_message(device_id: str, challenge: str) -> bytes:
    return f"vibe-groceries:auth:v1:{device_id}:{challenge}".encode()


# -- pairing --------------------------------------------------------------------------------

def create_pairing_code(session: Session, *, device_name: str | None = None, created_by: str = "cli",
                        cert_fingerprint: str | None = None) -> str:
    """A one-time code (shown once; only its hash is stored)."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    session.add(PairingCode(code_hash=_hash(code), device_name=(device_name or "").strip()[:64] or None, created_by=created_by,
                            cert_fingerprint=normalize_fingerprint(cert_fingerprint), expires_at=utcnow() + PAIRING_TTL))
    session.flush()
    return format_code(code)


def pair(session: Session, *, code: str, public_key_jwk: dict, name: str | None,
         cert_fingerprint: str | None = None, mtls_required: bool = False) -> Device:
    row = session.scalar(select(PairingCode).where(PairingCode.code_hash == _hash(normalize_code(code))))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise DeviceAuthError("That pairing code is invalid or has expired. Create a new one.")
    fp = normalize_fingerprint(cert_fingerprint)
    if mtls_required and not fp:
        raise DeviceAuthError("A client certificate is required.")
    if row.cert_fingerprint and row.cert_fingerprint != fp:
        raise DeviceAuthError("This pairing code belongs to a different client certificate.")
    load_public_key(public_key_jwk)  # validates
    device_name = ((name or "").strip() or row.device_name or "Browser")[:64]
    device = Device(id=uuid.uuid4().hex, name=device_name, public_key_jwk=json.dumps(public_key_jwk, sort_keys=True),
                    cert_fingerprint=fp or row.cert_fingerprint)
    row.used_at = utcnow()
    session.add(device)
    session.flush()
    return device


def revoke(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise DeviceAuthError("No such device.")
    if device.revoked_at is None:
        device.revoked_at = utcnow()
    tokens.revoke_device(device_id)
    session.flush()
    return device


def active_device(session: Session, device_id: str) -> Device | None:
    d = session.get(Device, device_id)
    return d if d is not None and d.revoked_at is None else None


def device_dict(d: Device) -> dict:
    return {"id": d.id, "name": d.name, "created_at": d.created_at.isoformat(),
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "revoked": d.revoked_at is not None, "has_certificate": bool(d.cert_fingerprint)}


# -- challenges and access tokens (in memory: a restart just means devices sign in again) -----

class _Challenges:
    def __init__(self):
        self._items: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, device_id: str) -> str:
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self._items = {k: v for k, v in self._items.items() if v[1] > now}
            self._items[nonce] = (device_id, now + CHALLENGE_TTL_SECONDS)
        return nonce

    def consume(self, device_id: str, nonce: str) -> bool:
        with self._lock:
            item = self._items.pop(nonce, None)  # single use, whatever the outcome
        return item is not None and item[0] == device_id and item[1] > time.time()


@dataclass
class _Token:
    device_id: str
    expires: float
    cert_fingerprint: str | None


class _Tokens:
    def __init__(self):
        self._items: dict[str, _Token] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, device_id: str, minutes: int, cert_fingerprint: str | None) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        expires = time.time() + minutes * 60
        with self._lock:
            now = time.time()
            self._items = {k: v for k, v in self._items.items() if v.expires > now}
            self._items[self._key(token)] = _Token(device_id, expires, cert_fingerprint)
        return token, expires

    def resolve(self, token: str) -> _Token | None:
        with self._lock:
            t = self._items.get(self._key(token))
        return t if t is not None and t.expires > time.time() else None

    def revoke_device(self, device_id: str) -> None:
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v.device_id != device_id}


challenges = _Challenges()
tokens = _Tokens()


def sign_in(session: Session, *, device_id: str, challenge: str, signature: str, cert_fingerprint: str | None,
            mtls_required: bool, minutes: int) -> tuple[str, float, Device]:
    """Exchange a signed challenge for an access token."""
    device = active_device(session, device_id)
    ok_challenge = challenges.consume(device_id, challenge)
    if device is None or not ok_challenge:
        raise DeviceAuthError("Sign-in failed. If this device was revoked, pair it again.")
    fp = normalize_fingerprint(cert_fingerprint)
    if mtls_required and (not fp or not device.cert_fingerprint or not hmac.compare_digest(fp, device.cert_fingerprint)):
        raise DeviceAuthError("Sign-in failed: this device's client certificate is missing or doesn't match.")
    if not verify_signature(load_public_key(json.loads(device.public_key_jwk)), auth_message(device_id, challenge), signature):
        raise DeviceAuthError("Sign-in failed. If this device was revoked, pair it again.")
    device.last_seen_at = utcnow()
    token, expires = tokens.issue(device.id, minutes, fp)
    return token, expires, device

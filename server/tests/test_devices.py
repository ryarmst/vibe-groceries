import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from shopping.auth import devices as dev
from shopping.models import PairingCode


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    n = key.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": b64u(n.x.to_bytes(32, "big")), "y": b64u(n.y.to_bytes(32, "big"))}
    return key, jwk


def webcrypto_sign(key, message: bytes) -> str:
    """Like WebCrypto: raw r||s, base64url."""
    r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
    return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def paired(session, **kw):
    code = dev.create_pairing_code(session, device_name="Ryan laptop", **kw)
    key, jwk = keypair()
    return key, dev.pair(session, code=code.lower().replace("-", " "), public_key_jwk=jwk, name=None,
                         cert_fingerprint=kw.get("cert_fingerprint"))


def test_pairing_code_single_use_and_hashed(session):
    code = dev.create_pairing_code(session, device_name="Steph")
    assert len(dev.normalize_code(code)) == 16 and session.query(PairingCode).one().code_hash != dev.normalize_code(code)
    _, jwk = keypair()
    d = dev.pair(session, code=code, public_key_jwk=jwk, name=None)
    assert d.name == "Steph"
    with pytest.raises(dev.DeviceAuthError):
        dev.pair(session, code=code, public_key_jwk=jwk, name=None)
    with pytest.raises(dev.DeviceAuthError):
        dev.pair(session, code="AAAA-BBBB-CCCC-DDDD", public_key_jwk=jwk, name=None)


def test_rejects_bad_keys(session):
    code = dev.create_pairing_code(session)
    for bad in ({"kty": "RSA"}, {"kty": "EC", "crv": "P-384", "x": "a", "y": "b"},
                {"kty": "EC", "crv": "P-256", "x": b64u(b"\1" * 32), "y": b64u(b"\2" * 32)},  # not on the curve
                {**keypair()[1], "d": "private!"}):
        with pytest.raises(dev.DeviceAuthError):
            dev.pair(session, code=code, public_key_jwk=bad, name="x")


def test_sign_in_with_webcrypto_signature(session):
    key, d = paired(session)
    ch = dev.challenges.issue(d.id)
    token, expires, device = dev.sign_in(session, device_id=d.id, challenge=ch, signature=webcrypto_sign(key, dev.auth_message(d.id, ch)),
                                         cert_fingerprint=None, mtls_required=False, minutes=15)
    assert dev.tokens.resolve(token).device_id == d.id
    # Challenges are single use, and a signature over a different challenge fails.
    with pytest.raises(dev.DeviceAuthError):
        dev.sign_in(session, device_id=d.id, challenge=ch, signature=webcrypto_sign(key, dev.auth_message(d.id, ch)),
                    cert_fingerprint=None, mtls_required=False, minutes=15)
    ch2 = dev.challenges.issue(d.id)
    other_key, _ = keypair()
    with pytest.raises(dev.DeviceAuthError):
        dev.sign_in(session, device_id=d.id, challenge=ch2, signature=webcrypto_sign(other_key, dev.auth_message(d.id, ch2)),
                    cert_fingerprint=None, mtls_required=False, minutes=15)
    # Revocation kills existing tokens and future sign-ins.
    dev.revoke(session, d.id)
    assert dev.tokens.resolve(token) is None
    ch3 = dev.challenges.issue(d.id)
    with pytest.raises(dev.DeviceAuthError):
        dev.sign_in(session, device_id=d.id, challenge=ch3, signature=webcrypto_sign(key, dev.auth_message(d.id, ch3)),
                    cert_fingerprint=None, mtls_required=False, minutes=15)


def test_mtls_binding(session):
    fp = "ab" * 32
    key, d = paired(session, cert_fingerprint=fp)
    assert d.cert_fingerprint == fp

    def attempt(cert):
        ch = dev.challenges.issue(d.id)
        return dev.sign_in(session, device_id=d.id, challenge=ch, signature=webcrypto_sign(key, dev.auth_message(d.id, ch)),
                           cert_fingerprint=cert, mtls_required=True, minutes=15)

    with pytest.raises(dev.DeviceAuthError):
        attempt(None)
    with pytest.raises(dev.DeviceAuthError):
        attempt("cd" * 32)
    token, _, _ = attempt("AB:" * 31 + "AB")
    assert dev.tokens.resolve(token).cert_fingerprint == fp
    # A code issued for one certificate can't be used with another.
    code = dev.create_pairing_code(session, cert_fingerprint=fp)
    with pytest.raises(dev.DeviceAuthError):
        dev.pair(session, code=code, public_key_jwk=keypair()[1], name="x", cert_fingerprint="ef" * 32, mtls_required=True)

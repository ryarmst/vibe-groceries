"""Pairing, sign-in, and device management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from shopping.api.deps import Caller, cert_fingerprint, limit_auth, require_device
from shopping.auth import devices as dev
from shopping.config import settings
from shopping.database import session_scope
from shopping.models import Device

router = APIRouter(prefix="/api")


class PairBody(BaseModel):
    code: str = Field(min_length=8, max_length=40)
    public_key: dict
    name: str | None = Field(default=None, max_length=64)


class ChallengeBody(BaseModel):
    device_id: str = Field(min_length=8, max_length=32)


class TokenBody(BaseModel):
    device_id: str = Field(min_length=8, max_length=32)
    challenge: str = Field(min_length=16, max_length=128)
    signature: str = Field(min_length=40, max_length=200)


@router.post("/pair", dependencies=[Depends(limit_auth)])
def pair(body: PairBody, request: Request):
    with session_scope() as session:
        device = dev.pair(session, code=body.code, public_key_jwk=body.public_key, name=body.name,
                          cert_fingerprint=cert_fingerprint(request), mtls_required=settings.mtls_required)
        return {"device_id": device.id, "name": device.name}


@router.post("/auth/challenge", dependencies=[Depends(limit_auth)])
def challenge(body: ChallengeBody):
    # Issued for any id (no device enumeration); only a real device can sign it.
    return {"challenge": dev.challenges.issue(body.device_id)}


@router.post("/auth/token", dependencies=[Depends(limit_auth)])
def token(body: TokenBody, request: Request):
    with session_scope() as session:
        tok, expires, device = dev.sign_in(session, device_id=body.device_id, challenge=body.challenge, signature=body.signature,
                                           cert_fingerprint=cert_fingerprint(request), mtls_required=settings.mtls_required,
                                           minutes=settings.access_token_minutes)
        return {"access_token": tok, "expires_at": expires, "device": dev.device_dict(device)}


@router.get("/devices")
def devices(caller: Caller = Depends(require_device)):
    with session_scope() as session:
        rows = [dev.device_dict(d) for d in session.scalars(select(Device).order_by(Device.created_at))]
    return {"devices": rows, "you": caller.device_id}


@router.delete("/devices/{device_id}")
def revoke(device_id: str, caller: Caller = Depends(require_device)):
    with session_scope() as session:
        d = dev.revoke(session, device_id)
        return {"revoked": d.id, "was_you": d.id == caller.device_id}


class PairingCodeBody(BaseModel):
    name: str | None = Field(default=None, max_length=64)


@router.post("/devices/pairing-code")
def new_pairing_code(body: PairingCodeBody, caller: Caller = Depends(require_device)):
    if settings.mtls_required:
        # A new browser also needs a client certificate, which is issued on the server (CLI).
        return {"code": None, "message": "mTLS is on: run `vibe pair --name NAME --cert` on the server to get a code and a certificate."}
    with session_scope() as session:
        return {"code": dev.create_pairing_code(session, device_name=body.name, created_by=caller.device_id), "expires_in_minutes": 10}

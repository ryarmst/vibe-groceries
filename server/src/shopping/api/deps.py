"""Request plumbing: who's calling (device auth), client IP, and errors as JSON."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from shopping import attribution
from shopping.appsettings import SettingsError
from shopping.auth import devices as dev
from shopping.auth.ratelimit import RateLimiter
from shopping.auth.session import AuthRequired
from shopping.config import settings
from shopping.core.service import ShoppingError
from shopping.database import session_scope
from shopping.models import utcnow
from shopping.retailer.client import RetailerError, RetailerUnavailable
from shopping.secrets.vault import VaultError

log = logging.getLogger(__name__)

CERT_HEADER = "x-client-cert-sha256"  # set by the reverse proxy from the verified client certificate

auth_limiter = RateLimiter(limit=20, window_seconds=60)  # pairing and sign-in, per client IP
api_limiter = RateLimiter(limit=600, window_seconds=60)  # everything else, per device

_last_seen_write: dict[str, float] = {}


@dataclass(frozen=True)
class Caller:
    device_id: str
    name: str


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def cert_fingerprint(request: Request) -> str | None:
    return dev.normalize_fingerprint(request.headers.get(CERT_HEADER))


def limit_auth(request: Request) -> None:
    if not auth_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many attempts; wait a minute.")


async def require_device(request: Request) -> Caller:
    """FastAPI dependency: a valid access token from a non-revoked device (and its certificate, if required)."""
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    t = dev.tokens.resolve(token) if token else None
    if t is None:
        raise HTTPException(401, "Sign in required.", headers={"WWW-Authenticate": "Bearer"})
    if settings.mtls_required:
        fp = cert_fingerprint(request)
        if not fp or fp != t.cert_fingerprint:
            raise HTTPException(401, "Client certificate missing or changed; sign in again.")
    if not api_limiter.allow(t.device_id):
        raise HTTPException(429, "Slow down.")
    with session_scope() as session:
        device = dev.active_device(session, t.device_id)
        if device is None:
            dev.tokens.revoke_device(t.device_id)
            raise HTTPException(401, "This device was revoked.")
        now = time.time()
        if now - _last_seen_write.get(device.id, 0) > 300:  # don't write on every request
            device.last_seen_at = utcnow()
            _last_seen_write[device.id] = now
        attribution.current_device.set(device.id)
        return Caller(device.id, device.name)


def install_error_handlers(app) -> None:
    def err(status: int, message: str, code: str | None = None):
        return JSONResponse({"error": message, **({"code": code} if code else {})}, status_code=status)

    @app.exception_handler(HTTPException)
    async def _http(_, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(dev.DeviceAuthError)
    async def _devauth(_, exc):
        return err(401, str(exc))

    @app.exception_handler(AuthRequired)
    async def _needs_session(_, exc):
        return err(409, str(exc), "needs_session")

    @app.exception_handler(RetailerUnavailable)
    async def _unavailable(_, exc):
        return err(503, str(exc), "retailer_unavailable")

    @app.exception_handler(RetailerError)
    async def _retailer(_, exc):
        return err(502, str(exc), "retailer_error")

    @app.exception_handler(ShoppingError)
    async def _shopping(_, exc):
        return err(400, str(exc))

    @app.exception_handler(SettingsError)
    async def _settings(_, exc):
        return err(400, str(exc))

    @app.exception_handler(VaultError)
    async def _vault(_, exc):
        return err(400, str(exc))

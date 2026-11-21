"""Retailer authentication session.

PC Express uses OAuth (Oracle IDCS at accounts.pcid.ca). The token and refresh endpoints
sit behind bot protection that rejects non-browser clients, so this application cannot
log in or refresh on its own. Instead the user pastes the site's `AccessToken` cookie
(a JWT valid for ~1 hour) into the /auth page. The retailer API itself accepts that
bearer token from this server.

The rest of the application only uses `ensure_authenticated()` / `get_headers()`, so a
browser-assisted refresh mechanism can replace the manual paste later without changes
elsewhere.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class AuthRequired(Exception):
    """Raised when an operation needs a retailer login and no valid token is available."""


@dataclass
class AuthStatus:
    state: str  # "connected" | "expired" | "required"
    expires_at: datetime | None
    seconds_remaining: int | None
    last_updated: datetime | None
    customer_id: str | None

    @property
    def label(self) -> str:
        return {"connected": "Connected", "expired": "Expired", "required": "Authentication required"}[self.state]


def _jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a JWT (expected three dot-separated parts).")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not decode the token payload.") from exc


class FileTokenStore:
    """The token as a 0600 JSON file (v1 behaviour; used in tests and local development)."""

    def __init__(self, session_dir: Path):
        self._path = session_dir / "token.json"
        session_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(session_dir, 0o700)
        except OSError:
            pass

    def load(self) -> dict | None:
        if not self._path.is_file():
            return None
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return None

    def save(self, record: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(record, fh)
        os.replace(tmp, self._path)

    def delete(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


class VaultTokenStore:
    """The token encrypted in the secrets vault (v2). A short in-memory cache avoids a decrypt per call."""

    NAME = "retailer:access_token"

    def __init__(self, vault, session_scope):
        self._vault, self._scope = vault, session_scope
        self._cache: dict | None = None
        self._cached_at = 0.0

    def load(self) -> dict | None:
        if self._cache is not None and time.time() - self._cached_at < 30:
            return self._cache
        with self._scope() as session:
            raw = self._vault.get(session, self.NAME, touch=False)
        self._cache, self._cached_at = (json.loads(raw) if raw else None), time.time()
        return self._cache

    def save(self, record: dict) -> None:
        with self._scope() as session:
            self._vault.set(session, self.NAME, json.dumps(record), by=record.get("by"))
        self._cache, self._cached_at = record, time.time()

    def delete(self) -> None:
        with self._scope() as session:
            self._vault.delete(session, self.NAME)
        self._cache, self._cached_at = None, time.time()


class AuthSession:
    # Treat a token as expired slightly early so calls don't fail mid-flight.
    EXPIRY_SKEW_SECONDS = 60

    def __init__(self, store):
        # A directory means the file store (v1 and tests); otherwise any object with load/save/delete.
        self._store = FileTokenStore(store) if isinstance(store, Path) else store

    # -- storage -------------------------------------------------------------------
    def _load(self) -> dict | None:
        return self._store.load()

    def set_access_token(self, token: str, *, by: str | None = None) -> AuthStatus:
        token = token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        claims = _jwt_claims(token)
        if "exp" not in claims or "sub" not in claims:
            raise ValueError("Token is missing exp/sub claims; is this the AccessToken cookie?")
        if claims["exp"] <= time.time():
            raise ValueError("That token has already expired. Reload nofrills.ca and copy a fresh one.")
        current = self._load()
        if current and current.get("access_token") == token:
            return self.status()  # the extension re-sends on every cookie event; nothing changed
        self._store.save({"access_token": token, "updated_at": time.time(), "by": by})
        return self.status()

    async def clear(self) -> None:
        self._store.delete()

    # -- status --------------------------------------------------------------------
    def status(self) -> AuthStatus:
        record = self._load()
        if not record:
            return AuthStatus("required", None, None, None, None)
        claims = _jwt_claims(record["access_token"])
        exp = float(claims["exp"])
        remaining = int(exp - time.time())
        updated = datetime.fromtimestamp(record.get("updated_at", 0), tz=timezone.utc)
        state = "connected" if remaining > self.EXPIRY_SKEW_SECONDS else "expired"
        return AuthStatus(state, datetime.fromtimestamp(exp, tz=timezone.utc), max(remaining, 0), updated, claims.get("sub"))

    # -- interface used by the retailer client -------------------------------------
    async def refresh_if_needed(self) -> None:
        # Refresh is not possible server-side (see module docstring). Nothing to do.
        return None

    async def ensure_authenticated(self) -> str:
        """Return the customer id (PC id) for the logged-in user, or raise AuthRequired."""
        await self.refresh_if_needed()
        st = self.status()
        if st.state != "connected":
            raise AuthRequired(
                "Retailer session is "
                + ("expired" if st.state == "expired" else "not set")
                + ". Open nofrills.ca in the browser with the extension installed (and log in) to reconnect."
            )
        return st.customer_id or ""

    async def get_headers(self) -> dict[str, str]:
        await self.ensure_authenticated()
        record = self._load() or {}
        return {"authorization": "Bearer " + record["access_token"], "is-helios-account": "true"}

"""Process-wide singletons: the secrets vault, the No Frills session, the retailer client."""

from __future__ import annotations

from shopping.auth.session import AuthSession, VaultTokenStore
from shopping.config import settings
from shopping.database import session_scope
from shopping.retailer.client import PCExpressClient
from shopping.secrets.vault import Vault, load_master_key

PUBLIC_URL = settings.public_url

vault = Vault(load_master_key(settings.master_key_b64, settings.master_key_file))
auth = AuthSession(VaultTokenStore(vault, session_scope))
_client: PCExpressClient | None = None


def client() -> PCExpressClient:
    global _client
    if _client is None:
        _client = PCExpressClient(
            api_base=settings.pcx_api_base,
            api_key=settings.pcx_api_key,
            banner=settings.banner,
            store_id=settings.store_id,
            auth=auth,
            raw_dir=settings.raw_dir,
        )
    return _client


async def shutdown() -> None:
    if _client is not None:
        await _client.aclose()

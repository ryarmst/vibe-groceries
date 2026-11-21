"""Application settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing environment wins."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    store_id: str
    banner: str
    pcx_api_key: str
    pcx_api_base: str
    host: str
    port: int
    log_level: str
    mcp_token: str
    public_url: str
    deal_scan_hours: float = 24.0  # refresh the deal catalogue this often; 0 disables the background scan
    allowed_hosts: list[str] = field(default_factory=list)
    # -- v2 --------------------------------------------------------------------------------
    master_key_b64: str = ""  # MASTER_KEY: 32 random bytes, base64; encrypts the secrets vault
    mtls_required: bool = False  # require the proxy-verified client-certificate fingerprint on every API call
    # Header the proxy uses for the verified client certificate's SHA-256 fingerprint:
    # Caddy (deploy/) sets x-client-cert-sha256; Cloudflare's "Add TLS client auth headers" sets cf-cert-sha256.
    cert_header: str = "x-client-cert-sha256"
    cert_verified_header: str = ""  # optional: a header that must equal "true" (Cloudflare: cf-cert-verified)
    client_ip_header: str = ""  # header with the real client IP set by the proxy (Cloudflare: cf-connecting-ip)
    mcp_enabled: bool = False  # the v1 MCP endpoint (for Claude Desktop/Code); behind device auth when on
    timezone: str = "America/Toronto"
    monthly_budget_usd: float = 10.0  # default LLM spend cap; adjustable at runtime from the extension
    access_token_minutes: int = 15
    jobs_enabled: bool = True
    trusted_proxies: str = ""  # FORWARDED_ALLOW_IPS: proxy addresses whose X-Forwarded-For is trusted

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def session_dir(self) -> Path:
        return self.data_dir / "session"

    @property
    def raw_dir(self) -> Path:
        """Recent raw retailer responses, kept for debugging (secrets are never in these)."""
        return self.data_dir / "raw"

    @property
    def master_key_file(self) -> Path:
        """Fallback key location for development only; production sets MASTER_KEY in the environment."""
        return self.data_dir / "master.key"


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    _load_dotenv(Path(os.environ.get("SHOPPING_ENV_FILE", ".env")))
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    port = int(os.environ.get("PORT", "8000"))
    public_url = os.environ.get("PUBLIC_URL", f"http://localhost:{port}").rstrip("/")
    # Hosts the app answers to (DNS-rebinding protection): loopback, PUBLIC_URL's host, plus ALLOWED_HOSTS.
    hosts = ",".join(["localhost", "127.0.0.1", urlsplit(public_url).hostname or "", os.environ.get("ALLOWED_HOSTS", "")])
    return Settings(
        data_dir=data_dir,
        store_id=os.environ.get("STORE_ID", "3728"),
        banner=os.environ.get("BANNER", "nofrills"),
        pcx_api_key=os.environ.get("PCX_API_KEY", ""),
        pcx_api_base=os.environ.get("PCX_API_BASE", "https://api.pcexpress.ca/pcx-bff/api"),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        mcp_token=os.environ.get("MCP_TOKEN", ""),
        public_url=public_url,
        deal_scan_hours=float(os.environ.get("DEAL_SCAN_HOURS", "24")),
        allowed_hosts=list(dict.fromkeys(h.strip() for h in hosts.split(",") if h.strip())),
        master_key_b64=os.environ.get("MASTER_KEY", ""),
        mtls_required=_bool("MTLS_REQUIRED", False),
        cert_header=os.environ.get("CERT_HEADER", "x-client-cert-sha256").strip().lower(),
        cert_verified_header=os.environ.get("CERT_VERIFIED_HEADER", "").strip().lower(),
        client_ip_header=os.environ.get("CLIENT_IP_HEADER", "").strip().lower(),
        mcp_enabled=_bool("MCP_ENABLED", False),
        timezone=os.environ.get("TZ", "America/Toronto"),
        monthly_budget_usd=float(os.environ.get("MONTHLY_BUDGET_USD", "10")),
        access_token_minutes=int(os.environ.get("ACCESS_TOKEN_MINUTES", "15")),
        jobs_enabled=_bool("JOBS_ENABLED", True),
        trusted_proxies=os.environ.get("FORWARDED_ALLOW_IPS", ""),
    )


settings = load_settings()

"""Configuration settings for the vin-mcp server."""

import os

from dotenv import load_dotenv

load_dotenv()

# --- vPIC API (NHTSA) ---
# Public, no API key required. Base URL includes the /api/vehicles prefix so
# tool paths are just the endpoint name (e.g. "DecodeVinValues/<vin>").
VPIC_BASE_URL: str = os.getenv(
    "VPIC_BASE_URL", "https://vpic.nhtsa.dot.gov/api/vehicles"
)
# Vehicle specs are static per VIN. The cache exists only to be polite to
# NHTSA's automated rate-control mechanism, not for correctness.
VPIC_CACHE_TTL_SECONDS: int = int(os.getenv("VPIC_CACHE_TTL_SECONDS", "86400"))
VPIC_CACHE_MAXSIZE: int = int(os.getenv("VPIC_CACHE_MAXSIZE", "8192"))
VPIC_TIMEOUT_SECONDS: float = float(os.getenv("VPIC_TIMEOUT_SECONDS", "30"))

# --- MCP transport ---
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")  # "stdio" | "http"
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "3034"))

# --- OAuth (HTTP transport only) ---
# - MCP_BASE_URL: public URL of the server, e.g. https://vin.nlma.io. Used by
#   the OAuth issuer metadata + DCR. Must match what clients see.
# - MCP_OWNER_PASSWORD: password required at /login before /authorize completes.
#   Required for HTTP transport. Generate via
#   `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
# - MCP_OAUTH_STATE_DIR: where to persist OAuth state (registered clients,
#   tokens). In production use /var/lib/vin-mcp/oauth-state.
# - MCP_OAUTH_REDIRECT_DOMAINS: comma-separated redirect-URI host suffixes.
MCP_BASE_URL: str = os.getenv("MCP_BASE_URL", "http://localhost:3034")
MCP_OWNER_PASSWORD: str = os.getenv("MCP_OWNER_PASSWORD", "")
MCP_OAUTH_STATE_DIR: str = os.getenv("MCP_OAUTH_STATE_DIR", ".oauth-state")
MCP_OAUTH_REDIRECT_DOMAINS: list[str] = [
    d.strip()
    for d in os.getenv(
        "MCP_OAUTH_REDIRECT_DOMAINS",
        "claude.ai,claude.com,chatgpt.com,openai.com,localhost",
    ).split(",")
    if d.strip()
]

# --- Google sign-in gate (optional; HTTP transport only) ---
# When GOOGLE_WEB_CLIENT_ID/SECRET are set, /login offers "Sign in with
# Google". vin requests only `openid email` (online access, no refresh token):
# it calls no Google API, it just verifies who the human is, then checks the
# returned email against GOOGLE_ALLOWED_EMAILS before letting OAuth proceed.
# Use a *web* OAuth client whose authorized redirect URI includes
# <MCP_BASE_URL>/oauth/google/callback.
GOOGLE_WEB_CLIENT_ID: str = os.getenv("GOOGLE_WEB_CLIENT_ID", "")
GOOGLE_WEB_CLIENT_SECRET: str = os.getenv("GOOGLE_WEB_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI: str = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    f"{MCP_BASE_URL.rstrip('/')}/oauth/google/callback",
)
GOOGLE_ALLOWED_EMAILS: list[str] = [
    e.strip().lower()
    for e in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
    if e.strip()
]
# Domain-level allowlist: any Google email whose domain matches passes the gate
# (e.g. "nlma.io,fidumcompany.com" admits everyone @ those orgs). Stored without
# a leading "@". Combined with GOOGLE_ALLOWED_EMAILS via OR — either list
# matching admits the email.
_ENV_GOOGLE_ALLOWED_DOMAINS: list[str] = [
    d.strip().lower().lstrip("@")
    for d in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",")
    if d.strip()
]

# --- Org-wide authorized-domains registry (managed from status.nlma.io) -----
# allowed_domains() below resolves env domains UNION
# https://status.nlma.io/domains.json (TTL cache, last-known-good on outage,
# baked defaults on cold failure) — mirrors bright-auth / skiptrace-mcp, so
# adding a domain on the dashboard reaches vin with no redeploy. Set
# AUTHORIZED_DOMAINS_URL="" to disable the registry and run env-only.
AUTHORIZED_DOMAINS_URL: str = os.getenv(
    "AUTHORIZED_DOMAINS_URL", "https://status.nlma.io/domains.json"
)
AUTHORIZED_DOMAINS_TTL: int = int(os.getenv("AUTHORIZED_DOMAINS_TTL", "60"))
_REGISTRY_DEFAULTS = frozenset(
    {
        "aristidemanagement.com",
        "fidumcompany.com",
        "hvacfrontroyal.com",
        "mattmirus.com",
        "nlma.io",
        "propmanageplus.com",
        "tra-lawfirm.com",
        "zipadeeservices.com",
    }
)
_registry_cache: dict = {"domains": None, "exp": 0.0}


def _registry_domains() -> frozenset:
    if not AUTHORIZED_DOMAINS_URL:
        return frozenset()
    import json as _json
    import time as _time
    import urllib.request as _rq

    now = _time.time()
    if _registry_cache["domains"] is not None and _registry_cache["exp"] > now:
        return _registry_cache["domains"]
    try:
        req = _rq.Request(
            AUTHORIZED_DOMAINS_URL, headers={"Accept": "application/json"}
        )
        with _rq.urlopen(req, timeout=4) as r:
            doms = frozenset(
                str(d).strip().lower()
                for d in _json.loads(r.read().decode()).get("domains", [])
                if str(d).strip()
            )
        if doms:
            _registry_cache.update(domains=doms, exp=now + AUTHORIZED_DOMAINS_TTL)
            return doms
    except Exception:
        pass
    if _registry_cache["domains"] is not None:
        _registry_cache["exp"] = now + AUTHORIZED_DOMAINS_TTL
        return _registry_cache["domains"]
    return _REGISTRY_DEFAULTS


def allowed_domains() -> list[str]:
    """env domains UNION the live org-wide registry.

    A resolver function, deliberately not a module-level constant: tests that
    `monkeypatch.setattr(config, "GOOGLE_ALLOWED_EMAILS", [...])` should not
    have to also know about the registry union, and a plain constant computed
    at import time would go stale the moment the registry refreshes.
    """
    return sorted(set(_ENV_GOOGLE_ALLOWED_DOMAINS) | _registry_domains())


# Keep the operator-password gate working as a break-glass fallback alongside
# Google sign-in (so a Google outage cannot lock the operator out).
ALLOW_PASSWORD_FALLBACK: bool = os.getenv(
    "ALLOW_PASSWORD_FALLBACK", "true"
).lower() in ("1", "true", "yes", "on")

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")

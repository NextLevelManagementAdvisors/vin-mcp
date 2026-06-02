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
# Keep the operator-password gate working as a break-glass fallback alongside
# Google sign-in (so a Google outage cannot lock the operator out).
ALLOW_PASSWORD_FALLBACK: bool = os.getenv(
    "ALLOW_PASSWORD_FALLBACK", "true"
).lower() in ("1", "true", "yes", "on")

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")

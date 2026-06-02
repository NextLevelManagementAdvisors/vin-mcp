"""MCP Server instance for vPIC (NHTSA) VIN tools.

The `auth` parameter is attached lazily — for stdio transport (local Claude
Desktop subprocess) we don't want OAuth machinery; for HTTP transport we do.
Selection happens in src/server.py based on MCP_TRANSPORT.
"""

from fastmcp import FastMCP

from src import config
from src.auth import VinPersonalAuthProvider


def _build_auth_provider():
    """Construct the OAuth provider.

    We attach the provider whenever an operator gate is configured (an operator
    password and/or Google sign-in), regardless of MCP_TRANSPORT (which is a
    *runtime* selector, not a build-time one — the --transport CLI flag can
    override the env var). For stdio transport the provider is unused but
    harmless.
    """
    if not (config.MCP_OWNER_PASSWORD or config.GOOGLE_WEB_CLIENT_ID):
        return None
    return VinPersonalAuthProvider(
        base_url=config.MCP_BASE_URL,
        allowed_redirect_domains=config.MCP_OAUTH_REDIRECT_DOMAINS,
        state_dir=config.MCP_OAUTH_STATE_DIR,
    )


_auth = _build_auth_provider()

mcp = FastMCP(
    name="vin-mcp",
    instructions=(
        "NHTSA vPIC vehicle data. Decode 17-char VINs (flat or extended), "
        "batch-decode up to 50 VINs, list makes/models, decode WMIs, and look "
        "up vehicle types. US-market vehicles, model year 1981 and forward. "
        "Specs only — no title/accident/odometer history."
    ),
    auth=_auth,
)


# Every vPIC endpoint is read-only — there is no mutation surface on vPIC.
# Patch the @mcp.tool decorator once so every tool registration gets the
# read-only / non-destructive / idempotent annotations automatically. Clients
# (claude.ai / ChatGPT) use these hints to categorize tools in their
# permission UI.
_DEFAULT_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,  # interacts with an external service (NHTSA vPIC)
}
_original_tool = mcp.tool


def _readonly_tool(*args, **kwargs):
    kwargs.setdefault("annotations", _DEFAULT_TOOL_ANNOTATIONS)
    return _original_tool(*args, **kwargs)


mcp.tool = _readonly_tool

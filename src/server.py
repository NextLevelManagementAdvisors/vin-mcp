"""vin-mcp server entry point.

Transports:
- stdio: for local Claude Desktop / mcp-inspector. No auth.
- http:  for hosted deploy at vin.nlma.io with OAuth 2.1 (DCR + PKCE).
         A login gate at /login (Google sign-in and/or operator password) sits
         in front of /authorize so only an authorized human can complete the
         flow.

All custom HTTP behavior (/health, /login, /oauth/google/*, /authorize gate)
lives in src/login_views.py:OperatorGateMiddleware. We do NOT use
@mcp.custom_route — it interferes with OAuth route mounting.
"""

import argparse
import logging
import sys

import structlog
from starlette.middleware import Middleware

from src import config
from src.login_views import OperatorGateMiddleware
from src.mcp_server import mcp

# Importing the tool module registers @mcp.tool() decorators on `mcp`.
from src.tools import vin_tools  # noqa: F401

log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(format="%(message)s", stream=sys.stderr, level=log_level)
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)


def main() -> None:
    logger = structlog.get_logger(__name__)

    parser = argparse.ArgumentParser(description="vin-mcp (NHTSA vPIC) server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=config.MCP_TRANSPORT,
    )
    parser.add_argument("--host", default=config.MCP_HOST)
    parser.add_argument("--port", type=int, default=config.MCP_PORT)
    parser.add_argument("--log-level", default=config.LOG_LEVEL.lower())
    try:
        args, _ = parser.parse_known_args()
    except SystemExit:
        class DefaultArgs:
            transport = config.MCP_TRANSPORT
            host = config.MCP_HOST
            port = config.MCP_PORT
            log_level = config.LOG_LEVEL.lower()
        args = DefaultArgs()

    # vPIC requires no API key — nothing to validate here.

    if args.transport == "stdio":
        logger.info("Starting vin-mcp", transport="stdio")
        mcp.run(transport="stdio")
        return

    if args.transport != "http":
        logger.error("Unknown transport", transport=args.transport)
        sys.exit(2)

    if not (config.MCP_OWNER_PASSWORD or config.GOOGLE_WEB_CLIENT_ID):
        logger.error(
            "http transport needs an operator gate: set MCP_OWNER_PASSWORD "
            "and/or GOOGLE_WEB_CLIENT_ID."
        )
        sys.exit(1)

    logger.info(
        "Starting vin-mcp",
        transport="streamable-http",
        host=args.host,
        port=args.port,
        base_url=config.MCP_BASE_URL,
        google_gate=bool(config.GOOGLE_WEB_CLIENT_ID),
        password_fallback=bool(
            config.MCP_OWNER_PASSWORD and config.ALLOW_PASSWORD_FALLBACK
        ),
    )

    # OperatorGateMiddleware serves /health, /login and /oauth/google/*, and
    # gates /authorize behind a login cookie. Everything else passes through to
    # FastMCP's OAuth + MCP route handlers.
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        middleware=[Middleware(OperatorGateMiddleware)],
    )


if __name__ == "__main__":
    main()

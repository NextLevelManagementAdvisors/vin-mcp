"""Operator-password gate + /login form + /health endpoint as ASGI middleware.

We collapse three concerns into one middleware because using FastMCP's
@mcp.custom_route decorator causes the OAuth provider's routes to not be
mounted at runtime (introspection sees them but they 404 in practice).
Adding everything in a single middleware sidesteps that interaction.

Routes handled here (returned directly, never passed through):
- GET  /health  -> 200 plain text
- GET  /login   -> password form
- POST /login   -> validate password, set cookie, 303 back to return URL

Authorization gate:
- GET  /authorize without `vin_authed` cookie -> 302 to /login?return=...
- GET  /authorize with valid cookie           -> pass through to FastMCP

Everything else passes through unchanged.
"""

from __future__ import annotations

import hmac
import secrets
import time
from urllib.parse import urlencode, parse_qsl

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from src import config

COOKIE_NAME = "vin_authed"
COOKIE_MAX_AGE = 10 * 60
COOKIE_VALUE_LEN = 32

_VALID_COOKIES: dict[str, float] = {}


def _is_valid_cookie(value: str) -> bool:
    if not value:
        return False
    exp = _VALID_COOKIES.get(value)
    if exp is None:
        return False
    if exp < time.time():
        _VALID_COOKIES.pop(value, None)
        return False
    return True


def _mint_cookie() -> str:
    val = secrets.token_urlsafe(COOKIE_VALUE_LEN)
    _VALID_COOKIES[val] = time.time() + COOKIE_MAX_AGE
    return val


def _login_page(return_url: str, error: str | None = None) -> HTMLResponse:
    err_html = f'<div class="err">{error}</div>' if error else ""
    body = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>VIN MCP &mdash; operator sign-in</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:380px;margin:80px auto;padding:0 20px;color:#222}}
h1{{font-size:20px}}
label{{display:block;margin:12px 0 4px;font-size:13px;color:#555}}
input[type=password]{{width:100%;padding:10px;font-size:14px;box-sizing:border-box;border:1px solid #ccc;border-radius:4px}}
button{{padding:10px 22px;font-size:14px;margin-top:14px;cursor:pointer;border:0;background:#111;color:white;border-radius:4px;width:100%}}
.err{{background:#fef2f2;color:#b00020;padding:10px 14px;border-radius:4px;margin-bottom:12px;font-size:13px}}
.hint{{color:#666;font-size:12px;margin-top:18px;line-height:1.5}}
</style>
</head><body>
<h1>VIN MCP</h1>
<p>The MCP server is requesting authorization to connect. Enter the operator password to continue.</p>
{err_html}
<form method="post" action="/login">
  <input type="hidden" name="return" value="{return_url}">
  <label for="password">Password</label>
  <input id="password" type="password" name="password" autocomplete="current-password" autofocus>
  <button type="submit">Authorize</button>
</form>
<p class="hint">Single-operator server. If you don't know the password, this connector isn't for you.</p>
</body></html>"""
    return HTMLResponse(body, status_code=200 if error is None else 401)


def _parse_cookies(cookie_header: str) -> dict[str, str]:
    cookies = {}
    for piece in cookie_header.split(";"):
        piece = piece.strip()
        if "=" in piece:
            k, v = piece.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class OperatorGateMiddleware:
    """Single ASGI middleware that handles /health, /login, and /authorize gating."""

    def __init__(self, app):
        self.app = app

    async def _send_response(self, response, scope, receive, send):
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Parse cookies once
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")
        cookies = _parse_cookies(cookie_header)

        # --- /health ---
        if path == "/health" and method == "GET":
            await self._send_response(
                PlainTextResponse("ok\n"), scope, receive, send
            )
            return

        # --- /login GET ---
        if path == "/login" and method == "GET":
            query = scope.get("query_string", b"").decode("latin-1")
            return_url = dict(parse_qsl(query)).get("return", "/")
            await self._send_response(_login_page(return_url), scope, receive, send)
            return

        # --- /login POST ---
        if path == "/login" and method == "POST":
            request = Request(scope, receive=receive)
            form = await request.form()
            submitted = str(form.get("password", ""))
            return_url = str(form.get("return", "/")) or "/"

            expected = config.MCP_OWNER_PASSWORD
            if not expected or not hmac.compare_digest(submitted, expected):
                await self._send_response(
                    _login_page(return_url, error="Wrong password."),
                    scope, receive, send,
                )
                return

            cookie = _mint_cookie()
            resp = RedirectResponse(url=return_url, status_code=303)
            resp.set_cookie(
                COOKIE_NAME,
                cookie,
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                secure=True,
                samesite="lax",
                path="/",
            )
            await self._send_response(resp, scope, receive, send)
            return

        # --- /authorize gate ---
        if path == "/authorize":
            if _is_valid_cookie(cookies.get(COOKIE_NAME, "")):
                await self.app(scope, receive, send)
                return

            query = scope.get("query_string", b"").decode("latin-1")
            original = path + (f"?{query}" if query else "")
            redirect = f"/login?{urlencode({'return': original})}"
            await self._send_response(
                RedirectResponse(url=redirect, status_code=302),
                scope, receive, send,
            )
            return

        # --- pass through ---
        await self.app(scope, receive, send)

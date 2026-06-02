"""Operator login gate (Google sign-in + password fallback) + /health, as ASGI
middleware.

vin-mcp keeps its own OAuth 2.1 Authorization Server (see src/auth.py) for MCP
clients — Claude/ChatGPT do DCR + PKCE against this server. This middleware
only gates the *human* who authorizes a client: it proves identity before the
standard /authorize handler runs, then sets a short-lived cookie that the OAuth
handler trusts.

Two gate methods, both optional and config-driven:

1. Google sign-in (enabled when GOOGLE_WEB_CLIENT_ID/SECRET are set).
   GET  /login                 -> page with a "Sign in with Google" button
   GET  /oauth/google/start     -> 302 to Google consent (scope: openid email)
   GET  /oauth/google/callback  -> exchange code, read the verified email from
                                   userinfo, check GOOGLE_ALLOWED_EMAILS, set
                                   the cookie, 303 back to /authorize.
   Online access only (no refresh token) — vin calls no Google API.

2. Operator password (break-glass fallback; enabled when MCP_OWNER_PASSWORD is
   set and ALLOW_PASSWORD_FALLBACK is true).
   POST /login                  -> validate MCP_OWNER_PASSWORD, set cookie.

We do NOT use @mcp.custom_route — it interferes with OAuth route mounting, so
every custom route is handled here and returned directly.

Authorization gate:
- GET /authorize without a valid vin_authed cookie -> 302 to /login?return=...
- GET /authorize with a valid cookie               -> pass through to FastMCP

Everything else passes through unchanged.
"""

from __future__ import annotations

import hmac
import html
import secrets
import time
import urllib.parse
from typing import Any, Dict, Optional

import httpx
import structlog
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from src import config

logger = structlog.get_logger("vin-gate")

COOKIE_NAME = "vin_authed"
COOKIE_MAX_AGE = 10 * 60
COOKIE_VALUE_LEN = 32

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# In-memory stores. Single-process container; both are short-lived and may be
# dropped on restart (a 10-minute login cookie, a 5-minute in-flight login).
_VALID_COOKIES: dict[str, float] = {}
_GOOGLE_STATES: dict[str, dict] = {}  # state -> {"return": str, "exp": float}
_STATE_TTL = 5 * 60


# --------------------------------------------------------------------------- #
# Feature toggles
# --------------------------------------------------------------------------- #
def _google_enabled() -> bool:
    return bool(config.GOOGLE_WEB_CLIENT_ID and config.GOOGLE_WEB_CLIENT_SECRET)


def _password_enabled() -> bool:
    return bool(config.MCP_OWNER_PASSWORD and config.ALLOW_PASSWORD_FALLBACK)


# --------------------------------------------------------------------------- #
# Cookie helpers
# --------------------------------------------------------------------------- #
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


def _set_cookie(resp) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        _mint_cookie(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _parse_cookies(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for piece in cookie_header.split(";"):
        piece = piece.strip()
        if "=" in piece:
            k, v = piece.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


# --------------------------------------------------------------------------- #
# Google login state helpers
# --------------------------------------------------------------------------- #
def _prune_states() -> None:
    now = time.time()
    for k in [k for k, v in _GOOGLE_STATES.items() if v["exp"] < now]:
        _GOOGLE_STATES.pop(k, None)


def _put_state(return_url: str) -> str:
    _prune_states()
    st = secrets.token_urlsafe(24)
    _GOOGLE_STATES[st] = {"return": return_url or "/", "exp": time.time() + _STATE_TTL}
    return st


def _pop_state(st: str) -> Optional[dict]:
    row = _GOOGLE_STATES.pop(st, None)
    if not row or row["exp"] < time.time():
        return None
    return row


def _email_allowed(email: str) -> bool:
    allow = config.GOOGLE_ALLOWED_EMAILS
    # Fail closed: with no allowlist configured, nobody passes the Google gate.
    if not allow:
        return False
    return email.lower() in {a.lower() for a in allow}


def _google_consent_url(state: str) -> str:
    params = {
        "client_id": config.GOOGLE_WEB_CLIENT_ID,
        "redirect_uri": config.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def _login_page(return_url: str, error: str | None = None) -> HTMLResponse:
    safe_return = html.escape(return_url, quote=True)
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""

    google_html = ""
    if _google_enabled():
        start = "/oauth/google/start?" + urllib.parse.urlencode({"return": return_url})
        google_html = (
            f'<a class="gbtn" href="{html.escape(start, quote=True)}">'
            f'<span class="g">G</span> Sign in with Google</a>'
        )

    pw_html = ""
    if _password_enabled():
        sep = '<div class="sep">or</div>' if google_html else ""
        pw_html = (
            f"{sep}"
            f'<form method="post" action="/login">'
            f'<input type="hidden" name="return" value="{safe_return}">'
            f'<label for="password">Operator password</label>'
            f'<input id="password" type="password" name="password" '
            f'autocomplete="current-password">'
            f'<button type="submit">Authorize</button>'
            f"</form>"
        )

    body = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>VIN MCP &mdash; sign in</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:380px;margin:80px auto;padding:0 20px;color:#222}}
h1{{font-size:20px}}
label{{display:block;margin:12px 0 4px;font-size:13px;color:#555}}
input[type=password]{{width:100%;padding:10px;font-size:14px;box-sizing:border-box;border:1px solid #ccc;border-radius:4px}}
button{{padding:10px 22px;font-size:14px;margin-top:14px;cursor:pointer;border:0;background:#111;color:#fff;border-radius:4px;width:100%}}
.gbtn{{display:flex;align-items:center;justify-content:center;gap:10px;padding:11px;border:1px solid #ccc;border-radius:4px;text-decoration:none;color:#222;font-size:14px;font-weight:500}}
.gbtn .g{{display:inline-flex;width:20px;height:20px;align-items:center;justify-content:center;border-radius:50%;background:#4285F4;color:#fff;font-weight:700;font-size:13px}}
.sep{{text-align:center;color:#999;font-size:12px;margin:16px 0}}
.err{{background:#fef2f2;color:#b00020;padding:10px 14px;border-radius:4px;margin-bottom:12px;font-size:13px}}
.hint{{color:#666;font-size:12px;margin-top:18px;line-height:1.5}}
</style>
</head><body>
<h1>VIN MCP</h1>
<p>A client is requesting authorization to connect. Sign in to continue.</p>
{err_html}
{google_html}
{pw_html}
<p class="hint">Single-operator server. Access is limited to authorized accounts.</p>
</body></html>"""
    return HTMLResponse(body, status_code=200 if error is None else 401)


def _denied_page(email: str) -> HTMLResponse:
    safe = html.escape(email)
    body = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Not authorized</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;padding:0 20px;color:#222}}
.err{{background:#fef2f2;color:#b00020;padding:12px 16px;border-radius:6px;font-size:14px}}
a{{color:#111}}
</style>
</head><body>
<h1>Not authorized</h1>
<div class="err">The Google account <b>{safe}</b> is not on the allow list for this server.</div>
<p><a href="/login">Try a different account</a></p>
</body></html>"""
    return HTMLResponse(body, status_code=403)


# --------------------------------------------------------------------------- #
# Google HTTP helpers
# --------------------------------------------------------------------------- #
async def _post_form(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, data=data)
        r.raise_for_status()
        return r.json()


async def _get_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #
class OperatorGateMiddleware:
    """ASGI middleware: /health, /login, /oauth/google/*, and the /authorize gate."""

    def __init__(self, app):
        self.app = app

    async def _send(self, response, scope, receive, send):
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")
        cookies = _parse_cookies(cookie_header)

        # --- /health ---
        if path == "/health" and method == "GET":
            await self._send(PlainTextResponse("ok\n"), scope, receive, send)
            return

        # --- /login GET ---
        if path == "/login" and method == "GET":
            query = scope.get("query_string", b"").decode("latin-1")
            return_url = dict(urllib.parse.parse_qsl(query)).get("return", "/")
            await self._send(_login_page(return_url), scope, receive, send)
            return

        # --- /login POST (password fallback) ---
        if path == "/login" and method == "POST":
            request = Request(scope, receive=receive)
            form = await request.form()
            submitted = str(form.get("password", ""))
            return_url = str(form.get("return", "/")) or "/"

            if not _password_enabled():
                await self._send(
                    _login_page(return_url, error="Password sign-in is disabled."),
                    scope, receive, send,
                )
                return

            expected = config.MCP_OWNER_PASSWORD
            if not expected or not hmac.compare_digest(submitted, expected):
                await self._send(
                    _login_page(return_url, error="Wrong password."),
                    scope, receive, send,
                )
                return

            resp = RedirectResponse(url=return_url, status_code=303)
            _set_cookie(resp)
            await self._send(resp, scope, receive, send)
            return

        # --- /oauth/google/start ---
        if path == "/oauth/google/start" and method == "GET":
            if not _google_enabled():
                await self._send(
                    PlainTextResponse("google sign-in not configured", status_code=404),
                    scope, receive, send,
                )
                return
            query = scope.get("query_string", b"").decode("latin-1")
            return_url = dict(urllib.parse.parse_qsl(query)).get("return", "/")
            state = _put_state(return_url)
            await self._send(
                RedirectResponse(url=_google_consent_url(state), status_code=302),
                scope, receive, send,
            )
            return

        # --- /oauth/google/callback ---
        if path == "/oauth/google/callback" and method == "GET":
            await self._handle_google_callback(scope, receive, send)
            return

        # --- /authorize gate ---
        if path == "/authorize":
            if _is_valid_cookie(cookies.get(COOKIE_NAME, "")):
                await self.app(scope, receive, send)
                return
            query = scope.get("query_string", b"").decode("latin-1")
            original = path + (f"?{query}" if query else "")
            redirect = f"/login?{urllib.parse.urlencode({'return': original})}"
            await self._send(
                RedirectResponse(url=redirect, status_code=302),
                scope, receive, send,
            )
            return

        # --- pass through ---
        await self.app(scope, receive, send)

    async def _handle_google_callback(self, scope, receive, send):
        request = Request(scope, receive=receive)
        qp = request.query_params
        err = qp.get("error")
        state = qp.get("state")
        code = qp.get("code")

        if not state:
            await self._send(
                PlainTextResponse("missing state", status_code=400),
                scope, receive, send,
            )
            return
        row = _pop_state(state)
        if not row:
            await self._send(
                PlainTextResponse("state not found or expired", status_code=400),
                scope, receive, send,
            )
            return
        return_url = row["return"]

        if err:
            await self._send(
                _login_page(return_url, error=f"Google sign-in failed: {err}"),
                scope, receive, send,
            )
            return
        if not code:
            await self._send(
                _login_page(return_url, error="Google sign-in returned no code."),
                scope, receive, send,
            )
            return

        # 1. Exchange the Google authorization code for tokens.
        try:
            token = await _post_form(
                GOOGLE_TOKEN_URL,
                {
                    "code": code,
                    "client_id": config.GOOGLE_WEB_CLIENT_ID,
                    "client_secret": config.GOOGLE_WEB_CLIENT_SECRET,
                    "redirect_uri": config.GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("google token exchange failed", error=str(e))
            await self._send(
                _login_page(return_url, error="Google token exchange failed."),
                scope, receive, send,
            )
            return

        access_token = token.get("access_token")
        if not access_token:
            await self._send(
                _login_page(return_url, error="Google did not return an access token."),
                scope, receive, send,
            )
            return

        # 2. Read the verified email from userinfo.
        try:
            info = await _get_json(
                GOOGLE_USERINFO_URL,
                {"Authorization": f"Bearer {access_token}"},
            )
        except Exception as e:  # noqa: BLE001
            logger.error("google userinfo failed", error=str(e))
            await self._send(
                _login_page(return_url, error="Could not read your Google profile."),
                scope, receive, send,
            )
            return

        email = (info.get("email") or "").strip()
        verified = info.get("email_verified")
        if not email or not verified:
            await self._send(
                _login_page(return_url, error="Google account has no verified email."),
                scope, receive, send,
            )
            return

        # 3. Allowlist check (fail closed).
        if not _email_allowed(email):
            logger.warning("google login denied", email=email)
            await self._send(_denied_page(email), scope, receive, send)
            return

        # 4. Authorized: set the gate cookie and bounce back to /authorize.
        logger.info("google login ok", email=email)
        resp = RedirectResponse(url=return_url or "/", status_code=303)
        _set_cookie(resp)
        await self._send(resp, scope, receive, send)

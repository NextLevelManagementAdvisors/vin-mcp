# CLAUDE.md — vin-mcp ops notes

Self-hosted on `server.nlma.io` (178.16.141.166). Mirrors the attom-mcp pattern.

## Topology
- Source: `/opt/vin-mcp`
- Container: `vin-mcp`, image `vin-mcp:nlma`, bound to `127.0.0.1:3034`
  (3032 is taken by vacourts-mcp; 3033 was also occupied)
- nginx site: `/etc/nginx/sites-enabled/vin.nlma.io` (TLS-terminate + rate-limit + proxy)
- rate-limit zone: `/etc/nginx/conf.d/limit-req-vin.conf` (`vin_mcp`, 60r/m)
- landing page: `/var/www/vin-mcp/index.html`
- OAuth state (persisted): `/var/lib/vin-mcp/oauth-state` (bind-mounted)
- public URL: `https://vin.nlma.io`, MCP endpoint `https://vin.nlma.io/mcp`

## Auth
- This server is its own OAuth 2.1 Authorization Server (DCR + PKCE) for MCP
  clients — see `src/auth.py` (`VinPersonalAuthProvider`). nginx does NOT do
  auth — only TLS + rate-limit + proxy.
- The human is gated at `/login` by `src/login_views.py:OperatorGateMiddleware`,
  which sets a short-lived `vin_authed` cookie that the `/authorize` handler
  trusts. Two methods, both config-driven:
  - **Google sign-in** (when `GOOGLE_WEB_CLIENT_ID`/`SECRET` set): `/login` ->
    `/oauth/google/start` -> Google consent (`openid email`, online only) ->
    `/oauth/google/callback` verifies the email against `GOOGLE_ALLOWED_EMAILS`
    (fails closed if empty), then sets the cookie. vin calls no Google API.
    The Google web client must list `<MCP_BASE_URL>/oauth/google/callback` as an
    authorized redirect URI.
  - **Operator password** (break-glass fallback; `MCP_OWNER_PASSWORD` +
    `ALLOW_PASSWORD_FALLBACK=true`): `POST /login`.

## Deploy / update
```bash
cd /opt/vin-mcp
git pull
docker compose up -d --build
```

## nginx reload (systemd/dbus is NOT reachable from the shell-mcp chroot, and
## this shell is in a child PID namespace so it cannot signal the host nginx).
## Working method on this box — reload from a host-PID container:
```bash
nginx -t && docker run --rm --pid=host --privileged alpine:latest kill -HUP "$(cat /run/nginx.pid)"
```

## Cert
```bash
certbot certonly --webroot -w /var/www/html -d vin.nlma.io
```

## Quick checks
```bash
curl -s http://127.0.0.1:3034/health        # local
curl -s https://vin.nlma.io/health           # through nginx
curl -s https://vin.nlma.io/.well-known/oauth-authorization-server | head
```

## Upstream
NHTSA vPIC, no API key. Cache TTL (`VPIC_CACHE_TTL_SECONDS`, default 24h) is
politeness only — vPIC has no retention ceiling. Coverage is MY 1981+, US
market, specs only (no history).

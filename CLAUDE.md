# CLAUDE.md — vin-mcp ops notes

Self-hosted on `server.nlma.io` (178.16.141.166). Mirrors the attom-mcp pattern.

## Topology
- Source: `/opt/vin-mcp`
- Container: `vin-mcp`, image `vin-mcp:nlma`, bound to `127.0.0.1:3032`
- nginx site: `/etc/nginx/sites-enabled/vin.nlma.io` (TLS-terminate + rate-limit + proxy)
- rate-limit zone: `/etc/nginx/conf.d/limit-req-vin.conf` (`vin_mcp`, 60r/m)
- landing page: `/var/www/vin-mcp/index.html`
- OAuth state (persisted): `/var/lib/vin-mcp/oauth-state` (bind-mounted)
- public URL: `https://vin.nlma.io`, MCP endpoint `https://vin.nlma.io/mcp`

## Auth
- OAuth 2.1 (DCR + PKCE) handled in Python (`src/auth.py`).
- `/login` operator-password gate in `src/login_views.py`; password = `MCP_OWNER_PASSWORD`.
- nginx does NOT do auth — only TLS + rate-limit + proxy.

## Deploy / update
```bash
cd /opt/vin-mcp
git pull
docker compose up -d --build
```

## nginx reload (systemd/dbus is not reachable from the shell-mcp chroot)
```bash
nginx -t && nginx -s reload     # or: kill -HUP $(cat /run/nginx.pid)
```

## Cert
```bash
certbot certonly --webroot -w /var/www/html -d vin.nlma.io
```

## Quick checks
```bash
curl -s http://127.0.0.1:3032/health        # local
curl -s https://vin.nlma.io/health           # through nginx
curl -s https://vin.nlma.io/.well-known/oauth-authorization-server | head
```

## Upstream
NHTSA vPIC, no API key. Cache TTL (`VPIC_CACHE_TTL_SECONDS`, default 24h) is
politeness only — vPIC has no retention ceiling. Coverage is MY 1981+, US
market, specs only (no history).

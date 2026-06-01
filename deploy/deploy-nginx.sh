#!/usr/bin/env bash
# Deploy the vin.nlma.io nginx vhost + rate-limit conf from this repo to the VPS.
#
# Guards the three failure modes from issue #1
# (https://github.com/NextLevelManagementAdvisors/vin-mcp/issues/1):
#   1. Host-port reuse: refuse to install if another enabled vhost already
#      proxies to the loopback port(s) this vhost wants. vacourts-mcp (host
#      networking) owns 127.0.0.1:3032, so vin must not point there.
#   2. Stray backups: config backups are written OUTSIDE sites-enabled/, because
#      nginx globs sites-enabled/* and a .bak there becomes a duplicate server.
#   3. Missing /run/nginx.pid: prefer `systemctl reload`; if unavailable, rebuild
#      the pidfile from the running master before `nginx -s reload`, else HUP it.
#
# Run on the VPS as root:   sudo ./deploy/deploy-nginx.sh
# Or from a workstation:    ssh root@178.16.141.166 'cd /opt/vin-mcp && ./deploy/deploy-nginx.sh'
set -euo pipefail

cd "$(dirname "$0")/.."

SITE="${SITE:-vin.nlma.io}"
ENABLED="/etc/nginx/sites-enabled/${SITE}"
RATECONF_SRC="deploy/limit-req-vin.conf"
RATECONF_DST="/etc/nginx/conf.d/limit-req-vin.conf"
BACKDIR="/root/nginx-backups"
VHOST_SRC="deploy/${SITE}.nginx"

[ -f "$VHOST_SRC" ] || { echo "ERROR: $VHOST_SRC not found (run from repo root)"; exit 1; }
mkdir -p "$BACKDIR"

# 1) Port-lint: every loopback port this vhost proxies to must be unused by any
#    OTHER enabled vhost.
ports="$(grep -oE '127\.0\.0\.1:[0-9]+' "$VHOST_SRC" | grep -oE '[0-9]+$' | sort -u)"
for p in $ports; do
  clash="$(grep -rlE "127\.0\.0\.1:${p}([^0-9]|$)" /etc/nginx/sites-enabled/ 2>/dev/null \
            | grep -v "/${SITE}\$" || true)"
  if [ -n "$clash" ]; then
    echo "ABORT: 127.0.0.1:${p} is already proxied by another vhost:"
    echo "$clash" | sed 's/^/  /'
    echo "Pick a free port (compare against: grep -rho '127.0.0.1:[0-9]*' /etc/nginx/sites-enabled/)."
    exit 1
  fi
done

# 2) Install (back up the live copies off-tree first).
ts="$(date +%Y%m%d-%H%M%S)"
[ -f "$ENABLED" ]      && cp -a "$ENABLED"      "${BACKDIR}/${SITE}.${ts}.bak"
[ -f "$RATECONF_DST" ] && cp -a "$RATECONF_DST" "${BACKDIR}/limit-req-vin.conf.${ts}.bak"
cp "$VHOST_SRC"     "$ENABLED"
cp "$RATECONF_SRC"  "$RATECONF_DST"
echo "installed ${SITE} vhost + rate-limit conf"

# 3) Validate, then reload nginx (pidfile-safe).
nginx -t
if command -v systemctl >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null; then
  echo "reloaded nginx via systemctl"
else
  pid="$(cat /run/nginx.pid 2>/dev/null || true)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    pid="$(pgrep -o -x nginx || true)"
    [ -n "$pid" ] && { echo "$pid" > /run/nginx.pid; echo "rebuilt /run/nginx.pid -> $pid"; }
  fi
  if [ -n "$pid" ]; then
    nginx -s reload 2>/dev/null || kill -HUP "$pid"
    echo "reloaded nginx via signal (pid $pid)"
  else
    echo "ERROR: nginx master not found; is nginx running?"; exit 1
  fi
fi

echo "OK: deployed ${SITE}"

#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:8765"
SERVICE="gui/$(/usr/bin/id -u)/com.stockultimus.local-console"

if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
  /usr/bin/open "$URL/console"
  exit 0
fi

# Prefer and repair the permanent background service.  Never start a second
# Terminal server: two owners of port 8765 make launchd loop indefinitely.
/usr/bin/launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 || true
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
    /usr/bin/open "$URL/console"
    exit 0
  fi
  /bin/sleep 1
done

cd "$ROOT"
/usr/bin/python3 "$ROOT/scripts/install_stock_ultimus_console_launchd.py" --install --replace-listener
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
    /usr/bin/open "$URL/console"
    exit 0
  fi
  /bin/sleep 1
done

echo "Stock Ultimus: el servicio permanente no pudo iniciar. Revisa /private/tmp/com.stockultimus.local-console.err"
exit 1

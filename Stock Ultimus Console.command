#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:8765"
SERVICE="gui/$(/usr/bin/id -u)/com.stockultimus.local-console"

if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
  /usr/bin/open "$URL/console"
  exit 0
fi

# Prefer the permanent background service. The direct Terminal server below is
# retained only as a recovery path when the service has not yet been installed.
/usr/bin/launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 || true
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
    /usr/bin/open "$URL/console"
    exit 0
  fi
  /bin/sleep 1
done

cd "$ROOT"
(sleep 1; /usr/bin/open "$URL/console") &
exec /usr/bin/python3 "$ROOT/scripts/ibkr_account_profile.py" serve --host 127.0.0.1 --port 8765

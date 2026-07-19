#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:8765"

if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null; then
  /usr/bin/open "$URL/console"
  exit 0
fi

cd "$ROOT"
(sleep 1; /usr/bin/open "$URL/console") &
exec /usr/bin/python3 "$ROOT/scripts/ibkr_account_profile.py" serve --host 127.0.0.1 --port 8765

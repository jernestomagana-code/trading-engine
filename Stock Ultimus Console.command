#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:8765"

cd "$ROOT"
(sleep 1; open "$URL") &
exec /usr/bin/python3 "$ROOT/scripts/ibkr_account_profile.py" serve --host 127.0.0.1 --port 8765

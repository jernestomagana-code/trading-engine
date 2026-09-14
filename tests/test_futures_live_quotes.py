from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import re
import shutil
import subprocess
import unittest

import futures_live_quotes as quotes


class LiveQuotesTests(unittest.TestCase):
    def test_continuous_requires_explicit_matching_contract(self):
        self.assertIsNone(quotes.contract_identity({"ticker": "MNQ1!"}))
        for contract in ("CME_MINI:MESU2026", "BLACKBULL:MNQU2026", "MNQU6"):
            self.assertIsNone(quotes.contract_identity({"ticker": "MNQ1!", "current_contract": contract}))
        identity = quotes.contract_identity({"ticker": "MNQ1!", "raw_payload": {"current_contract": "CME_MINI:MNQU2026"}})
        self.assertEqual(identity["month"], "202609")
        self.assertEqual(identity["ticker"], "MNQ1!")

    def test_delayed_frozen_and_bad_markets_never_become_live(self):
        identity = quotes.contract_identity({"ticker": "MESU2026"})
        for kind in (2, 3, 4):
            self.assertNotEqual(quotes.normalized_quote(identity, SimpleNamespace(marketDataType=kind), 100, 101, "now")["quote_status"], "LIVE")
        for bid, ask in [(102, 101), (float("nan"), 101), (0, 101)]:
            self.assertNotEqual(quotes.normalized_quote(identity, SimpleNamespace(marketDataType=1), bid, ask, "now")["quote_status"], "LIVE")

    def test_cache_selects_executable_side_and_preserves_source(self):
        now = datetime.now(timezone.utc).isoformat()
        event = {"ticker": "MNQ1!", "current_contract": "MNQU2026", "state": "ENTRY_READY", "received_at": now, "direction": "LONG"}
        result = {"quote_status": "LIVE", "bid": 100, "ask": 101, "quote_symbol": "MNQ1!", "quote_timestamp": now}
        with patch.dict(quotes._cache, {"MNQ1!|MNQU2026": (quotes.time.monotonic(), result)}, clear=True):
            self.assertEqual(quotes.enrich_event(event)["current_price"], 101)
            self.assertEqual(quotes.enrich_event({**event, "direction": "SHORT"})["current_price"], 100)
        self.assertNotIn("current_price", event)

    @unittest.skipUnless(shutil.which("node"), "Node required to check browser syntax")
    def test_console_main_javascript_parses(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/ibkr_account_profile.py").read_text()
        scripts = [(Path(__file__).resolve().parents[1] / "scripts/console_ui.js").read_text()]
        self.assertTrue(scripts)
        for script in scripts:
            if "const views =" not in script:
                continue
            result = subprocess.run([shutil.which("node"), "--check"], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

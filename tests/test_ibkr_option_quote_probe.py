import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "ibkr_option_quote_probe.py"


def load_probe_helpers():
    tree = ast.parse(PROBE.read_text(), filename=str(PROBE))
    wanted = {
        "parse_ibkr_expiration",
        "days_to_expiration",
        "choose_expiration",
        "choose_strike",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    future = ast.parse("from __future__ import annotations\n").body
    module = ast.Module(body=future + nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"datetime": datetime, "timezone": timezone}
    exec(compile(module, str(PROBE), "exec"), namespace)
    return namespace


class IbkrOptionQuoteProbeTests(unittest.TestCase):
    def test_probe_is_readonly_and_never_places_orders(self):
        source = PROBE.read_text()
        tree = ast.parse(source, filename=str(PROBE))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_from_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        self.assertIn("readonly=True", source)
        self.assertIn("execution_authorized", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("--json-out", source)
        self.assertIn('genericTickList="" if snapshot else "100,101,106"', source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn("whatIfOrder", source)
        self.assertNotIn("ibkr_bridge", imported_modules)
        self.assertNotIn("ibkr_bridge", imported_from_modules)

    def test_probe_has_main_guard_and_no_top_level_connection(self):
        tree = ast.parse(PROBE.read_text(), filename=str(PROBE))

        top_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        ]
        self.assertEqual(top_level_calls, [])

        main_guard = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in tree.body
        )
        self.assertTrue(main_guard)

    def test_choose_strike_selects_otm_put_or_call(self):
        helpers = load_probe_helpers()
        strikes = [650.0, 665.0, 670.0, 750.0, 815.0, 820.0]

        put = helpers["choose_strike"](strikes, 746.94, "P", 0.10)
        call = helpers["choose_strike"](strikes, 746.94, "C", 0.10)

        self.assertEqual(put, 670.0)
        self.assertEqual(call, 820.0)

    def test_choose_expiration_prefers_target_dte(self):
        helpers = load_probe_helpers()

        def fake_dte(value):
            return {"20260717": 28, "20260731": 42, "20260821": 63}.get(value)

        helpers["days_to_expiration"] = fake_dte

        self.assertEqual(
            helpers["choose_expiration"](["20260717", "20260731", "20260821"], 45),
            "20260731",
        )


if __name__ == "__main__":
    unittest.main()

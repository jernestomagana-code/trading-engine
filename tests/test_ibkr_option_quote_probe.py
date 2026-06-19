import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "ibkr_option_quote_probe.py"


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
        self.assertIn("not_order_instruction", source)
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


if __name__ == "__main__":
    unittest.main()

import ast
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ibkr_bridge.py"


def load_quote_helpers():
    tree = ast.parse(BRIDGE.read_text(), filename=str(BRIDGE))
    wanted = {
        "clean",
        "safe_round",
        "calculate_spread_pct",
        "data_quality_for_option",
        "normalize_option_quote_fields",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"math": math}
    exec(compile(module, str(BRIDGE), "exec"), namespace)
    return namespace


class IbkrOptionQuoteNormalizationTests(unittest.TestCase):
    def test_full_bidask_quote_computes_v30_execution_fields(self):
        helpers = load_quote_helpers()

        quote = helpers["normalize_option_quote_fields"](
            bid=1.20,
            ask=1.35,
            last=None,
            close=None,
            market_price=None,
            greeks={"delta": -0.2, "iv": 0.25},
        )

        self.assertEqual(quote["bid"], 1.2)
        self.assertEqual(quote["ask"], 1.35)
        self.assertEqual(quote["mid"], 1.275)
        self.assertEqual(quote["spread"], 0.15)
        self.assertEqual(quote["spread_pct"], 11.76)
        self.assertEqual(quote["data_quality"], "FULL_WITH_GREEKS")

    def test_ibkr_placeholder_values_do_not_create_executable_bidask(self):
        helpers = load_quote_helpers()

        quote = helpers["normalize_option_quote_fields"](
            bid=-1,
            ask=float("nan"),
            last=0.32,
            close=None,
            market_price=None,
            greeks={"delta": -0.064, "iv": 0.2404},
        )

        self.assertIsNone(quote["bid"])
        self.assertIsNone(quote["ask"])
        self.assertEqual(quote["mid"], 0.32)
        self.assertIsNone(quote["spread"])
        self.assertIsNone(quote["spread_pct"])
        self.assertEqual(quote["data_quality"], "PRICE_WITH_GREEKS_NO_BIDASK")

    def test_inverted_bidask_never_produces_spread_or_full_quality(self):
        helpers = load_quote_helpers()

        quote = helpers["normalize_option_quote_fields"](
            bid=1.40,
            ask=1.20,
            last=1.25,
            close=None,
            market_price=None,
            greeks={"delta": -0.2, "iv": 0.25},
        )

        self.assertEqual(quote["bid"], 1.4)
        self.assertEqual(quote["ask"], 1.2)
        self.assertEqual(quote["mid"], 1.25)
        self.assertIsNone(quote["spread"])
        self.assertIsNone(quote["spread_pct"])
        self.assertEqual(quote["data_quality"], "PRICE_WITH_GREEKS_NO_BIDASK")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from tools import record_v31_manual_review as cli


def _args(**overrides):
    parser = cli.build_parser()
    args = parser.parse_args([])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class V31ManualReviewCliTests(unittest.TestCase):
    def test_default_keychain_service_matches_production_read_token(self):
        args = _args()

        self.assertEqual(args.read_token_service, "stock-ultimus-read-access")

    def test_dry_run_record_does_not_read_token_or_send_request(self):
        args = _args(ticker="spy", status="REVIEWING", reason="Validating chart.", dry_run=True)

        with patch.object(cli, "read_token") as read_token:
            with patch.object(cli, "request_json") as request_json:
                result = cli.run(args)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["method"], "POST")
        self.assertIn("/v31_manual_review", result["url"])
        self.assertEqual(result["payload"]["ticker"], "SPY")
        self.assertEqual(result["payload"]["status"], "REVIEWING")
        self.assertFalse(result["token_read"])
        self.assertFalse(result["request_sent"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        read_token.assert_not_called()
        request_json.assert_not_called()

    def test_record_posts_manual_review_without_returning_token(self):
        args = _args(
            base_url="https://example.test",
            token="secret-token",
            ticker="QQQ",
            status="WATCHLIST",
            reason="Good setup, waiting for cleaner spread.",
        )

        with patch.object(cli, "request_json", return_value=(200, {"status": "RECORDED"})) as request_json:
            result = cli.run(args)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertFalse(result["token_printed"])
        self.assertNotIn("secret-token", str(result))
        called = request_json.call_args
        self.assertEqual(called.args[0], "https://example.test/v31_manual_review")
        self.assertEqual(called.kwargs["token"], "secret-token")
        self.assertEqual(called.kwargs["method"], "POST")
        self.assertEqual(called.kwargs["payload"]["ticker"], "QQQ")
        self.assertEqual(called.kwargs["payload"]["status"], "WATCHLIST")
        self.assertFalse(called.kwargs["payload"]["execution_authorized"])
        self.assertTrue(called.kwargs["payload"]["not_order_instruction"])

    def test_list_uses_manual_reviews_endpoint(self):
        args = _args(base_url="https://example.test/", token="secret-token", list=True, limit=7)

        with patch.object(cli, "request_json", return_value=(200, {"review_count": 2})) as request_json:
            result = cli.run(args)

        self.assertTrue(result["ok"])
        self.assertEqual(result["operation"], "list")
        self.assertFalse(result["token_printed"])
        self.assertNotIn("secret-token", str(result))
        called = request_json.call_args
        self.assertEqual(called.args[0], "https://example.test/v31_manual_reviews?limit=7")
        self.assertEqual(called.kwargs["token"], "secret-token")

    def test_ticker_required_for_record(self):
        args = _args(status="REJECTED")

        with self.assertRaises(ValueError) as ctx:
            cli.run(args)

        self.assertIn("ticker is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

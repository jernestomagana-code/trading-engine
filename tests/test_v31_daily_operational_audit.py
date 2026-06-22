import json
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import v31_daily_operational_audit as audit


def args(**overrides):
    values = {
        "base_url": "https://example.test",
        "token": "read-token-secret",
        "read_token_service": "stock-ultimus-read-access",
        "keychain_account": "user",
        "timeout": 1,
        "limit": 10,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def ok_payload_for_url(url):
    if url.endswith("/health"):
        return 200, {"status": "ok", "operating_mode": "ANALYSIS_ONLY"}
    if url.endswith("/v31_system_status"):
        return 200, {
            "engine": "V31_SYSTEM_STATUS",
            "not_order_instruction": True,
            "can_operate": False,
            "summary": {"can_operate": 1},
            "decisions": [{"ticker": "SPY", "can_operate": False, "not_order_instruction": True}],
        }
    if "/v31_production_readiness" in url:
        return 200, {
            "status": "READY",
            "blockers": [],
            "not_order_instruction": True,
            "outcome_tracking": {"not_order_instruction": True},
        }
    if "/v31_data_pipeline_status" in url:
        return 200, {
            "engine": "V31_DATA_PIPELINE_STATUS",
            "status": "NO_MASTER_SNAPSHOT",
            "rows_found": 0,
            "master_snapshot_available": False,
            "freshness": {"status": "MISSING", "not_order_instruction": True},
            "not_order_instruction": True,
        }
    if "/v31_trading_day_readiness" in url:
        return 200, {
            "engine": "V31_TRADING_DAY_READINESS",
            "status": "WAIT_PIPELINE",
            "blockers": [],
            "warnings": ["PIPELINE_NOT_READY", "SNAPSHOT_MISSING"],
            "freshness": {"status": "MISSING", "not_order_instruction": True},
            "not_order_instruction": True,
            "execution_authorized": False,
        }
    if "/v31_monitor_notify/preview" in url:
        return 200, {
            "engine": "V31_PIPELINE_MONITOR_EMAIL",
            "status": "preview",
            "email_sent": False,
            "not_order_instruction": True,
            "monitor": {"not_order_instruction": True},
        }
    if "/v31_manual_reviews" in url:
        return 200, {
            "engine": "V31_MANUAL_REVIEW_JOURNAL",
            "review_count": 1,
            "recent_reviews": [{"review_id": "MR-1", "not_order_instruction": True, "execution_authorized": False}],
            "not_order_instruction": True,
            "execution_authorized": False,
        }
    if "/v31_manual_review_learning_notify/preview" in url:
        return 200, {
            "engine": "V31_WEEKLY_LEARNING_EMAIL",
            "status": "preview",
            "email_sent": False,
            "not_order_instruction": True,
            "execution_authorized": False,
            "learning": {"not_order_instruction": True, "execution_authorized": False},
        }
    if "/v31_manual_review_learning" in url:
        return 200, {
            "engine": "V31_MANUAL_REVIEW_LEARNING",
            "review_count": 1,
            "evaluated_count": 1,
            "needs_more_data": True,
            "not_order_instruction": True,
            "execution_authorized": False,
            "best_reviews": [{"not_order_instruction": True, "execution_authorized": False}],
        }
    if "/v31_evaluate_manual_reviews" in url:
        return 200, {
            "engine": "V31_MANUAL_REVIEW_AUTO_EVALUATION",
            "status": "DRY_RUN",
            "evaluated_count": 0,
            "not_order_instruction": True,
            "execution_authorized": False,
        }
    raise AssertionError(f"unexpected URL {url}")


class DailyOperationalAuditTests(unittest.TestCase):
    def test_dry_run_does_not_read_token_or_call_production(self):
        with patch.object(audit, "resolve_read_token") as token, patch.object(audit, "request_json") as request_json:
            result = audit.run_audit(args(dry_run=True, token=""))

        token.assert_not_called()
        request_json.assert_not_called()
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse(result["uses_ingest_token"])
        self.assertFalse(result["sends_email"])
        self.assertFalse(result["touches_ibkr"])
        self.assertTrue(result["not_order_instruction"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["planned_checks"])

    def test_passes_with_warning_when_pipeline_has_no_snapshot(self):
        def fake_request(method, url, **kwargs):
            if url.endswith("/v31_system_status") and not kwargs.get("token"):
                return False, 401, {"detail": "read auth required"}
            code, payload = ok_payload_for_url(url)
            return True, code, payload

        with patch.object(audit, "request_json", side_effect=fake_request):
            result = audit.run_audit(args())

        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["summary"]["warnings"], 2)
        self.assertEqual(result["pipeline"]["status"], "NO_MASTER_SNAPSHOT")
        self.assertEqual(result["trading_day_readiness"]["status"], "WAIT_PIPELINE")
        self.assertNotIn("read-token-secret", json.dumps(result))

    def test_fails_when_nested_execution_guardrail_breaks(self):
        def fake_request(method, url, **kwargs):
            if url.endswith("/v31_system_status") and not kwargs.get("token"):
                return False, 401, {"detail": "read auth required"}
            code, payload = ok_payload_for_url(url)
            if "/v31_manual_review_learning" in url and "/notify" not in url:
                payload = {
                    **payload,
                    "worst_reviews": [{"execution_authorized": True, "not_order_instruction": True}],
                }
            return True, code, payload

        with patch.object(audit, "request_json", side_effect=fake_request):
            result = audit.run_audit(args())

        self.assertEqual(result["status"], "FAIL")
        failed_names = {item["name"] for item in result["checks"] if not item["ok"]}
        self.assertIn("manual_review_learning_guardrails", failed_names)

    def test_fails_when_nested_can_operate_boolean_true_breaks(self):
        def fake_request(method, url, **kwargs):
            if url.endswith("/v31_system_status") and not kwargs.get("token"):
                return False, 401, {"detail": "read auth required"}
            code, payload = ok_payload_for_url(url)
            if url.endswith("/v31_system_status"):
                payload = {
                    **payload,
                    "decisions": [{"ticker": "SPY", "can_operate": True, "not_order_instruction": True}],
                }
            return True, code, payload

        with patch.object(audit, "request_json", side_effect=fake_request):
            result = audit.run_audit(args())

        self.assertEqual(result["status"], "FAIL")
        failed_names = {item["name"] for item in result["checks"] if not item["ok"]}
        self.assertIn("system_status_guardrails", failed_names)

    def test_fails_when_trading_day_readiness_requires_action(self):
        def fake_request(method, url, **kwargs):
            if url.endswith("/v31_system_status") and not kwargs.get("token"):
                return False, 401, {"detail": "read auth required"}
            code, payload = ok_payload_for_url(url)
            if "/v31_trading_day_readiness" in url:
                payload = {
                    **payload,
                    "status": "ACTION_REQUIRED",
                    "blockers": ["STALE_SNAPSHOT"],
                    "freshness": {"status": "STALE", "not_order_instruction": True},
                }
            return True, code, payload

        with patch.object(audit, "request_json", side_effect=fake_request):
            result = audit.run_audit(args())

        self.assertEqual(result["status"], "FAIL")
        failed_names = {item["name"] for item in result["checks"] if not item["ok"]}
        self.assertIn("trading_day_readiness_not_action_required", failed_names)

    def test_missing_token_fails_without_printing_secret_fields(self):
        with patch.object(audit, "resolve_read_token", return_value=""):
            result = audit.run_audit(args(token=""))

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["secrets_printed"])
        self.assertFalse(result["uses_ingest_token"])


if __name__ == "__main__":
    unittest.main()

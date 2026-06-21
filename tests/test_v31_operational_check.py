import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import v31_operational_check as check


DAILY_OK = {"status": "OK", "not_order_instruction": True}
STRATEGY_PERFORMANCE_OK = {
    "engine": "V32_STRATEGY_PERFORMANCE",
    "strategy_performance_version": "strategy_performance_v1",
    "summary": {"strategy_count": 6},
    "not_order_instruction": True,
    "execution_authorized": False,
}


class V31OperationalCheckTests(unittest.TestCase):
    def test_pipeline_ready_for_open_data_requires_ok_and_min_rows(self):
        self.assertTrue(check.pipeline_ready_for_open_data({"status": "OK", "rows_found": 2}, 1))
        self.assertFalse(check.pipeline_ready_for_open_data({"status": "NO_MASTER_SNAPSHOT", "rows_found": 2}, 1))
        self.assertFalse(check.pipeline_ready_for_open_data({"status": "OK", "rows_found": 0}, 1))

    def test_post_bridge_wait_returns_success_when_pipeline_is_ready(self):
        original_fetch = check.fetch_json
        original_sleep = check.time.sleep
        try:
            check.fetch_json = lambda *args, **kwargs: (
                True,
                200,
                {"status": "OK", "rows_found": 3},
            )
            check.time.sleep = lambda *_args, **_kwargs: None

            result = check.wait_for_pipeline_after_bridge(
                "https://example.test",
                "token",
                request_timeout=1,
                wait_seconds=5,
                poll_interval=1,
                min_rows=1,
            )
        finally:
            check.fetch_json = original_fetch
            check.time.sleep = original_sleep

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["rows_found"], 3)

    def test_post_bridge_wait_can_be_disabled(self):
        result = check.wait_for_pipeline_after_bridge(
            "https://example.test",
            "token",
            request_timeout=1,
            wait_seconds=0,
            poll_interval=1,
            min_rows=1,
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["waited"])

    def test_cloud_check_passes_safe_holiday_cloud_only(self):
        health = {
            "status": "ok",
            "operating_mode": "ANALYSIS_ONLY",
            "snapshot_ingest_token_required": True,
            "market_clock": {"market_holiday": True},
        }
        pipeline = {"status": "OK", "rows_found": 0}
        decision = {
            "final_state": "WAIT_MARKET",
            "not_order_instruction": True,
            "can_operate": False,
        }

        readiness = {
            "status": "READY",
            "read_auth": {"critical_endpoints_protected": True},
            "outcome_tracking": {"version": "v31_entry_ready_signal_outcome_v1"},
            "risk_profile": {"profile_version": "v31_risk_profile_v1"},
        }

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness=readiness,
            pipeline=pipeline,
            decision=decision,
            daily_recommendations=DAILY_OK,
            strategy_performance=STRATEGY_PERFORMANCE_OK,
            require_open_data=False,
            min_rows=1,
        )

        self.assertTrue(all(item.ok for item in checks))

    def test_require_open_data_fails_on_holiday_and_no_rows(self):
        health = {
            "status": "ok",
            "operating_mode": "ANALYSIS_ONLY",
            "snapshot_ingest_token_required": True,
            "market_clock": {"market_holiday": True},
        }
        pipeline = {"status": "OK", "rows_found": 0}
        decision = {
            "final_state": "NO_DATA",
            "not_order_instruction": True,
            "can_operate": False,
        }

        readiness = {
            "status": "READY",
            "read_auth": {"critical_endpoints_protected": True},
            "outcome_tracking": {"version": "v31_entry_ready_signal_outcome_v1"},
            "risk_profile": {"profile_version": "v31_risk_profile_v1"},
        }

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness=readiness,
            pipeline=pipeline,
            decision=decision,
            daily_recommendations=DAILY_OK,
            strategy_performance=STRATEGY_PERFORMANCE_OK,
            require_open_data=True,
            min_rows=1,
        )
        failed = {item.name for item in checks if not item.ok}

        self.assertIn("market_not_holiday", failed)
        self.assertIn("rows_found_minimum", failed)
        self.assertIn("decision_not_no_data", failed)

    def test_decision_support_check_fails_if_can_operate_true(self):
        health = {
            "status": "ok",
            "operating_mode": "ANALYSIS_ONLY",
            "snapshot_ingest_token_required": True,
            "market_clock": {"market_holiday": False},
        }
        pipeline = {"status": "OK", "rows_found": 2}
        decision = {
            "final_state": "ENTRY_READY",
            "not_order_instruction": True,
            "can_operate": True,
        }

        readiness = {
            "status": "READY",
            "read_auth": {"critical_endpoints_protected": True},
            "outcome_tracking": {"version": "v31_entry_ready_signal_outcome_v1"},
            "risk_profile": {"profile_version": "v31_risk_profile_v1"},
        }

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness=readiness,
            pipeline=pipeline,
            decision=decision,
            daily_recommendations=DAILY_OK,
            strategy_performance=STRATEGY_PERFORMANCE_OK,
            require_open_data=False,
            min_rows=1,
        )
        failed = {item.name for item in checks if not item.ok}

        self.assertIn("decision_support_only", failed)

    def test_cloud_check_fails_when_read_auth_or_readiness_missing(self):
        health = {
            "status": "ok",
            "operating_mode": "ANALYSIS_ONLY",
            "snapshot_ingest_token_required": True,
            "market_clock": {"market_holiday": False},
        }
        pipeline = {"status": "OK", "rows_found": 1}
        decision = {
            "final_state": "WAIT_MARKET",
            "not_order_instruction": True,
            "can_operate": False,
        }

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": False},
            readiness={"status": "BLOCKED"},
            pipeline=pipeline,
            decision=decision,
            daily_recommendations={"status": "BLOCKED", "not_order_instruction": False},
            strategy_performance=STRATEGY_PERFORMANCE_OK,
            require_open_data=False,
            min_rows=1,
        )
        failed = {item.name for item in checks if not item.ok}

        self.assertIn("read_auth_required", failed)
        self.assertIn("production_readiness_ready", failed)

    def test_cloud_check_fails_when_strategy_performance_contract_breaks(self):
        health = {
            "status": "ok",
            "operating_mode": "ANALYSIS_ONLY",
            "snapshot_ingest_token_required": True,
            "market_clock": {"market_holiday": False},
        }
        readiness = {
            "status": "READY",
            "read_auth": {"critical_endpoints_protected": True},
            "outcome_tracking": {"version": "v31_entry_ready_signal_outcome_v1"},
            "risk_profile": {"profile_version": "v31_risk_profile_v1"},
        }
        decision = {
            "final_state": "WAIT_MARKET",
            "not_order_instruction": True,
            "can_operate": False,
        }

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness=readiness,
            pipeline={"status": "OK", "rows_found": 1},
            decision=decision,
            daily_recommendations=DAILY_OK,
            strategy_performance={
                "engine": "V32_STRATEGY_PERFORMANCE",
                "strategy_performance_version": "wrong",
                "summary": {},
                "not_order_instruction": True,
                "execution_authorized": True,
            },
            require_open_data=False,
            min_rows=1,
        )
        failed = {item.name for item in checks if not item.ok}

        self.assertIn("strategy_performance_ok", failed)
        self.assertIn("strategy_performance_no_order", failed)


if __name__ == "__main__":
    unittest.main()

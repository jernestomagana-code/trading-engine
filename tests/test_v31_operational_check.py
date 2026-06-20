import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import v31_operational_check as check


class V31OperationalCheckTests(unittest.TestCase):
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

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness={"status": "READY"},
            pipeline=pipeline,
            decision=decision,
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

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness={"status": "READY"},
            pipeline=pipeline,
            decision=decision,
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

        checks = check.evaluate_cloud(
            health,
            unauth_status_code=401,
            read_auth={"required": True},
            readiness={"status": "READY"},
            pipeline=pipeline,
            decision=decision,
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
            require_open_data=False,
            min_rows=1,
        )
        failed = {item.name for item in checks if not item.ok}

        self.assertIn("read_auth_required", failed)
        self.assertIn("production_readiness_ready", failed)


if __name__ == "__main__":
    unittest.main()

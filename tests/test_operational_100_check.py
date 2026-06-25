import json
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import stock_ultimus_operational_100_check as operational_100


def args(**overrides):
    values = {
        "base_url": "https://example.test",
        "timeout": 1,
        "limit": 25,
        "json_out": "/tmp/operational_100_test.json",
        "no_write": True,
        "skip_cloud": False,
        "real_outcomes_after_close": False,
    }
    values.update(overrides)
    return Namespace(**values)


def fake_step(name, command, timeout, env):
    payloads = {
        "gpt_action_health": {
            "status": "OK",
            "execution_authorized": False,
            "not_order_instruction": True,
        },
        "cloud_operational_audit": {
            "status": "PASS",
            "execution_authorized": False,
            "not_order_instruction": True,
        },
        "outcome_learning_dry_run": {
            "execution_authorized": False,
            "not_order_instruction": True,
        },
        "outcome_learning_real_write": {
            "execution_authorized": False,
            "not_order_instruction": True,
        },
    }
    return {
        "name": name,
        "ok": True,
        "exit_code": 0,
        "command": command,
        "stdout_tail": json.dumps(payloads[name]),
        "stderr_tail": "",
    }


class Operational100CheckTests(unittest.TestCase):
    def test_preflight_passes_with_warning_when_real_outcomes_not_requested(self):
        with patch.object(operational_100, "run_command", side_effect=fake_step):
            result = operational_100.run(args())

        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertFalse(result["real_outcome_write_requested"])
        self.assertTrue(result["not_order_instruction"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["uses_ingest_token"])
        self.assertFalse(result["touches_ibkr"])
        self.assertFalse(result["sends_email"])
        gate_names = {gate["name"] for gate in result["gates"]}
        self.assertIn("gpt_action_backend_health", gate_names)
        self.assertIn("cloud_operational_audit", gate_names)
        self.assertIn("outcome_learning_dry_run", gate_names)
        self.assertIn("real_outcome_write_after_close", gate_names)
        self.assertIn("manual_review_process_surfaces", gate_names)

    def test_explicit_post_close_mode_runs_real_outcome_write(self):
        calls = []

        def record_step(name, command, timeout, env):
            calls.append(name)
            return fake_step(name, command, timeout, env)

        with patch.object(operational_100, "run_command", side_effect=record_step):
            result = operational_100.run(args(real_outcomes_after_close=True))

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["real_outcome_write_requested"])
        self.assertIn("outcome_learning_real_write", calls)

    def test_failed_gpt_health_fails_preflight(self):
        def failed_step(name, command, timeout, env):
            if name == "gpt_action_health":
                return {
                    "name": name,
                    "ok": False,
                    "exit_code": 1,
                    "command": command,
                    "stdout_tail": json.dumps({"status": "FAIL"}),
                    "stderr_tail": "",
                }
            return fake_step(name, command, timeout, env)

        with patch.object(operational_100, "run_command", side_effect=failed_step):
            result = operational_100.run(args())

        self.assertEqual(result["status"], "FAIL")
        failed = {gate["name"] for gate in result["gates"] if not gate["ok"]}
        self.assertIn("gpt_action_backend_health", failed)

    def test_real_outcome_write_is_blocked_when_preconditions_fail(self):
        calls = []

        def failed_audit_step(name, command, timeout, env):
            calls.append(name)
            if name == "cloud_operational_audit":
                return {
                    "name": name,
                    "ok": False,
                    "exit_code": 1,
                    "command": command,
                    "stdout_tail": json.dumps({"status": "FAIL"}),
                    "stderr_tail": "",
                }
            return fake_step(name, command, timeout, env)

        with patch.object(operational_100, "run_command", side_effect=failed_audit_step):
            result = operational_100.run(args(real_outcomes_after_close=True))

        self.assertEqual(result["status"], "FAIL")
        self.assertNotIn("outcome_learning_real_write", calls)
        real_gate = [gate for gate in result["gates"] if gate["name"] == "real_outcome_write_after_close"][-1]
        self.assertFalse(real_gate["ok"])
        self.assertIn("preconditions failed", real_gate["detail"])


if __name__ == "__main__":
    unittest.main()

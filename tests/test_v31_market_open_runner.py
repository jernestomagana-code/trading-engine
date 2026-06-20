import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import v31_market_open_runner as runner


ROOT = Path(__file__).resolve().parents[1]


def _args(**overrides):
    parser = runner.build_parser()
    args = parser.parse_args([])
    for key, value in overrides.items():
        setattr(args, key, value)
    args.ticker = args.ticker.upper()
    return args


class V31MarketOpenRunnerTests(unittest.TestCase):
    def test_quote_probe_command_uses_readonly_probe_defaults(self):
        args = _args(ticker="spy")
        cmd = runner.quote_probe_command(args)

        self.assertIn("tools/ibkr_option_quote_probe.py", cmd)
        self.assertIn("--ticker", cmd)
        self.assertIn("SPY", cmd)
        self.assertIn("--target-dte", cmd)
        self.assertIn("45", cmd)
        self.assertIn("--otm-pct", cmd)
        self.assertIn("0.1", cmd)

    def test_operational_check_command_runs_bridge_and_requires_open_data_by_default(self):
        cmd = runner.operational_check_command(_args())

        self.assertIn("tools/v31_operational_check.py", cmd)
        self.assertIn("--run-bridge", cmd)
        self.assertIn("--require-open-data", cmd)
        self.assertIn("--min-rows", cmd)
        self.assertIn("1", cmd)

    def test_operational_check_command_can_skip_bridge_and_allow_closed_market(self):
        cmd = runner.operational_check_command(_args(skip_bridge=True, allow_closed_market=True))

        self.assertNotIn("--run-bridge", cmd)
        self.assertNotIn("--require-open-data", cmd)

    def test_dry_run_does_not_read_keychain_and_prints_no_secrets(self):
        args = _args(dry_run=True)
        with patch.object(runner, "keychain_secret") as keychain_secret:
            result = runner.run_market_open_validation(args, ROOT)

        keychain_secret.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["secrets_printed"])
        self.assertEqual([step["name"] for step in result["steps"]], [
            "ibkr_option_quote_probe",
            "v31_operational_check",
        ])
        self.assertTrue(all(step["skipped"] for step in result["steps"]))

    def test_probe_failure_stops_before_operational_check_by_default(self):
        args = _args()
        failed_probe = runner.StepResult(
            name="ibkr_option_quote_probe",
            ok=False,
            command=["probe"],
            exit_code=1,
            stdout_tail="NO_VALID_OPTION_PRICE",
        )

        with patch.object(runner, "build_env", return_value={}), patch.object(
            runner,
            "run_step",
            return_value=failed_probe,
        ) as run_step:
            result = runner.run_market_open_validation(args, ROOT)

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["steps"]), 1)
        run_step.assert_called_once()

    def test_continue_on_probe_failure_still_runs_operational_check(self):
        args = _args(continue_on_probe_failure=True)
        failed_probe = runner.StepResult(name="ibkr_option_quote_probe", ok=False, command=["probe"], exit_code=1)
        passed_check = runner.StepResult(name="v31_operational_check", ok=True, command=["check"], exit_code=0)

        with patch.object(runner, "build_env", return_value={}), patch.object(
            runner,
            "run_step",
            side_effect=[failed_probe, passed_check],
        ):
            result = runner.run_market_open_validation(args, ROOT)

        self.assertFalse(result["ok"])
        self.assertEqual([step["name"] for step in result["steps"]], [
            "ibkr_option_quote_probe",
            "v31_operational_check",
        ])


if __name__ == "__main__":
    unittest.main()

import inspect
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_v29_v30_contract_gating import main
from scripts import daily_open_checklist


class RenderResponsivenessTests(unittest.TestCase):
    def tearDown(self):
        main._SUPABASE_TABLE_READ_CACHE.clear()

    def test_health_is_local_only_and_never_calls_remote_loaders(self):
        with (
            patch.object(main, "load_signals", side_effect=AssertionError("remote signals called")),
            patch.object(
                main,
                "_v32_load_tradingview_signal_events",
                side_effect=AssertionError("remote ledger called"),
            ),
            patch.object(main, "load_signals_from_file", return_value=[]),
            patch.object(
                main.shared_tradingview_signal_ledger,
                "load_signal_events",
                return_value=[],
            ),
        ):
            payload = main.health()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["health_scope"], "LOCAL_LIVENESS_ONLY")

    def test_production_table_reads_are_cached(self):
        response = Mock(status_code=200)
        response.json.return_value = [
            {"id": "new"},
            {"id": "old"},
        ]
        with (
            patch.object(main, "SUPABASE_URL", "https://example.supabase.co"),
            patch.object(main, "SUPABASE_KEY", "secret"),
            patch.object(main, "_supabase_table_read_cache_enabled", return_value=True),
            patch.object(main.requests, "get", return_value=response) as request_get,
        ):
            first = main.supabase_fetch_table_rows("events", limit=2)
            second = main.supabase_fetch_table_rows("events", limit=1)

        self.assertEqual(first, [{"id": "old"}, {"id": "new"}])
        self.assertEqual(second, [{"id": "new"}])
        self.assertEqual(request_get.call_count, 1)

    def test_operator_routes_run_in_fastapi_threadpool(self):
        self.assertFalse(inspect.iscoroutinefunction(main.v32_operator_today))
        self.assertFalse(inspect.iscoroutinefunction(main.gpt_v32_operator_today))
        self.assertFalse(inspect.iscoroutinefunction(main.v32_operator_next_actions))

    def test_operator_reuses_command_center_readiness(self):
        command = {
            "status": "READY_FOR_DECISION_REVIEW",
            "operational_readiness": "READY",
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "main_blocker": None,
            },
        }

        readiness = main._v32_operator_readiness_from_command(command)

        self.assertEqual(readiness["status"], "READY_FOR_DECISION_REVIEW")
        self.assertEqual(readiness["operational_readiness"], "READY")
        self.assertEqual(readiness["source"], "COMMAND_CENTER_REUSED")

    def test_daily_publisher_wrapper_allows_all_configured_retries(self):
        args = Mock(allow_stale_publish=True)
        captured = {}

        def fake_run(name, command, timeout, env):
            captured.update(name=name, command=command, timeout=timeout, env=env)
            return {"ok": True}

        with patch.object(daily_open_checklist, "run_command", side_effect=fake_run):
            result = daily_open_checklist.publish_runtime(args, "secret")

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(captured["timeout"], 156)
        self.assertNotIn("secret", captured["command"])

    def test_rsp_bridge_does_not_overwrite_general_radar_files(self):
        source = (Path(__file__).resolve().parents[1] / "ibkr_bridge.py").read_text()

        self.assertIn(
            '"runtime/coberturas_rsp_decision_desk_latest.json"\n'
            "    if COBERTURAS_RSP_WEEKLY\n"
            '    else "runtime/decision_desk_snapshot.json"',
            source,
        )
        self.assertIn(
            'saved = ibkr_diagnostics.write_cycle_diagnostic(\n'
            '            diagnostic,\n'
            '            _v283_Path("runtime") / "coberturas_rsp_chain_coverage_latest.json",',
            source,
        )
        self.assertIn(
            "else:\n        saved = ibkr_diagnostics.write_cycle_diagnostic(diagnostic)",
            source,
        )


if __name__ == "__main__":
    unittest.main()

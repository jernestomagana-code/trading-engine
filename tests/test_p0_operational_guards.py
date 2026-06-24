import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ibkr_bridge.py"
APP = ROOT / "app" / "main.py"
GITIGNORE = ROOT / ".gitignore"
ROTATE_TOKEN_TOOL = ROOT / "tools" / "rotate_snapshot_ingest_token.py"
MONITOR_NOTIFY_WORKFLOW = ROOT / ".github" / "workflows" / "v31-monitor-notify.yml"
MANUAL_REVIEW_EVALUATE_WORKFLOW = ROOT / ".github" / "workflows" / "v31-manual-review-evaluate.yml"
WEEKLY_LEARNING_EMAIL_WORKFLOW = ROOT / ".github" / "workflows" / "v31-weekly-learning-email.yml"
DAILY_OPERATIONAL_AUDIT_WORKFLOW = ROOT / ".github" / "workflows" / "v31-daily-operational-audit.yml"
DAILY_OPERATIONAL_AUDIT_TOOL = ROOT / "tools" / "v31_daily_operational_audit.py"


class BridgeEntrypointTests(unittest.TestCase):
    def test_bridge_loop_is_not_executed_at_module_scope(self):
        tree = ast.parse(BRIDGE.read_text(), filename=str(BRIDGE))
        self.assertFalse(any(isinstance(node, ast.While) for node in tree.body))

        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("run_bridge_cycle", functions)
        self.assertIn("run_bridge_forever", functions)

        forever = functions["run_bridge_forever"]
        self.assertTrue(any(isinstance(node, ast.While) for node in ast.walk(forever)))
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "time"
            and node.func.attr == "sleep"
            for node in ast.walk(forever)
        ))

    def test_bridge_does_not_hardcode_market_open_and_sends_ingest_token(self):
        source = BRIDGE.read_text()
        self.assertNotIn('"is_regular_market_open": True', source)
        self.assertNotIn('"options_bidask_expected": True', source)
        self.assertIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertIn("X-Snapshot-Ingest-Token", source)

    def test_fast_option_universe_covers_default_radar(self):
        tree = ast.parse(BRIDGE.read_text(), filename=str(BRIDGE))
        module_vars = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    module_vars[node.targets[0].id] = ast.literal_eval(node.value)
                except Exception:
                    continue

        default_watchlist = set(module_vars["DEFAULT_WATCHLIST"])
        default_option_symbols = set(module_vars["DEFAULT_OPTION_SYMBOLS"])
        self.assertEqual(default_watchlist, default_option_symbols)

        source = BRIDGE.read_text()
        self.assertIn("FAST_WATCHLIST = list(DEFAULT_WATCHLIST)", source)
        self.assertIn("FAST_OPTION_SYMBOLS = list(DEFAULT_OPTION_SYMBOLS)", source)

    def test_option_chain_selection_prefers_exact_trading_class(self):
        source = BRIDGE.read_text()
        self.assertIn("def option_chain_symbol_match_rank", source)
        self.assertIn("trading_class == symbol", source)
        self.assertIn("trading_class.endswith(symbol)", source)
        self.assertIn('x["symbol_match_rank"]', source)


class SnapshotIngestAuthTests(unittest.TestCase):
    def test_v31_ingest_uses_constant_time_token_verification(self):
        tree = ast.parse(APP.read_text(), filename=str(APP))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        verifier = functions["verify_snapshot_ingest_token"]
        verifier_calls = {
            node.func.attr
            for node in ast.walk(verifier)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("compare_digest", verifier_calls)

        ingest = functions["v31_ingest_snapshot"]
        ingest_calls = {
            node.func.id
            for node in ast.walk(ingest)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("verify_snapshot_ingest_token", ingest_calls)


class RepositorySafetyTests(unittest.TestCase):
    def test_sensitive_runtime_paths_are_gitignored(self):
        ignored = GITIGNORE.read_text().splitlines()

        self.assertIn("runtime/", ignored)
        self.assertIn(".env", ignored)
        self.assertIn(".env.*", ignored)
        self.assertIn("!.env.example", ignored)
        self.assertIn("*.log", ignored)


class TokenRotationToolTests(unittest.TestCase):
    def test_snapshot_token_rotation_tool_never_prints_secret_value(self):
        source = ROTATE_TOKEN_TOOL.read_text()
        tree = ast.parse(source, filename=str(ROTATE_TOKEN_TOOL))

        self.assertIn("secrets.token_hex(32)", source)
        self.assertIn("add-generic-password", source)
        self.assertIn("pbcopy", source)
        self.assertIn("token_printed=false", source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                printed = ast.get_source_segment(source, node) or ""
                self.assertNotIn("token)", printed)
                self.assertNotIn("{token", printed)


class MonitorNotifyWorkflowTests(unittest.TestCase):
    def test_v31_monitor_workflow_uses_protected_notify_endpoint(self):
        source = MONITOR_NOTIFY_WORKFLOW.read_text()

        self.assertIn("cron:", source)
        self.assertIn("/v31_monitor_notify", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)


class ManualReviewEvaluateWorkflowTests(unittest.TestCase):
    def test_v31_manual_review_evaluate_workflow_uses_protected_endpoint(self):
        source = MANUAL_REVIEW_EVALUATE_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertIn("cron:", source)
        self.assertIn("/v31_evaluate_manual_reviews", source)
        self.assertIn("EOD,PLUS_1D,PLUS_5D", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)


class WeeklyLearningEmailWorkflowTests(unittest.TestCase):
    def test_v31_weekly_learning_email_workflow_uses_protected_notify_endpoint(self):
        source = WEEKLY_LEARNING_EMAIL_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertIn("cron:", source)
        self.assertIn("/v31_manual_review_learning_notify", source)
        self.assertIn("/v31_manual_review_learning_notify/preview", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)


class DailyOperationalAuditWorkflowTests(unittest.TestCase):
    def test_v31_daily_audit_workflow_is_read_only_and_guarded(self):
        source = DAILY_OPERATIONAL_AUDIT_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertIn("cron:", source)
        self.assertIn("issues: write", source)
        self.assertIn("tools/v31_daily_operational_audit.py", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("READ_ACCESS_TOKEN", source)
        self.assertIn("continue-on-error: true", source)
        self.assertIn("Trading day readiness", source)
        self.assertIn("gh issue create", source)
        self.assertIn("gh issue comment", source)
        self.assertIn("Stock Ultimus V31 daily operational audit failed", source)
        self.assertIn("Fail job if audit failed", source)
        self.assertIn("env.DRY_RUN != 'true'", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertIn("uses_ingest_token", source)
        self.assertIn("sends_email", source)
        self.assertIn("touches_ibkr", source)
        self.assertIn("secrets_printed", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("ibkr_bridge.py", source)
        self.assertNotIn("/v31_ingest_snapshot", source)
        self.assertNotIn("send_resend_email", source)

    def test_v31_daily_audit_tool_never_uses_ingest_or_email_paths(self):
        source = DAILY_OPERATIONAL_AUDIT_TOOL.read_text()

        self.assertIn("V31_DAILY_OPERATIONAL_AUDIT", source)
        self.assertIn("/v31_trading_day_readiness", source)
        self.assertIn("/v31_evaluate_manual_reviews", source)
        self.assertIn("dry_run=true", source)
        self.assertIn("/v31_manual_review_learning_notify/preview", source)
        self.assertIn("/v31_monitor_notify/preview", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("send_resend_email", source)
        self.assertNotIn("ib_insync", source)


if __name__ == "__main__":
    unittest.main()

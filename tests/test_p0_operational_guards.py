import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ibkr_bridge.py"
APP = ROOT / "app" / "main.py"
GITIGNORE = ROOT / ".gitignore"
ROTATE_TOKEN_TOOL = ROOT / "tools" / "rotate_snapshot_ingest_token.py"
MONITOR_NOTIFY_WORKFLOW = ROOT / ".github" / "workflows" / "v31-monitor-notify.yml"


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


if __name__ == "__main__":
    unittest.main()

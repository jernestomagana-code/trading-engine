import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ibkr_bridge.py"
IBKR_ACCOUNT_PROFILE = ROOT / "scripts" / "ibkr_account_profile.py"
APP = ROOT / "app" / "main.py"
GITIGNORE = ROOT / ".gitignore"
ROTATE_TOKEN_TOOL = ROOT / "tools" / "rotate_snapshot_ingest_token.py"
ROTATE_READ_TOKEN_TOOL = ROOT / "tools" / "rotate_read_access_token.py"
MONITOR_NOTIFY_WORKFLOW = ROOT / ".github" / "workflows" / "v31-monitor-notify.yml"
MANUAL_REVIEW_EVALUATE_WORKFLOW = ROOT / ".github" / "workflows" / "v31-manual-review-evaluate.yml"
WEEKLY_LEARNING_EMAIL_WORKFLOW = ROOT / ".github" / "workflows" / "v31-weekly-learning-email.yml"
DAILY_OPERATIONAL_AUDIT_WORKFLOW = ROOT / ".github" / "workflows" / "v31-daily-operational-audit.yml"
V32_CLOUD_PUSHOVER_WORKFLOW = ROOT / ".github" / "workflows" / "v32-cloud-pushover.yml"
V32_OPERATOR_NUDGES_WORKFLOW = ROOT / ".github" / "workflows" / "v32-operator-nudges.yml"
V32_ACTIONABLE_SIGNAL_WATCH_WORKFLOW = ROOT / ".github" / "workflows" / "v32-actionable-signal-watch.yml"
DAILY_OPERATIONAL_AUDIT_TOOL = ROOT / "tools" / "v31_daily_operational_audit.py"
OPERATING_DAY_RUNNER = ROOT / "scripts" / "run_operating_day.py"
DAILY_RADAR_RUNNER = ROOT / "scripts" / "run_daily_radar.py"
OPERATIONAL_100_CHECK = ROOT / "scripts" / "stock_ultimus_operational_100_check.py"
DAILY_OPEN_CHECKLIST = ROOT / "scripts" / "daily_open_checklist.py"
V32_NUDGE_PREFLIGHT_CHECK = ROOT / "scripts" / "v32_nudge_preflight_check.py"
V32_OPERATOR_NOTIFY = ROOT / "scripts" / "v32_operator_notify.py"
PUSHOVER_CHANNEL_SETUP = ROOT / "scripts" / "setup_pushover_channel.py"
PUSHOVER_AUTOMATION = ROOT / "scripts" / "v32_pushover_automation.py"
PUSHOVER_LAUNCHD_INSTALLER = ROOT / "scripts" / "install_v32_pushover_launchd.py"
LOCAL_CONSOLE_LAUNCHD_INSTALLER = ROOT / "scripts" / "install_stock_ultimus_console_launchd.py"
LOCAL_CONSOLE_COMMAND = ROOT / "Stock Ultimus Console.command"


class BridgeEntrypointTests(unittest.TestCase):
    def test_fastapi_routes_are_not_registered_twice(self):
        tree = ast.parse(APP.read_text(), filename=str(APP))
        registrations = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
                    continue
                if decorator.func.attr not in {"get", "post", "put", "delete", "patch"}:
                    continue
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    registrations.append((decorator.func.attr, decorator.args[0].value))

        duplicates = sorted({item for item in registrations if registrations.count(item) > 1})
        self.assertEqual(duplicates, [])

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
        self.assertTrue({"AAPL", "MSFT", "NVDA", "META", "AMZN", "TSLA", "GOOGL"}.issubset(default_watchlist))
        self.assertTrue({"AVGO", "AMD", "COST", "CRM", "ORCL", "RSP"}.issubset(default_watchlist))
        self.assertTrue({"PLTR", "CRWD", "NOW", "UBER", "PANW"}.issubset(default_watchlist))

        source = BRIDGE.read_text()
        fast_watchlist = set(module_vars["FAST_WATCHLIST"])
        self.assertLess(len(fast_watchlist), len(default_watchlist))
        self.assertTrue({"QQQ", "SPY", "RSP", "TLT"}.issubset(fast_watchlist))
        self.assertIn("IBKR_MAX_WATCHLIST_SYMBOLS_PER_RUN", source)
        self.assertIn("WATCHLIST_REQUESTED[:MAX_WATCHLIST_SYMBOLS_PER_RUN]", source)
        self.assertIn("FAST_OPTION_SYMBOLS = list(DEFAULT_OPTION_SYMBOLS)", source)

    def test_option_chain_selection_prefers_exact_trading_class(self):
        source = BRIDGE.read_text()
        self.assertIn("def option_chain_symbol_match_rank", source)
        self.assertIn("trading_class == symbol", source)
        self.assertIn("trading_class.endswith(symbol)", source)
        self.assertIn('x["symbol_match_rank"]', source)

    def test_bridge_limits_option_chains_with_dynamic_underlying_universe(self):
        source = BRIDGE.read_text()
        self.assertIn("IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED", source)
        self.assertIn("IBKR_MAX_OPTION_SYMBOLS_PER_RUN", source)
        self.assertIn("IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN", source)
        self.assertIn("IBKR_OPTION_CONTEXT_ONLY_SYMBOLS", source)
        self.assertIn("IBKR_OPTION_TECHNICAL_TRIGGER_SCORE", source)
        self.assertIn("IBKR_OPTION_CANSLIM_TRIGGER_SCORE", source)
        self.assertIn("8 if DAILY_RADAR_FAST else 14", source)
        self.assertIn("16 if DAILY_RADAR_FAST else 64", source)
        self.assertIn("OPTION_MIN_UNDERLYING_SCORE", source)
        self.assertIn("CONTEXT_ONLY_NO_ACTION_TRIGGER", source)
        self.assertIn("INVALID_OPTION_UNDERLYING_SYMBOL", source)
        self.assertIn("invalid_candidate_symbols", source)
        self.assertIn("def build_dynamic_option_symbol_plan", source)
        self.assertIn("option_underlying_rank", source)
        self.assertIn("OPTION_CONTRACT_BUDGET_APPLIED", source)
        self.assertIn("underlying_rank_score", source)
        self.assertIn("symbol_plan=symbol_plan", source)
        self.assertIn("def _bridge_extract_canslim_candidates", source)
        self.assertIn("def _bridge_merge_canslim_candidates_into_technical", source)
        self.assertIn("canslim_candidate_count", source)
        self.assertIn("canslim_score", source)

    def test_bridge_account_context_is_sanitized_for_broker_checks(self):
        source = BRIDGE.read_text()
        self.assertIn("def _bridge_account_context_snapshot", source)
        self.assertIn("ib.accountSummary()", source)
        self.assertIn("account=selected", source)
        self.assertIn('"NetLiquidation": "net_liquidation"', source)
        self.assertIn('"BuyingPower": "buying_power"', source)
        self.assertIn('"AvailableFunds": "available_funds"', source)
        self.assertIn('"sensitive_identifiers_excluded": True', source)
        self.assertIn('"account_scope"', source)
        self.assertIn('"account_alias"', source)
        self.assertIn('"selected_account_configured"', source)

        tree = ast.parse(source, filename=str(BRIDGE))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        function_source = ast.get_source_segment(source, functions["_bridge_account_context_snapshot"]) or ""
        self.assertNotIn("account_id", function_source)
        self.assertNotIn("acctCode", function_source)
        self.assertNotIn("accountNumber", function_source)

    def test_ibkr_account_selector_has_local_web_flow_without_printing_ids(self):
        source = IBKR_ACCOUNT_PROFILE.read_text()
        self.assertIn("ThreadingHTTPServer((host, int(args.port)), AccountProfileWebHandler)", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_KEYCHAIN_TIMEOUT_SECONDS", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_REMOTE_TIMEOUT_SECONDS", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn("def cmd_serve", source)
        self.assertIn("WEB_LAST_RESULT_PATH", source)
        self.assertIn("WEB_JOBS", source)
        self.assertIn("def start_web_job", source)
        self.assertIn('"/job-status"', source)
        self.assertIn('"RUNNING"', source)
        self.assertIn("Refresh IBKR iniciado", source)
        self.assertIn("busy-overlay", source)
        self.assertIn("Alinear cuenta rapido", source)
        self.assertIn("Refresh profundo opciones", source)
        self.assertIn("def console_health", source)
        self.assertIn("def render_console_health", source)
        self.assertIn("def render_active_process_panel", source)
        self.assertIn("def render_today_panel", source)
        self.assertIn("def render_module_health", source)
        self.assertIn("def render_timeline", source)
        self.assertIn("def render_market_mode_panel", source)
        self.assertIn("def render_diagnostic_panel", source)
        self.assertIn("control-strip", source)
        self.assertIn("signal-dot", source)
        self.assertIn("health-green", source)
        self.assertIn("PROCESS_RUNNING", source)
        self.assertIn("La consola esta trabajando", source)
        self.assertIn("Modo Hoy", source)
        self.assertIn("Semaforo por modulo", source)
        self.assertIn("Timeline operativo", source)
        self.assertIn("Modo mercado abierto", source)
        self.assertIn("Diagnostico completo", source)
        self.assertIn("sanitize_output", source)
        self.assertIn('"[REDACTED_IBKR_ACCOUNT]"', source)
        self.assertIn('"account_id_printed": False', source)
        self.assertIn("Decision support only; no autoriza ordenes", source)
        self.assertIn("Stock Ultimus Console", source)
        self.assertIn("def latest_master_snapshot", source)
        self.assertIn("def console_operator_payload", source)
        self.assertIn("def selected_vs_published", source)
        self.assertIn("def published_context_value", source)
        self.assertIn("UNKNOWN_CONTEXT_VALUES", source)
        self.assertIn("Alinear cuenta rapido", source)
        self.assertIn('"/bridge-deep"', source)
        self.assertIn('"/select-refresh"', source)
        self.assertIn("Solo usar cuenta</button>", source)
        self.assertIn("Publicando cuenta para GPT", source)
        self.assertIn("solo trae datos frescos del broker", source)
        self.assertIn("CACHE_FIRST_CONSOLE_RENDER", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_JOB_TIMEOUT_SECONDS", source)
        self.assertIn("subprocess.TimeoutExpired", source)
        self.assertIn("def process_output_text", source)
        self.assertIn("decode(\"utf-8\", errors=\"replace\")", source)
        self.assertIn('"timed_out": timed_out', source)
        self.assertIn("TIMEOUT: comando detenido", source)
        self.assertIn("def console_bridge_command", source)
        self.assertIn("scripts/run_market_bridge_session.py", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_BRIDGE_TIMEOUT_SECONDS", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_OPTION_SYMBOLS", source)
        self.assertIn("QQQ,SPY,AAPL,NVDA,TSLA,RSP", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_MAX_OPTIONS_PER_SYMBOL", source)
        self.assertIn("STOCK_ULTIMUS_CONSOLE_IBKR_CLIENT_ID", source)
        self.assertIn("--ibkr-client-id", source)
        self.assertIn("IBKR_OPTION_MARKET_DATA_TYPE_SEQUENCE", source)
        self.assertIn("def enrich_console_bridge_output", source)
        self.assertIn("bridge session detail", source)
        self.assertIn("def console_job_diagnostic", source)
        self.assertIn("IBKR esta en puerto abierto", source)
        self.assertIn("No sigas presionando Refresh", source)
        self.assertIn("stock_ultimus_console_bridge_latest.json", source)
        self.assertIn("Solo relee la pantalla local; no lanza otro trabajo", source)
        self.assertIn("Alinear/Publicar rapido</strong>", source)
        self.assertIn("def do_HEAD", source)
        self.assertIn("/gpt_v32_operator_today?limit=12", source)
        self.assertIn("READ_ACCESS_TOKEN", source)
        self.assertIn("def read_keychain_value_any_account", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("/v32_operator_daily_summary_email/preview", source)
        self.assertIn("/coberturas", source)
        self.assertIn("Coberturas RSP", source)
        self.assertIn("def render_coberturas_inline_panel", source)
        self.assertIn('name="gamma_blob"', source)
        self.assertIn('name="return_to" value="console"', source)
        self.assertIn('payload.get("return_to") == "console"', source)
        self.assertIn("def post_remote_json", source)
        self.assertIn('"/diagnostic"', source)
        self.assertIn("console_diagnostic_command", source)
        self.assertIn('"/operator-event"', source)
        self.assertIn('"/gpt_v32_operator_event"', source)
        self.assertIn('"MARK_REVIEWING"', source)
        self.assertIn('"MARK_WATCHLIST"', source)
        self.assertIn('"MARK_PAPER_TRACKED"', source)
        self.assertIn('"MARK_IBKR_APPLIED"', source)
        self.assertIn('"MARK_IBKR_NOT_APPLIED"', source)
        self.assertIn('"MARK_MISSED"', source)
        self.assertIn('"REJECT_SETUP"', source)
        self.assertIn("Visto</button>", source)
        self.assertIn("Revisando</button>", source)
        self.assertIn("IBKR aplicada</button>", source)
        self.assertIn("MARK_IBKR_APPLIED", source)
        self.assertIn("ibkr_fill_price", source)
        self.assertIn("alert_lifecycle", source)
        self.assertIn("status-new", source)
        self.assertIn("alert-checklist", source)
        self.assertIn("why-line", source)
        self.assertIn("def alert_reason_plain", source)
        self.assertIn("Queda registrado para seguimiento/backtesting", source)
        self.assertIn('"execution_authorized": False', source)

        app_source = APP.read_text()
        self.assertIn('"MARK_IBKR_APPLIED"', app_source)
        self.assertIn("OPERATOR_EVENT_IBKR_FILL_REQUIRED", app_source)
        self.assertIn("shared_alert_lifecycle.alert_lifecycle_state", app_source)

    def test_gpt_payloads_surface_sanitized_account_context(self):
        source = APP.read_text()
        self.assertIn("def _v31_account_context_from_master", source)
        self.assertIn('"v31_sanitized_account_context_v1"', source)
        self.assertIn('"real_account_id_excluded": True', source)
        self.assertIn('"gpt_context_rule"', source)
        self.assertIn('"account_context": account_context', source)
        self.assertIn('"account_context": today.get("account_context") or {}', source)

    def test_bridge_account_selection_is_local_and_filters_positions(self):
        source = BRIDGE.read_text()
        self.assertIn("def _bridge_account_selection", source)
        self.assertIn("def _bridge_selected_ibkr_account", source)
        self.assertIn("def _bridge_public_account_selection", source)
        self.assertIn("IBKR_ACCOUNT_ALIAS", source)
        self.assertIn("IBKR_ACCOUNT_MAP", source)
        self.assertIn("IBKR_ACCOUNT_ID", source)
        self.assertIn("STOCK_ULTIMUS_ACCOUNT_SCOPE", source)
        self.assertIn("ib.managedAccounts()", source)
        self.assertIn("ACCOUNT_SELECTION_REQUIRED", source)
        self.assertIn("selected IBKR account is not visible", source)
        self.assertIn('getattr(position, "account"', source)
        self.assertIn('"sensitive_identifiers_excluded": True', source)

    def test_ibkr_account_profile_helper_keeps_real_ids_local(self):
        source = IBKR_ACCOUNT_PROFILE.read_text()
        self.assertIn("stock-ultimus-ibkr-account-", source)
        self.assertIn("add-generic-password", source)
        self.assertIn("find-generic-password", source)
        self.assertIn("account_id_printed=false", source)
        self.assertIn("real_account_id_printed", source)
        self.assertIn("STOCK_ULTIMUS_ACCOUNT_SCOPE", source)
        self.assertIn("IBKR_ACCOUNT_ALIAS", source)
        self.assertIn("IBKR_ACCOUNT_ID", source)
        self.assertIn("ibkr_bridge.py", source)
        self.assertIn("daily_open_checklist.py", source)
        self.assertIn("not_order_instruction", source)

    def test_bridge_connection_retries_write_local_health_without_orders(self):
        source = BRIDGE.read_text()

        self.assertIn("def connect_ibkr_with_retries", source)
        self.assertIn("IB_CONNECT_RETRIES", source)
        self.assertIn("ibkr_bridge_health_latest.json", source)
        self.assertIn('"CONNECTION_FAILED"', source)
        self.assertIn("readonly=True", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)

    def test_bridge_positions_feed_broker_snapshot_context(self):
        source = BRIDGE.read_text()
        tree = ast.parse(source, filename=str(BRIDGE))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        send_positions_source = ast.get_source_segment(source, functions["send_positions"]) or ""
        broker_context_source = ast.get_source_segment(source, functions["_bridge_cycle_position_rows"]) or ""

        self.assertIn("v17_store_row(payload)", send_positions_source)
        self.assertIn("IBKR_PORTFOLIO_COMMANDER", broker_context_source)
        self.assertIn("position_size", broker_context_source)

    def test_legacy_bridge_outputs_never_advertise_can_operate_true(self):
        source = BRIDGE.read_text()
        self.assertNotIn("can_operate:{nba.get('can_operate')}", source)
        self.assertIn("manual_review_ready:{nba.get('manual_review_ready')}", source)
        self.assertIn('"can_operate_count": 0', source)
        self.assertIn("def v18_can_operate", source)
        self.assertIn("return False", ast.get_source_segment(
            source,
            {
                node.name: node
                for node in ast.parse(source, filename=str(BRIDGE)).body
                if isinstance(node, ast.FunctionDef)
            }["v18_can_operate"],
        ) or "")


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

    def test_read_token_rotation_tool_never_prints_secret_value(self):
        source = ROTATE_READ_TOKEN_TOOL.read_text()
        tree = ast.parse(source, filename=str(ROTATE_READ_TOKEN_TOOL))

        self.assertIn("secrets.token_hex(32)", source)
        self.assertIn("add-generic-password", source)
        self.assertIn("pbcopy", source)
        self.assertIn("token_printed=false", source)
        self.assertIn("stock-ultimus-read-access-token", source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                printed = ast.get_source_segment(source, node) or ""
                self.assertNotIn("token)", printed)
                self.assertNotIn("{token", printed)


class MonitorNotifyWorkflowTests(unittest.TestCase):
    def test_v31_monitor_workflow_uses_protected_notify_endpoint(self):
        source = MONITOR_NOTIFY_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("cron:", source)
        self.assertIn("/v31_monitor_notify", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)


class CloudPushoverWorkflowTests(unittest.TestCase):
    def test_v32_cloud_pushover_workflow_uses_protected_endpoint_without_push_secrets(self):
        source = V32_CLOUD_PUSHOVER_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("cron:", source)
        self.assertIn("/v32_operator_pushover_notify", source)
        self.assertIn("timeout=90", source)
        self.assertIn("Timed out waiting for /v32_operator_pushover_notify after 90 seconds.", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("deduped", source)
        self.assertIn("notify_reason", source)
        self.assertIn("no_data", source)
        self.assertIn("data_refresh_required", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("PUSHOVER_USER_KEY", source)
        self.assertNotIn("PUSHOVER_API_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)

    def test_v32_operator_nudges_workflow_uses_protected_endpoint_without_push_secrets(self):
        source = V32_OPERATOR_NUDGES_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("cron:", source)
        self.assertIn("/v32_operator_nudge", source)
        self.assertIn("timeout=90", source)
        self.assertIn("Timed out waiting for /v32_operator_nudge after 90 seconds.", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("NUDGE_SLOT", source)
        self.assertIn("deduped", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("PUSHOVER_USER_KEY", source)
        self.assertNotIn("PUSHOVER_API_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)

    def test_v32_actionable_signal_watch_workflow_uses_protected_endpoint_without_push_secrets(self):
        source = V32_ACTIONABLE_SIGNAL_WATCH_WORKFLOW.read_text()

        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("cron:", source)
        self.assertNotIn("*/5", source)
        self.assertIn("/v32_actionable_signal_watch", source)
        self.assertIn("timeout=90", source)
        self.assertIn("Timed out waiting for /v32_actionable_signal_watch after 90 seconds.", source)
        self.assertIn("STOCK_ULTIMUS_READ_ACCESS_TOKEN", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("new_candidate_count", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("PUSHOVER_USER_KEY", source)
        self.assertNotIn("PUSHOVER_API_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)


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
        self.assertNotIn("cron:", source)
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


class LocalDailyEvaluationRunnerTests(unittest.TestCase):
    def test_local_daily_outcome_runner_uses_only_read_protected_endpoints(self):
        source = (ROOT / "scripts" / "run_daily_outcome_evaluation.py").read_text()

        self.assertIn("/v31_evaluate_pending_outcomes", source)
        self.assertIn("/v31_evaluate_manual_reviews", source)
        self.assertIn("/v32_strategy_performance", source)
        self.assertIn("/v31_manual_review_learning", source)
        self.assertIn("/gpt_v31_daily_answer", source)
        self.assertIn("/outcomes", source)
        self.assertIn("/v32_decisions", source)
        self.assertIn("sync_local_outcomes", source)
        self.assertIn("SENSITIVE_KEY_FRAGMENTS", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("not_order_instruction", source)
        self.assertIn("execution_authorized", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("ibkr_bridge.py", source)

    def test_gpt_action_monitor_checks_ready_answer_endpoint(self):
        source = (ROOT / "scripts" / "monitor_gpt_action_health.py").read_text()

        self.assertIn("/gpt_v31_daily_answer", source)
        self.assertIn("/gpt_v31_daily_now", source)
        self.assertIn("daily_answer_ok", source)
        self.assertIn("daily_now_ok", source)
        self.assertIn("daily_answer_no_order_guardrail", source)
        self.assertIn("daily_now_no_order_guardrail", source)
        self.assertIn("DEFAULT_STATE_OUT", source)
        self.assertIn("--state-out", source)
        self.assertIn("duplicate_failure", source)
        self.assertIn("last_duplicate_failure", source)
        self.assertIn("SUPPRESSED_DUPLICATE_FAILURE", source)

    def test_operating_day_runner_orchestrates_bridge_outcomes_and_health_safely(self):
        source = OPERATING_DAY_RUNNER.read_text()

        self.assertIn("STOCK_ULTIMUS_OPERATING_DAY_RUNNER", source)
        self.assertIn("scripts/run_daily_radar.py", source)
        self.assertIn("scripts/run_daily_outcome_evaluation.py", source)
        self.assertIn("scripts/monitor_gpt_action_health.py", source)
        self.assertIn("/v31_manual_review_inbox", source)
        self.assertIn("/v31_manual_reviews_dashboard", source)
        self.assertIn("/v31_manual_review_learning_dashboard", source)
        self.assertIn("/v31_outcome_tracking_status", source)
        self.assertIn("uses_ingest_token", source)
        self.assertIn("touches_ibkr", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("send_resend_email", source)

    def test_daily_radar_builds_free_canslim_before_bridge(self):
        source = DAILY_RADAR_RUNNER.read_text()

        self.assertIn("build_canslim_free_candidates.py", source)
        self.assertIn("--skip-canslim", source)
        self.assertIn("--refresh-sec-canslim", source)
        self.assertIn("run_canslim_builder(args)", source)
        self.assertIn("ibkr_bridge.py", source)

        opening_source = (ROOT / "scripts" / "daily_open_checklist.py").read_text()
        self.assertIn('env.setdefault("IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED", "1")', opening_source)
        self.assertIn('env.setdefault("IBKR_INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES", "1")', opening_source)
        self.assertIn("ensure_conservative_premarket_context", opening_source)

        outcome_source = (ROOT / "scripts" / "run_daily_outcome_evaluation.py").read_text()
        self.assertIn('futures_endpoint = "/intraday_futures/evaluate_pending"', outcome_source)

    def test_operational_100_preflight_closes_five_gates_safely(self):
        source = OPERATIONAL_100_CHECK.read_text()

        self.assertIn("STOCK_ULTIMUS_OPERATIONAL_100_PREFLIGHT", source)
        self.assertIn("scripts/monitor_gpt_action_health.py", source)
        self.assertIn("tools/v31_daily_operational_audit.py", source)
        self.assertIn("scripts/run_daily_outcome_evaluation.py", source)
        self.assertIn("--dry-run", source)
        self.assertIn("--no-write", source)
        self.assertIn("--real-outcomes-after-close", source)
        self.assertIn("/v31_manual_review_inbox", source)
        self.assertIn("/v31_manual_reviews_dashboard", source)
        self.assertIn("/v31_manual_review_learning_dashboard", source)
        self.assertIn("/v32_strategy_performance_dashboard", source)
        self.assertIn("manual_review_required", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertIn('"uses_ingest_token": False', source)
        self.assertIn('"touches_ibkr": False', source)
        self.assertIn('"sends_email": False', source)
        self.assertIn('"secrets_printed": False', source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("ibkr_bridge.py", source)
        self.assertNotIn("send_resend_email", source)

    def test_daily_open_checklist_is_safe_operator_automation(self):
        source = DAILY_OPEN_CHECKLIST.read_text()
        bridge_source = BRIDGE.read_text()

        self.assertIn("STOCK_ULTIMUS_DAILY_OPEN_CHECKLIST", source)
        self.assertIn("/gpt_v32_operator_today", source)
        self.assertIn("/v32_operator_dashboard", source)
        self.assertIn("/v32_operator_events", source)
        self.assertIn("scripts/daily_open_checklist.py", str(DAILY_OPEN_CHECKLIST))
        self.assertIn("scripts/build_canslim_free_candidates.py", source)
        self.assertIn("canslim_step", source)
        self.assertIn("canslim_pre_bridge_step", source)
        self.assertIn("POST_IBKR_HISTORY_L_M", source)
        self.assertLess(source.index('report["canslim_pre_bridge_step"]'), source.index('report["refresh_step"] = refresh_bridge'))
        self.assertGreater(source.index('report["canslim_step"] = build_canslim_candidates(args)'), source.index('report["refresh_step"] = refresh_bridge'))
        self.assertIn("rsp_refresh_step", source)
        self.assertIn("--coberturas-rsp-weekly", source)
        self.assertIn("RSP_READY_FOR_MANUAL_REVIEW", source)
        self.assertIn("IBKR_DISABLE_INCREMENTAL_ENGINE_POSTS", source)
        self.assertIn("non_blocking", source)
        self.assertIn("ibkr_bridge.py", source)
        self.assertIn("tools/publish_v31_snapshot_from_runtime.py", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertIn("Decision support", source)
        self.assertNotIn("send_resend_email", source)
        self.assertNotIn("placeOrder", source)
        self.assertIn('priority_symbols = ["SPY", "QQQ"] + canslim_symbols', bridge_source)
        self.assertIn('"supports_canslim_l_and_m": True', bridge_source)
        self.assertIn("CANSLIM_HISTORICAL_MAX_SYMBOLS", bridge_source)
        self.assertNotIn(".place_order", source)

    def test_v32_nudge_preflight_check_is_safe_operator_helper(self):
        source = V32_NUDGE_PREFLIGHT_CHECK.read_text()

        self.assertIn("STOCK_ULTIMUS_V32_NUDGE_PREFLIGHT_CHECK", source)
        self.assertIn("/v32_operator_nudge_preflight", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("haz preflight de nudges", source)
        self.assertIn("first_business_day_checklist", source)
        self.assertIn("response_playbook", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertIn("Decision support", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("send_resend_email", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_v32_operator_notify_suppresses_wait_market_noise(self):
        source = V32_OPERATOR_NOTIFY.read_text()

        self.assertIn("V32_OPERATOR_NOTIFY", source)
        self.assertIn("/gpt_v32_operator_today", source)
        self.assertIn("WAIT_MARKET_SUPPRESSED", source)
        self.assertIn("ACTIONABLE_OPERATOR_ALERT", source)
        self.assertIn("manual_review_ready", source)
        self.assertIn("X-Stock-Ultimus-Read-Token", source)
        self.assertIn("macos_notification_center", source)
        self.assertIn("STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL", source)
        self.assertIn("--pushover", source)
        self.assertIn("PUSHOVER_USER_KEY", source)
        self.assertIn("PUSHOVER_API_TOKEN", source)
        self.assertIn("stock-ultimus-pushover-user-key", source)
        self.assertIn("stock-ultimus-pushover-api-token", source)
        self.assertIn("socket.timeout", source)
        self.assertIn("TIMEOUT:", source)
        self.assertIn("api.pushover.net", source)
        self.assertIn("--email-summary", source)
        self.assertIn("/v32_operator_daily_summary_email", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("send_resend_email", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("ibkr_bridge.py", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_pushover_channel_setup_is_secret_safe(self):
        source = PUSHOVER_CHANNEL_SETUP.read_text()

        self.assertIn("PUSHOVER_CHANNEL_PREFLIGHT", source)
        self.assertIn("PUSHOVER_USER_KEY", source)
        self.assertIn("PUSHOVER_API_TOKEN", source)
        self.assertIn("stock-ultimus-pushover-user-key", source)
        self.assertIn("stock-ultimus-pushover-api-token", source)
        self.assertIn("--configure", source)
        self.assertIn("getpass.getpass", source)
        self.assertIn("add-generic-password", source)
        self.assertIn("--send-test", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_v32_pushover_automation_is_local_read_only_and_time_gated(self):
        source = PUSHOVER_AUTOMATION.read_text()

        self.assertIn("V32_PUSHOVER_AUTOMATION", source)
        self.assertIn("market_monitor_window", source)
        self.assertIn("post_close_window", source)
        self.assertIn("scripts/v32_operator_notify.py", source)
        self.assertIn("scripts/run_daily_outcome_evaluation.py", source)
        self.assertIn("setup_pushover_channel.py", source)
        self.assertIn("POST_CLOSE_ALREADY_RAN_FOR_MARKET_DATE", source)
        self.assertIn("send_pushover_summary", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("ibkr_bridge.py", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_v32_pushover_launchd_installer_keeps_secrets_out_of_plists(self):
        source = PUSHOVER_LAUNCHD_INSTALLER.read_text()

        self.assertIn("V32_PUSHOVER_LAUNCHD_INSTALLER", source)
        self.assertIn("com.stockultimus.v32-pushover-monitor", source)
        self.assertIn("com.stockultimus.v32-pushover-postclose", source)
        self.assertIn("com.stockultimus.v32-pushover-preflight", source)
        self.assertIn("StartInterval", source)
        self.assertIn("StartCalendarInterval", source)
        self.assertIn("LaunchAgents", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("PUSHOVER_USER_KEY", source)
        self.assertNotIn("PUSHOVER_API_TOKEN", source)
        self.assertNotIn("READ_ACCESS_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_local_console_launchd_installer_is_local_and_secret_free(self):
        source = LOCAL_CONSOLE_LAUNCHD_INSTALLER.read_text()

        self.assertIn("STOCK_ULTIMUS_LOCAL_CONSOLE_LAUNCHD_INSTALLER", source)
        self.assertIn("com.stockultimus.local-console", source)
        self.assertIn("com.stockultimus.local-console-opener", source)
        self.assertIn("scripts/ibkr_account_profile.py", source)
        self.assertIn("serve --host 127.0.0.1", source)
        self.assertIn("Stock Ultimus Console.command", source)
        self.assertIn("--install-opener-fallback", source)
        self.assertIn('"/bin/zsh"', source)
        self.assertIn("/usr/bin/open", source)
        self.assertIn("/usr/sbin/lsof", source)
        self.assertIn("-iTCP:{port}", source)
        self.assertIn('"StartInterval": 60', source)
        self.assertIn("shlex.quote", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn('"RunAtLoad": True', source)
        self.assertIn('"KeepAlive": True', source)
        self.assertIn("LaunchAgents", source)
        self.assertIn("secrets_printed", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("READ_ACCESS_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("IBKR_ACCOUNT_ID", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_local_console_double_click_launcher_is_local_and_secret_free(self):
        source = LOCAL_CONSOLE_COMMAND.read_text()

        self.assertIn("install_stock_ultimus_console_launchd.py", source)
        self.assertIn("--replace-listener", source)
        self.assertIn("http://127.0.0.1:8765", source)
        self.assertIn("/usr/sbin/lsof", source)
        self.assertIn("-iTCP:8765", source)
        self.assertIn('exit 0', source)
        self.assertNotIn("ibkr_account_profile.py\" serve", source)
        self.assertNotIn("READ_ACCESS_TOKEN", source)
        self.assertNotIn("TRADING_ENGINE_INGEST_TOKEN", source)
        self.assertNotIn("SNAPSHOT_INGEST_TOKEN", source)
        self.assertNotIn("IBKR_ACCOUNT_ID", source)
        self.assertNotIn("placeOrder", source)
        self.assertNotIn(".place_order", source)

    def test_project_dashboard_is_served_under_v32_read_auth_prefix(self):
        source = APP.read_text()

        self.assertIn("/v32_project_dashboard", source)
        self.assertIn("/v32_project_command_center", source)
        self.assertIn("/v32_project_command_center_static", source)
        self.assertIn("/v32_operator_daily_summary", source)
        self.assertIn("/v32_operator_tracking_status", source)
        self.assertIn("/v32_operator_daily_summary_email", source)
        self.assertIn("/gpt_v32_operator_daily_cycle", source)
        self.assertIn("/v32_operator_pushover_notify", source)
        self.assertIn("/v32_operator_nudge", source)
        self.assertIn("/v32_operator_nudge_preflight", source)
        self.assertIn("/v32_actionable_signal_watch", source)
        self.assertIn("/v32_operational_edge", source)
        self.assertIn("/v32_operational_edge_dashboard", source)
        self.assertIn("project-dashboard.html", source)
        self.assertIn("project-command-center.html", source)
        self.assertIn("def _v32_project_dashboard_doc_html", source)
        self.assertIn("def _v32_project_command_center_live_html", source)
        self.assertIn("def _v32_operational_edge_payload", source)
        self.assertIn("shared_operational_edge.build_operational_edge_report", source)
        self.assertIn("def _v32_operator_daily_summary_payload", source)
        self.assertIn("def _v32_operator_daily_cycle_payload", source)
        self.assertIn("def _v32_operator_tracking_payload", source)
        self.assertIn("def _v32_operator_pushover_notify_payload", source)
        self.assertIn("def _v32_operator_nudge_preflight_payload", source)
        self.assertIn("def _v32_actionable_signal_watch_payload", source)
        self.assertIn('"/v32"', source)


if __name__ == "__main__":
    unittest.main()

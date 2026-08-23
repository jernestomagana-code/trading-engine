from pathlib import Path
import unittest


class TradingViewFastFuturesPineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pine = (
            Path(__file__).resolve().parents[1]
            / "tradingview"
            / "stock_ultimus_intraday_futures_fast_v2.pine"
        ).read_text()

    def test_fast_payload_contains_required_futures_context(self):
        string_fields = (
            "session_state",
            "major_event_window",
            "risk_daily_status",
        )
        numeric_fields = ("premarket_high", "premarket_low")
        for field in string_fields:
            self.assertIn(f'pair("{field}"', self.pine)
        for field in numeric_fields:
            self.assertIn(f'numpair("{field}"', self.pine)

    def test_fast_alert_emits_silent_session_heartbeat(self):
        self.assertIn('payload("SESSION_SNAPSHOT"', self.pine)
        self.assertIn('"_SESSION_SNAPSHOT_5M"', self.pine)
        self.assertIn("heartbeatEveryBars", self.pine)

    def test_fast_chart_exposes_decision_funnel_and_risk_plan(self):
        for stage in ("WAIT_QUALITY", "ARMED_LONG", "ARMED_SHORT", "TRIGGERED_LONG", "TRIGGERED_SHORT"):
            self.assertIn(stage, self.pine)
        for plot_name in ("VWAP", "ORH", "ORL", "PMH", "PML", "ENTRY", "STOP", "TARGET 1", "TARGET 2"):
            self.assertIn(f'"{plot_name}"', self.pine)
        self.assertIn("table.new(position.middle_right", self.pine)
        self.assertIn('"ACCIÓN AHORA"', self.pine)
        self.assertIn('"POR QUÉ"', self.pine)
        self.assertIn('"CONTEXTO 5m"', self.pine)
        self.assertIn('numpair("tp1_price"', self.pine)
        self.assertIn('numpair("tp2_price"', self.pine)
        self.assertIn('pair("direction"', self.pine)

    def test_fast_chart_suppresses_duplicate_entry_noise_with_cooldown(self):
        self.assertIn("entryCooldownBars", self.pine)
        self.assertIn("cooldownReady", self.pine)
        self.assertIn("lastEntryBar", self.pine)

    def test_fast_emits_low_priority_prepare_and_invalidation_evidence(self):
        for token in (
            "enablePrepareAlerts", "PREPARE_LONG_1M", "PREPARE_SHORT_1M",
            "SETUP_INVALIDATED_LONG_1M", "SETUP_INVALIDATED_SHORT_1M",
            'pair("alert_priority"', 'numpair("trigger_price"',
            'pair("missing_confirmations"', 'numpair("bars_armed"',
        ):
            self.assertIn(token, self.pine)

    def test_fast_panel_explains_exact_next_step(self):
        for label in ("PRÓXIMO GATILLO", "FALTA", "BARRAS PREPARANDO", "PLAN SI CONFIRMA", "NEXT TRIGGER"):
            self.assertIn(f'"{label}"', self.pine)
        for phrase in ("EVALUAR LONG AHORA", "EVALUAR SHORT AHORA", "PREPARAR LONG", "PREPARAR SHORT", "ALERTA = EVIDENCIA"):
            self.assertIn(f'"{phrase}', self.pine)


if __name__ == "__main__":
    unittest.main()

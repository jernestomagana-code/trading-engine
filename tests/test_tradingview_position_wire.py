"""Wire-compatibility checks; fixtures never enter the production ledger."""
import unittest
from tradingview_signal_ledger import normalize_signal_event


class ContextLevelsWireTest(unittest.TestCase):
    def payload(self, ticker, signal):
        vix = ticker == 'VIX'
        return dict(source='TRADINGVIEW', sensor_version='ultimus_context_levels_v2',
                    strategy_context='OPTIONS_UNDERLYING_CONFIRMATION',
                    ticker=ticker, timeframe='D' if vix else '15',
                    event_code=(signal+'_D') if vix else ticker+'_'+signal+'_15M',
                    event='VOLATILITY_RISK' if vix else 'REGIME_SNAPSHOT',
                    breakout_direction='NONE', underlying_signal=signal,
                    volatility_state='ELEVATED' if vix else 'UNKNOWN',
                    price=20 if vix else 700, adx=22, atr=2, rsi=54,
                    vwap=0 if vix else 699, volume_relative=0 if vix else 1.2,
                    support_20d=680, resistance_20d=720, previous_day_low=695,
                    previous_day_high=710, daily_atr=8, macd_histogram=-0.4,
                    technical_event='SUPPORT_BREAK_20D',
                    levels_basis='PRIOR_20_COMPLETED_RTH_DAILY_BARS',
                    source_timestamp='2026-10-15T19:45:00Z', bar_confirmed=True,
                    action='ALERT_ONLY', execution_authorized=False, not_order_instruction=True)

    def test_all_eight_wire_codes_accepted_without_order_authority(self):
        for ticker in ('QQQ','SPY','VIX','NFLX','TLT','RSP'):
            signals = ('VIX_RISK_ELEVATED','VIX_RISK_NORMALIZED') if ticker=='VIX' else ('TECH_CONFIRM_LONG','TECH_CONFIRM_SHORT','REGIME_SNAPSHOT')
            for signal in signals:
                with self.subTest(ticker=ticker,signal=signal):
                    p=self.payload(ticker,signal)
                    event=normalize_signal_event(p)
                    self.assertTrue(event['accepted_for_engine'],event['quarantine_reasons'])
                    self.assertFalse(event['execution_authorized'])
                    self.assertTrue(event['manual_review_required'])
                    self.assertEqual(event['raw_payload']['support_20d'],680)
                    self.assertEqual(event['raw_payload']['source_timestamp'],p['source_timestamp'])

    def test_unapproved_symbol_stays_quarantined(self):
        self.assertIn('UNKNOWN_EVENT_CODE',normalize_signal_event(self.payload('UNREGISTERED','REGIME_SNAPSHOT'))['quarantine_reasons'])

    def test_missing_real_volume_rejected_instead_of_invented(self):
        p=self.payload('QQQ','REGIME_SNAPSHOT')
        p['volume_relative']=None
        self.assertFalse(normalize_signal_event(p)['accepted_for_engine'])

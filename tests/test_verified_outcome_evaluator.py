import unittest
from copy import deepcopy
from datetime import datetime, timezone
from verified_outcome_evaluator import evaluate, checkpoint_at, instant

class VerifiedEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.entry=dict(contract_con_id=123, expiration='20261218',right='P',strike=700,multiplier=100,currency='USD',bid=2,ask=2.1,quote_timestamp='2026-11-06T15:00:00Z',capture_id='entry')
        self.row=dict(self.entry,bid=1,ask=1.1,quote_timestamp='2026-11-06T20:59:00Z',capture_id='close')
        self.out=dict(outcome='PENDING',outcome_id='one',strategy='NAKED_PUT',entry_ready_at='2026-11-06T15:00:30Z',selected_contract=self.entry,round_trip_commission=2,risk_basis_dollars=1000)
        self.now=instant('2026-11-06T21:01:00Z')
    def run_eval(self):return evaluate(self.out,[self.row],'EOD',self.now)
    def test_short_uses_bid_entry_ask_exit_fees_and_actual_risk(self):
        r=self.run_eval();self.assertEqual(r['status'],'EVALUATED');e=r['evaluation']
        self.assertEqual(e['net_pnl'],88);self.assertEqual(e['current_paper_pnl_r'],.088)
        self.assertNotIn('mfe_r',r['outcome']);self.assertEqual(r['outcome']['outcome'],'PENDING')
    def test_long_is_not_treated_as_sold_premium(self):
        self.out['strategy']='LONG_PUT';self.assertEqual(self.run_eval()['evaluation']['net_pnl'],-112)
    def test_idempotence(self):
        self.out=self.run_eval()['outcome'];self.assertEqual(self.run_eval()['reason'],'CHECKPOINT_ALREADY_EVALUATED')
    def test_missing_identity_never_matches(self):
        self.row.pop('right');self.assertEqual(self.run_eval()['reason'],'EXACT_CONTRACT_CHECKPOINT_QUOTE_MISSING')
    def test_stale_or_future_quote_cannot_measure_checkpoint(self):
        for stamp in ('2026-11-06T15:00:00Z','2026-11-06T21:01:00Z'):
            self.row['quote_timestamp']=stamp
            self.assertEqual(self.run_eval()['status'],'NOT_EVALUATED')
    def test_no_evaluation_before_due(self):
        self.now=instant('2026-11-06T20:00:00Z');self.assertEqual(self.run_eval()['reason'],'CHECKPOINT_NOT_DUE')
    def test_sessions_weekend_holiday_and_early_close(self):
        self.assertEqual(checkpoint_at(instant('2026-11-06T15:00:00Z'),'PLUS_1D'),instant('2026-11-09T21:00:00Z'))
        self.assertEqual(checkpoint_at(instant('2026-11-25T15:00:00Z'),'PLUS_1D'),instant('2026-11-27T18:00:00Z'))
    def test_unknown_fees_do_not_become_zero(self):
        self.out.pop('round_trip_commission');self.assertEqual(self.run_eval()['reason'],'ROUND_TRIP_COMMISSION_MISSING')
    def test_no_single_leg_proxy_for_covered_call_or_spread(self):
        for strategy in ('COVERED_CALL','IRON_CONDOR','BULL_PUT_SPREAD'):
            self.out['strategy']=strategy;self.assertEqual(self.run_eval()['reason'],'COMPLETE_STRATEGY_LEGS_REQUIRED')
    def test_missing_entry_capture_is_not_reconstructed(self):
        self.entry.pop('capture_id');self.assertEqual(self.run_eval()['reason'],'ENTRY_CAPTURE_EVIDENCE_MISSING')
    def test_no_r_without_risk_basis(self):
        self.out.pop('risk_basis_dollars');self.assertIsNone(self.run_eval()['evaluation']['current_paper_pnl_r'])
    def test_multileg_sides_and_quantity(self):
        second=dict(self.entry,contract_con_id=456,strike=695,bid=.5,ask=.6,side='BUY',quantity=1)
        self.out['legs']=[dict(self.entry,side='SELL',quantity=1),second]
        r=evaluate(self.out,[self.row,dict(second,bid=.2,ask=.3,quote_timestamp=self.row['quote_timestamp'],capture_id='close2')],'EOD',self.now)
        self.assertEqual(r['evaluation']['net_pnl'],48)

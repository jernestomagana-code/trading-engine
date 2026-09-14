import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from pathlib import Path
import tempfile
import console_market_calendar as calendar
import console_presentation as presentation
from scripts import ibkr_account_profile as console


class ConsoleAuditRegressions(unittest.TestCase):
    def test_holiday_and_early_close(self):
        for stamp in ('2026-09-07T15:00:00+00:00', '2026-11-27T18:00:00+00:00'):
            self.assertFalse(calendar.session(datetime.fromisoformat(stamp))['open'])
        self.assertTrue(calendar.session(datetime.fromisoformat('2026-11-27T17:59:00+00:00'))['open'])

    def test_winter_and_summer_use_new_york_time(self):
        self.assertFalse(calendar.session(datetime.fromisoformat('2026-12-01T14:00:00+00:00'))['open'])
        self.assertTrue(calendar.session(datetime.fromisoformat('2026-12-01T14:30:00+00:00'))['open'])
        self.assertTrue(calendar.session(datetime.fromisoformat('2026-09-08T13:30:00+00:00'))['open'])

    def test_next_open_skips_holiday(self):
        result = calendar.next_open(datetime.fromisoformat('2026-09-04T21:00:00+00:00'))
        self.assertEqual(result.isoformat(), '2026-09-08T13:30:00+00:00')

    def test_rsp_uses_only_its_own_funds(self):
        account = {'account_alias':'retiro', 'refresh_status':'READY', 'generated_at':console.now_iso(), 'capacity':{'available_funds':4000, 'buying_power':16000}}
        rsp = {'strategy_recommendation':{'status':'RECOMMEND_ENTRY', 'capital_required':5000}}
        with patch.object(console,'active_control_tower_account',return_value=account):
            rows=console.build_unified_opportunity_items({},rsp,{},risk_payload={},account_capacity={'available_capacity':20000,'account_alias':'primary'},premium_payload={})
        row=next(r for r in rows if r['type']=='rsp')
        self.assertEqual(row['available_capacity_label'],'$4,000.00')
        self.assertEqual(row['state'],'blocked')
        self.assertFalse(row['simulator_available'])
        self.assertIn('retiro',row['capacity_context'])

    def test_rsp_missing_or_stale_funds_do_not_borrow_capacity(self):
        for account in ({}, {'refresh_status':'READY','generated_at':'2020-01-01T00:00:00Z','capacity':{'available_funds':999999}}):
            with patch.object(console,'active_control_tower_account',return_value=account):
                self.assertIsNone(console.rsp_account_capacity()['available_capacity'])

    def test_review_and_plan_are_separate(self):
        row={'management_action':'REVIEW_RISK','management_alternatives':{'recommendation':{'label':'Mantener y monitorear'}}}
        result=console.position_action_queue_metadata(row)
        self.assertEqual(result['label'],'Revisar ahora')
        self.assertEqual(result['plan'],'Mantener y monitorear')

    def test_missing_data_is_not_an_exit_instruction(self):
        row={'management_action':'REFRESH_DATA','blockers':['MISSING_DATA']}
        self.assertEqual(console.position_action_queue_metadata(row)['key'],'data')

    def test_same_ticker_different_account_has_different_target(self):
        a={'ticker':'TEST','position_id':'1','account_alias':'one'}
        b={**a,'account_alias':'two'}
        self.assertNotEqual(presentation.position_anchor(a),presentation.position_anchor(b))

    def test_yesterdays_done_task_reappears_and_can_be_reopened(self):
        task={'area':'Posiciones','title':'TEST','detail':'Revisar','href':'#posiciones','level':'high','when':'Resolver ahora'}
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, patch.object(console,'DAILY_TASK_JOURNAL_PATH',Path(tmp)/'journal.json'):
            row=console.daily_task_view([task],now=now)['visible'][0]
            console.record_daily_task_action(row['task_id'],row['task_fingerprint'],'DONE')
            self.assertEqual(console.daily_task_view([task])['attended_count'],1)
            self.assertEqual(len(console.daily_task_view([task],now=now+timedelta(days=1))['visible']),1)
            console.record_daily_task_action(row['task_id'],row['task_fingerprint'],'REOPEN')
            self.assertEqual(len(console.daily_task_view([task])['visible']),1)

    def test_historical_outcome_never_closes_unlinked_current_position(self):
        with patch.object(console,'json_rows',side_effect=[[],[{'ticker':'TEST','status':'COMPLETE','recorded_at':'2020-01-01T00:00:00Z'}]]), patch.object(console,'load_operator_events',return_value=[]):
            rows=console.build_trade_casefiles({'positions':[{'ticker':'TEST','position_id':'current','management_action':'HOLD'}]})
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['phase'],'open')
        self.assertIn('Pendiente de cierre',rows[0]['outcome'])
        self.assertFalse(rows[0]['linked'])

    def test_explicit_account_and_trade_cycle_link(self):
        identity={'ticker':'TEST','account_alias':'retiro','trade_id':'trade-1'}
        with patch.object(console,'json_rows',side_effect=[[{**identity,'final_state':'ENTRY_READY'}],[]]), patch.object(console,'load_operator_events',return_value=[]):
            rows=console.build_trade_casefiles({'positions':[{**identity,'management_action':'HOLD'}]})
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['linked'])

    def test_historical_trade_in_other_account_is_not_linked(self):
        with patch.object(console,'json_rows',side_effect=[[{'ticker':'TEST','account_alias':'one','trade_id':'1'}],[]]), patch.object(console,'load_operator_events',return_value=[]):
            rows=console.build_trade_casefiles({'positions':[{'ticker':'TEST','account_alias':'two','trade_id':'1'}]})
        self.assertEqual(len(rows),2)
        self.assertFalse(any(r['linked'] for r in rows))


    def test_rsp_capacity_wait_is_blocked_even_without_blocker_list(self):
        for status in ('WAIT_ACCOUNT_CAPACITY','WAIT_MARGIN_PREVIEW','WAIT_CAPITAL_DATA'):
            with patch.object(console,'active_control_tower_account',return_value={}):
                rows=console.build_unified_opportunity_items({}, {'strategy_recommendation':{'status':status}}, {}, risk_payload={},account_capacity={},premium_payload={})
            self.assertEqual(next(row for row in rows if row['type']=='rsp')['state'],'blocked')

    def test_rsp_saved_data_is_not_labelled_current_and_shares_are_managed(self):
        page=console.render_coberturas_inline_panel({'generated_at':'2020-01-01T00:00:00Z','position':{'state':'WITH_SHARES'},'ibkr':{'chain_has_rsp':True},'position_manager':{'status':'READY_FOR_COVERED_CALL_MANAGEMENT','primary_action':'Prioritize covered call management over naked put entry.'}})
        self.assertNotIn('cuenta retiro actualizada',page)
        self.assertNotIn('Prioritize covered',page)
        self.assertIn('Disponible; revisar vigencia',page)
        self.assertIn('Acciones en cartera',page)
        self.assertIn('RSP gestiona la posición abierta',page)

    def test_management_followup_never_falls_back_to_ticker(self):
        journal=console.shared_position_management_journal
        event={'position_id':'old','ticker':'TEST','account_alias':'retiro'}
        for positions in ([{'position_id':'new','ticker':'TEST','account_alias':'retiro'}],
                          [{'position_id':'old','ticker':'TEST','account_alias':'other'}],
                          [{'position_id':'old','ticker':'TEST','account_alias':'retiro'}]*2):
            with patch.object(journal,'load_journal',return_value={'events':[event]}):
                result=journal.evaluate_against_management({'positions':positions})
            self.assertFalse(result['evaluated_events'][0]['current_position_found'])
        with patch.object(journal,'load_journal',return_value={'events':[event]}):
            result=journal.evaluate_against_management({'positions':[event]})
        self.assertTrue(result['evaluated_events'][0]['current_position_found'])

    def test_casefile_explains_missing_cycle_without_relabelling_position_id(self):
        with patch.object(console,'json_rows',return_value=[]), patch.object(console,'load_operator_events',return_value=[]):
            rows=console.build_trade_casefiles({'positions':[{'ticker':'TEST','account_alias':'retiro','position_id':'position-only'}]})
            page=console.render_trade_casefiles({'positions':[{'ticker':'TEST','account_alias':'retiro','position_id':'position-only'}]})
        self.assertEqual(rows[0]['cycle'],'Sin ciclo identificado')
        self.assertIn('identificador de posición no lo sustituye',rows[0]['linkage_detail'])
        self.assertIn('data-case-linked="no"',page)
        self.assertIn('Vínculos incompletos',page)
        self.assertIn('<option value="open" selected>Posiciones actuales</option>', page)


    def test_review_acknowledgment_cannot_hide_other_account_or_ambiguous_id(self):
        journal=console.shared_position_management_journal
        position={'position_id':'same','ticker':'TEST','account_alias':'retiro','management_action':'HOLD','exit_state':'MONITOR'}
        event={'position_id':'same','account_alias':'retiro','operator_action':'REVIEW_COMPLETED','recommended_action':'HOLD','recommended_state':'MONITOR','recorded_at':console.now_iso(),'management_fingerprint':journal.management_fingerprint(position)}
        other={**position,'account_alias':'remanente'}
        self.assertNotEqual(journal.management_fingerprint(position),journal.management_fingerprint(other))
        with patch.object(journal,'load_journal',return_value={'events':[event]}):
            self.assertIn('same',journal.acknowledged_position_reviews({'positions':[position]}))
            self.assertEqual(journal.acknowledged_position_reviews({'positions':[other]}),{})
            self.assertEqual(journal.acknowledged_position_reviews({'positions':[position,other]}),{})

    def test_recent_activity_includes_alerts_and_type_filter(self):
        with patch.object(console, 'load_daily_task_journal', return_value={'tasks': {}}), \
             patch.object(console.shared_position_management_journal, 'load_journal', return_value={'events': []}), \
             patch.object(console, 'load_operator_events', return_value=[{'ticker': 'TEST', 'action': 'ACK_ALERT', 'recorded_at': console.now_iso()}]):
            page = console.render_recent_activity()
        self.assertIn('data-activity-type="alert"', page)
        self.assertIn('Alerta marcada como vista', page)
        self.assertIn('id="activity-type"', page)
        self.assertIn('value="data">Datos', page)
        self.assertIn('value="signal">Señales vencidas', page)

    def test_mobile_activity_actions_have_touch_target_and_primary_nav_is_unique(self):
        page = console.render_web_page({})
        if isinstance(page, bytes):
            page = page.decode("utf-8")
        self.assertIn('#recent-activity > button { min-height:44px; }', page)
        self.assertEqual(page.count('data-console-view-link="cartera"'), 1)

    def test_research_summary_hides_internal_state_codes(self):
        payload = {
            'summary': {},
            'strategies': {
                'CANSLIM_EARNINGS_VOLATILITY_HARVEST': {'data_state': 'DATA_COLLECTION_REQUIRED'},
                'SPY_RSP_LONG_DATED_PUTWRITE': {'data_state': 'RESEARCH_ONLY'},
            },
        }
        with patch.object(console, 'load_json_file', return_value=payload):
            page = console.render_premium_strategy_research_summary()
        self.assertIn('Recopilación de datos en curso', page)
        self.assertIn('Sólo investigación', page)
        self.assertIn('evaluación simulada', page)
        self.assertNotIn('DATA_COLLECTION_REQUIRED', page)
        self.assertNotIn('PAPER_ELIGIBLE', page)

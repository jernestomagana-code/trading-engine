from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
import futures_market_calendar as calendar
import futures_live_quotes as quotes


class FuturesCalendarTests(unittest.TestCase):
    def schedule(self, stamp, hours, zone='US/Central'):
        return {'contract':'MNQU2026', 'observed_at':stamp, 'trading_hours':hours, 'timezone':zone}

    def test_overnight_session_and_exact_close(self):
        hours='20260908:1700-20260909:1600;20260909:1700-20260910:1600'
        for stamp,state in [('2026-09-09T02:00:00+00:00','OPEN'),('2026-09-09T21:00:00+00:00','CLOSED'),('2026-09-09T22:00:00+00:00','OPEN')]:
            self.assertEqual(calendar.session(self.schedule(stamp,hours),datetime.fromisoformat(stamp))['state'],state)

    def test_explicit_holiday_and_uncovered_day(self):
        stamp='2026-09-07T15:00:00+00:00'
        for hours,state in [('20260907:CLOSED','CLOSED'),('20260908:CLOSED','UNKNOWN')]:
            self.assertEqual(calendar.session(self.schedule(stamp,hours),datetime.fromisoformat(stamp))['state'],state)

    def test_bad_missing_stale_and_future_evidence_stays_unknown(self):
        stamp='2026-09-09T15:00:00+00:00';now=datetime.fromisoformat(stamp)
        for data in [None,{},self.schedule(stamp,'20260909:0930-1600'),self.schedule(stamp,'broken'),self.schedule(stamp,'20260909:CLOSED','CST'),self.schedule((now-timedelta(minutes=31)).isoformat(),'20260909:CLOSED'),self.schedule((now+timedelta(minutes=1)).isoformat(),'20260909:CLOSED')]:
            self.assertEqual(calendar.session(data,now)['state'],'UNKNOWN')

    def test_winter_and_summer_offsets(self):
        for stamp,hours in [('2026-12-09T22:00:00+00:00','20261209:0900-20261209:1600'),('2026-09-09T21:00:00+00:00','20260909:0900-20260909:1600')]:
            self.assertEqual(calendar.session(self.schedule(stamp,hours),datetime.fromisoformat(stamp))['state'],'CLOSED')

    def test_schedule_is_available_without_live_prices_and_contracts_do_not_mix(self):
        from datetime import timezone
        stamp=datetime.now(timezone.utc).isoformat()
        event={'ticker':'MNQ1!', 'current_contract':'MNQU2026','state':'ENTRY_READY','received_at':stamp}
        for contract,expected in [('MNQU2026',True),('MESU2026',False)]:
            schedule={**self.schedule(stamp,'20260909:CLOSED'),'contract':contract}
            with patch.dict(quotes._cache,{'MNQ1!|MNQU2026':(quotes.time.monotonic(),{'quote_status':'LIVE_DATA_UNAVAILABLE','contract_schedule':schedule})},clear=True):
                self.assertEqual('contract_schedule' in quotes.enrich_event(event),expected)

    def test_live_quote_cannot_reintroduce_wrong_contract_schedule(self):
        from datetime import timezone
        stamp=datetime.now(timezone.utc).isoformat()
        event={'ticker':'MNQ1!', 'current_contract':'MNQU2026','state':'ENTRY_READY','received_at':stamp}
        quote={'quote_status':'LIVE','bid':100,'ask':101,'contract_schedule':{'contract':'MESU2026'}}
        with patch.dict(quotes._cache,{'MNQ1!|MNQU2026':(quotes.time.monotonic(),quote)},clear=True):
            self.assertNotIn('contract_schedule',quotes.enrich_event(event))

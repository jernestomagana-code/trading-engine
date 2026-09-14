"""Presentation of explicit IBKR contract schedules; never an entry gate.
https://interactivebrokers.github.io/tws-api/classIBApi_1_1ContractDetails.html
Only date-qualified intervals are accepted; legacy ambiguous hours stay unknown.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def session(schedule, now=None):
    unknown = {'state': 'UNKNOWN', 'label': 'Horario sin confirmar; revisar contrato en TWS'}
    if not isinstance(schedule, dict):
        return unknown
    current = now or datetime.now(timezone.utc)
    try:
        observed = datetime.fromisoformat(schedule['observed_at'].replace('Z', '+00:00'))
        if observed.tzinfo is None or current.tzinfo is None or not 0 <= (current-observed).total_seconds() <= 1800:
            return unknown
        # Do not interpret ambiguous abbreviations such as CST as a fixed offset.
        zone_name = schedule['timezone']
        if zone_name not in {'America/Chicago', 'US/Central', 'America/New_York', 'US/Eastern', 'UTC'}:
            return unknown
        zone = ZoneInfo(zone_name)
        local = current.astimezone(zone)
        intervals, closed_days = [], set()
        for entry in schedule['trading_hours'].split(';'):
            if not entry:
                continue
            if entry.endswith(':CLOSED'):
                closed_days.add(datetime.strptime(entry[:-7], '%Y%m%d').date())
                continue
            for segment in entry.split(','):
                start, end = segment.split('-')
                start = datetime.strptime(start, '%Y%m%d:%H%M').replace(tzinfo=zone)
                end = datetime.strptime(end, '%Y%m%d:%H%M').replace(tzinfo=zone)
                if end <= start:
                    return unknown
                intervals.append((start, end))
        for start, end in intervals:
            if start <= local < end:
                return {'state': 'OPEN', 'label': 'Abierto según horario IBKR · hasta ' + end.astimezone(ZoneInfo('America/Mexico_City')).strftime('%d/%m %H:%M CDMX')}
        # Outside a supplied day's coverage cannot be inferred to be closed.
        covered = local.date() in closed_days or any(start.date() <= local.date() <= end.date() for start, end in intervals)
        if not covered:
            return unknown
        return {'state': 'CLOSED', 'label': 'Cerrado según horario IBKR; revisar próxima sesión en TWS'}
    except (KeyError, ValueError, TypeError, AttributeError):
        return unknown

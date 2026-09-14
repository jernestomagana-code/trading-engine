"""Read-only inventory of evidence needed to finish UX validation.
Prints aggregates only; never rewrites journals or infers execution links.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path, key):
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return [], 'missing'
    except (OSError, ValueError):
        return [], 'unreadable'
    rows = payload if isinstance(payload, list) else payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], 'unexpected_schema'
    return [row for row in rows if isinstance(row, dict)], 'read'


def inventory(runtime):
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'journals': {}}
    for name, key in [('v32_decision_journal.json', 'decisions'), ('v32_outcomes_journal.json', 'outcomes')]:
        rows, status = read_rows(runtime/name, key)
        result['journals'][key] = {
            'read_status': status, 'records': len(rows),
            'missing_account': sum(not (r.get('account_alias') or r.get('account_scope')) for r in rows),
            'missing_trade_cycle': sum(not (r.get('trade_id') or r.get('trade_cycle_id')) for r in rows),
            'with_signal_reference': sum(bool(r.get('signal_id')) for r in rows),
        }
    rows, status = read_rows(runtime/'console_usage_validation.json', 'events')
    counts = Counter(r.get('event') for r in rows)
    result['usage'] = {'read_status': status, 'sessions': len({r['session_id'] for r in rows if r.get('session_id')}),
                       'actions_confirmed': counts['TASK_COMPLETED'], 'action_errors': counts['TASK_FAILED']}
    result['limits'] = [
        'Only top-level account and trade-cycle fields are counted; missing fields do not prove that no other evidence exists.',
        'Signal references identify recommendations, not broker executions or account ownership.',
        'Session and action counts do not measure comprehension or task completion observed by a researcher.',
    ]
    return result


if __name__ == '__main__':
    print(json.dumps(inventory(ROOT/'runtime'), ensure_ascii=False, indent=2))

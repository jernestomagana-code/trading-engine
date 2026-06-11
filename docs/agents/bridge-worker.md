# Bridge Worker Brief

## Mission

Update the local IBKR bridge so option candidates publish executable contract fields required by V30.

## Expected Write Scope

- `ibkr_bridge.py`
- narrowly related bridge-side helpers or tests, if they already exist

## Required Option Fields

- `strike`
- `expiration`
- `dte`
- `bid`
- `ask`
- `mid`
- `spread`
- `spread_pct`
- `delta`

## Implementation Guidance

- Prefer existing snapshot and candidate structures.
- Use `ib_insync` market data and option contract objects already present in the codebase.
- Keep numeric fields JSON-serializable.
- Treat missing, stale, NaN, or non-positive bid/ask/mid quote data as incomplete executable data.
- Do not submit orders or add automatic execution.

## Output

Return:

- files changed,
- snapshot fields added,
- incomplete-data behavior,
- tests or fixture checks run.

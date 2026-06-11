# V30 Decision Contract

## Required Executable Option Data

An option candidate is executable-data-complete only when all fields below are present and valid:

```json
{
  "strike": 100.0,
  "expiration": "2026-07-17",
  "dte": 39,
  "bid": 1.2,
  "ask": 1.35,
  "mid": 1.275,
  "spread": 0.15,
  "spread_pct": 11.76,
  "delta": -0.28
}
```

## Suggested Validity Rules

- `strike` must be positive.
- `expiration` must be a parseable date.
- `dte` must be non-negative.
- `bid` must be greater than zero.
- `ask` must be greater than zero.
- `ask` must be greater than or equal to `bid`.
- `mid` must be greater than zero.
- `spread` must be greater than or equal to zero.
- `spread_pct` must be greater than or equal to zero.
- `delta` must be present and numeric.

For Naked Put candidates, delta is normally expected to be negative.

For Covered Call candidates, delta is normally expected to be positive.

## Blocker Priority

Recommended priority from highest to lower:

1. system or data ingestion failure
2. missing account/position context
3. `WAIT_OPTIONS_DATA`
4. risk blocker
5. manual review blocker
6. `WAIT_TECHNICAL`
7. `ENTRY_READY`

This priority should be adjusted only if the existing code has a stronger explicit convention.

When technical and executable option data are complete but the system still requires human inspection, the state should remain blocked by manual review instead of becoming `ENTRY_READY`.

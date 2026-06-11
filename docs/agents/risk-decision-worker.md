# Risk And Decision Worker Brief

## Mission

Enforce V30 readiness and blocker priority.

## Expected Write Scope

- decision/risk modules if they exist
- `app/main.py` only if decision logic currently lives there
- tests or fixtures related to decision state

## Decision Rules

`ENTRY_READY` requires:

- confirmed technical signal,
- complete executable option fields,
- passing risk rules,
- no manual-review blocker.

`WAIT_OPTIONS_DATA` must apply when:

- technical signal is confirmed,
- candidate intent exists,
- but any required executable option field is missing or invalid.

`WAIT_TECHNICAL` should apply when:

- technical confirmation is missing or failed,
- and no higher-priority blocker is present.

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

## Output

Return:

- files changed,
- blocker priority table,
- readiness gate behavior,
- tests or fixture checks run.

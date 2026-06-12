# V30 Acceptance Checklist

## Snapshot Contract

- [x] Master snapshot includes `strike`.
- [x] Master snapshot includes `expiration`.
- [x] Master snapshot includes `dte`.
- [x] Master snapshot includes `bid`.
- [x] Master snapshot includes `ask`.
- [x] Master snapshot includes `mid`.
- [x] Master snapshot includes `spread`.
- [x] Master snapshot includes `spread_pct`.
- [x] Master snapshot includes `delta`.
- [x] Fields are JSON-serializable.
- [x] Missing or invalid quote/Greek values are represented explicitly enough for blocker logic.

## Decision Logic

- [x] Confirmed technical signal plus missing executable option data returns `WAIT_OPTIONS_DATA`.
- [x] Confirmed technical signal plus partial executable option data returns `WAIT_OPTIONS_DATA`.
- [x] Missing technical confirmation returns `WAIT_TECHNICAL` when no higher-priority blocker exists.
- [x] Complete option data plus passing risk can return `ENTRY_READY`.
- [x] Risk failure blocks `ENTRY_READY`.
- [x] No automatic IBKR order submission is introduced.

## Cloud/API

- [x] Render snapshot POST accepts V30 fields.
- [x] Runtime JSON persistence preserves V30 fields.
- [x] GPT-facing ticker decision endpoint exposes V30 fields and blocker state.
- [x] Dashboard matches API state.
- [x] Older snapshots do not crash the cloud app.

## QA

- [x] Fixture covers no option data.
- [x] Fixture covers partial option data.
- [x] Fixture covers complete option data.
- [x] Fixture covers risk failure.
- [x] Fixture covers `ENTRY_READY`.
- [x] Tests or script checks are documented.
- [x] Sanitized runtime snapshot covers multi-ticker cloud decision states.
- [x] Runtime fixture privacy guard blocks obvious sensitive data leaks.

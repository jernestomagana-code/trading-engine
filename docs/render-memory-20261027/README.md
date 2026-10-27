# Render memory mitigation · 27 October 2026

The production Render service is `trading-engine`; its health probe is `/health`. The prior implementation read complete local signal/event histories and calculated TradingView readiness even though it advertised local liveness. The fix makes the probe independent of history size and returns an explicit `NOT_EVALUATED_ON_LIVENESS` readiness state. Detailed authenticated diagnostic routes, trading rules, event retention, plan, workers, credentials and schedules are unchanged.

The probe now reports bounded OS memory observations: process RSS/peak RSS and cgroup v2 current/limit bytes. Container usage includes file cache and is a different scope from process RSS. Missing/unsupported measurements remain null. This is diagnostic information, not a health guarantee or a reason to change the plan automatically.

## Verification

- 711 local tests passed; GitHub CI passed on the initial patch.
- Native FastAPI/Uvicorn HTTP smoke test on Python 3.11.15: `/health` returned 200, a private ledger route without a token returned 401. Local-only test; production startup reconciliation was disabled only in this temporary test process.
- Synthetic function-level allocation comparison: 20,000 events (25,117,781 JSON bytes) and 10,000 signals (10,690,001 JSON bytes), with identical fixtures in separate processes. Peak traced Python allocations changed from 68,632,583 bytes to 20,174 bytes. Elapsed times were 0.3446s and 0.0016s on this machine. This measures the handler's allocations, not production RSS, framework concurrency or Render's actual instance.
- The allocation benchmark imports the repository's contract-test module (API stubs) and executes the actual old/new handler bodies; the separate HTTP smoke test verifies the real framework. Do not equate either measurement with the Render memory graph.
- Public production health before deployment: HTTP 200, 0.299s. Private Render events/logs/graphs were not yet accessible because the dashboard required the existing login. The specific OOM incident's cause remains unproven until those records can be reviewed.

`measure_health.py baseline` and `measure_health.py patched` reproduce the allocation comparison in separate processes using the original `f50e2d6` handler. All fixture contents are synthetic; no events were sent to production. The JSON evidence and tests log are included beside this file.

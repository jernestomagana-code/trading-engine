# Stock Ultimus World-Class Console Audit

Audit date: 2026-09-05.

## Executive conclusion

Stock Ultimus is operationally usable as a single-operator decision-support
console. Its code, local services, security controls, dependencies, storage,
navigation, daily workflow, opportunity lanes, position management, Focus Mode,
and audit trail passed the closed-market review.

It would be inaccurate to call the product fully institution-grade yet. The
remaining gap is primarily live evidence and exact transaction lineage, not a
broken console.

## Passed

- 670 automated tests.
- Security audit and dependency audit.
- Published-environment audit: 26/26 checks passed, protected access enforced,
  health routes responsive, and the current 280-row snapshot reported fresh.
- Eight expected local services installed.
- Runtime file freshness and disk-capacity checks.
- Five-alert TradingView production architecture; futures real end-to-end
  evidence and zero quarantined events.
- Automated opening-cycle evidence, operator Focus Mode, trade casefiles, and
  privacy-minimal local usage telemetry.
- Premium-strategy research lanes for earnings-volatility and long-dated
  SPY/RSP puts, correctly blocked from recommendation until their data gates
  are satisfied.

## Expected closed-market warnings

- TWS/IBKR is not connected and option chains are incomplete while the market
  is closed.
- Some options event types have not occurred naturally yet.
- Premium strategies remain in `DATA_COLLECTION_REQUIRED`.

These are not code failures.

## Remaining evidence gates

1. Complete 5–10 real operator sessions to validate discoverability and daily
   workflow. Current sample: 1 session.
2. Accumulate at least 30 complete closed outcomes per strategy before changing
   thresholds from historical performance. Current complete sample: 0.
3. Observe the remaining natural options-underlying event types end to end.
4. Populate expired-option history and the liquid long-dated SPY/RSP grid before
   promoting either premium strategy from research to live recommendation.

## Institutional upgrades, if the product will serve third parties

1. Replace ticker-level trade casefiles with immutable trade identifiers tied
   to IBKR contract, order, execution, fill, and lot identifiers. This prevents
   two trades in the same ticker from being merged conceptually.
2. Add an automated backup-and-restore drill and a secondary health monitor so
   the Mac/TWS path is not a silent single point of failure.
3. Add named users, roles, and an immutable operator-action log before allowing
   multiple clients or operators.

These upgrades are not required for the current single-user decision-support
workflow, but they are required before claiming institutional or multi-client
readiness.

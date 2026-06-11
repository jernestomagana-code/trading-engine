# Stock Ultimus Product Vision

## North Star

Stock Ultimus should become an auditable trading decision operating system for
options. It should help a user identify, validate, explain, and monitor trading
opportunities, while preserving human control over final execution.

The goal is not to build an uncontrolled auto-trader. The goal is to build a
decision platform strong enough to support personal use first and potential
commercial use later.

## Core Thesis

The system becomes more powerful when it becomes:

- more data-complete,
- more conservative about blockers,
- more explainable by ticker,
- more measurable after the fact,
- more modular by strategy,
- more auditable by snapshot and ruleset version,
- more robust for user/account isolation,
- and more honest about risk.

It should not become more powerful by hiding uncertainty or expanding
`ENTRY_READY` too easily.

## Product Pillars

1. Data Quality First

   No strategy can outrank missing executable data. For option candidates, the
   contract must include the required executable fields before readiness.

2. Deterministic Readiness

   GPT can explain and challenge a decision, but deterministic code owns the
   blocker and readiness state.

3. Human Final Control

   `ENTRY_READY` means ready for manual validation, not permission to place a
   live order.

4. Auditability

   A future user should be able to reconstruct why a ticker was classified as
   `WAIT_OPTIONS_DATA`, `WAIT_TECHNICAL`, `RISK_BLOCKED`, or `ENTRY_READY`.

5. Strategy Modularity

   Strategies should be independent modules with testable inputs, outputs,
   blockers, and risk gates.

6. Learning Without Hidden Autonomy

   The system should track outcomes and propose parameter improvements, but
   parameter changes should be reviewed, versioned, and tested.

7. Commercial Readiness Before Commercial Claims

   Selling the system to others requires user/account isolation, disclosures,
   audit logs, security controls, legal/compliance review, and careful product
   positioning as analytics or decision support.

## Target Architecture

- Data layer: IBKR, TradingView, account, positions, market session, events,
  volatility, liquidity, and future data providers.
- Normalization layer: versioned snapshot contracts and stable JSON schemas.
- Strategy layer: Naked Put, Covered Call, Iron Condor, position management,
  and future research-approved strategies.
- Risk layer: capital, margin, concentration, assignment risk, event risk,
  liquidity, spread, delta exposure, and profile-level limits.
- Decision layer: canonical blocker priority and one readiness source of truth.
- Explanation layer: GPT-facing and dashboard-facing rationale from the same
  decision payload.
- Learning layer: signal history, trade outcomes, missed opportunities,
  forward-test metrics, and parameter review.
- Governance layer: audit logs, ruleset versions, user isolation, disclosures,
  permissions, and commercial review.
- Security layer: secrets management, endpoint authentication, access control,
  safe logging, dependency review, runtime-data protection, and tenant isolation.

## Commercial Boundary

Until reviewed by qualified legal/compliance counsel, Stock Ultimus should avoid
claims that it manages money, guarantees returns, provides personalized
investment advice to third parties, or safely auto-trades customer accounts.

Commercial language should emphasize analytics, decision support, risk
visibility, educational workflow, and manual validation.

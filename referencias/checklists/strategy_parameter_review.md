# Strategy Parameter Review Checklist

Use this checklist before changing strategy thresholds.

## Contract Execution Data

- [ ] `strike` present and valid.
- [ ] `expiration` present and parseable.
- [ ] `dte` present and inside configured range.
- [ ] `bid` and `ask` present and positive.
- [ ] `mid` present and positive.
- [ ] `spread` present and non-negative.
- [ ] `spread_pct` present and within threshold.
- [ ] `delta` present and strategy-appropriate.
- [ ] `volume` and `open_interest` reviewed when available.

## Naked Put

- [ ] Put is OTM.
- [ ] Delta range remains appropriate for risk target.
- [ ] Premium justifies assignment and tail risk.
- [ ] Underlying is acceptable to own if assigned.
- [ ] Earnings/event risk is reviewed.
- [ ] Capital/margin impact is reviewed.

## Covered Call

- [ ] Call is OTM or intentionally managed.
- [ ] Delta range matches income/upside tradeoff.
- [ ] Position exists and share count is sufficient.
- [ ] Assignment outcome is acceptable.
- [ ] Earnings/event risk is reviewed.
- [ ] Liquidity is acceptable.

## Decision Integrity

- [ ] Incomplete option data returns `WAIT_OPTIONS_DATA`.
- [ ] Missing technical confirmation returns `WAIT_TECHNICAL` only after option data is executable.
- [ ] `ENTRY_READY` remains manual-validation only.
- [ ] GPT endpoint and dashboard agree.

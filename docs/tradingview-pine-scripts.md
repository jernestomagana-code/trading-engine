# TradingView Pine Scripts

These scripts generate Stock Ultimus-compatible JSON alerts for
`/technical_snapshot`. They are decision-support inputs only and never authorize
orders.

## Recommended Pro Scripts

`tradingview/stock_ultimus_options_signal_pro_v2.pine`

Recommended first upload for:

- `NAKED_PUT`
- `CASH_SECURED_PUT`
- `COVERED_CALL`
- `IRON_CONDOR`

It adds multi-timeframe trend, SPY/QQQ market regime, VIX context, ATR risk,
VWAP, range state, support/resistance proximity, relative volume, manual IV
rank, event/earnings caps, and optional CANSLIM filter fields.

`tradingview/stock_ultimus_futures_signal_pro_v2.pine`

Recommended first upload for:

- `FUTURES`
- `MNQ`
- `NQ`
- `MES`
- `ES`

It adds session gating, opening range breakout, higher-timeframe alignment,
EMA/VWAP direction, ADX, RSI, ATR-normalized VWAP distance, relative volume, and
macro/news blackout support.

Set `Stock Ultimus ticker` to the IBKR symbol used by the engine. For example,
when the TradingView chart is `USTEC.F`, use `MNQ` or `NQ` as the canonical
ticker. The payload preserves the original chart symbol as `chart_ticker`.

`tradingview/stock_ultimus_canslim_filter_pro_v2.pine`

Recommended first upload for CANSLIM. It keeps fundamental inputs manual where
TradingView data is unreliable, but adds market direction and relative strength
ratio against a market proxy.

## Legacy V1 Templates

The V1 scripts are kept as simpler fallback templates. Prefer the Pro V2 scripts
for new TradingView uploads.

`tradingview/stock_ultimus_options_signal_v1.pine`

Use this for:

- `NAKED_PUT`
- `CASH_SECURED_PUT`
- `COVERED_CALL`
- `IRON_CONDOR`

It computes RSI, ADX, range state, support/resistance proximity, VWAP position,
relative volume, a context-specific score, and a JSON alert payload.

`tradingview/stock_ultimus_futures_signal_v1.pine`

Use this for:

- `FUTURES`
- `MNQ`
- `NQ`
- `MES`
- `ES`

It focuses on intraday EMA/VWAP alignment, breakout state, ADX, RSI, and
relative volume. CANSLIM is intentionally not included.

`tradingview/stock_ultimus_canslim_filter_v1.pine`

Use this as a manual/auditable CANSLIM overlay. TradingView may not provide all
fundamental data consistently across symbols, so this script starts with manual
inputs for the CANSLIM letters and emits a `CANSLIM_FILTER` payload.

## Alert Setup

For scripts that call `alert()` directly:

1. Add the indicator to the chart.
2. Configure the inputs.
3. Create an alert.
4. Choose the script condition and "Any alert() function call".
5. Set webhook URL to your `/technical_snapshot` endpoint.
6. Leave the alert message field generic; the script supplies the JSON.

## Recommended Starting Point

Start with `stock_ultimus_options_signal_pro_v2.pine` on `1h` for option
strategies. Use `15m` for faster monitoring only after the base flow is stable.

For futures, start with `stock_ultimus_futures_signal_pro_v2.pine` on `15m`.

For CANSLIM, start with `stock_ultimus_canslim_filter_pro_v2.pine` on `1d` and
treat it as a fundamental filter, not a trigger.

## Local Validation

Run:

```bash
python3 scripts/validate_tradingview_pine_scripts.py
```

The validator checks that Pine files include a Stock Ultimus contract version,
`strategy_context`, and a webhook `alert()` call.

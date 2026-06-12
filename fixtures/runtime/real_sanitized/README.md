# Real Sanitized Runtime Snapshots

Use this folder only for runtime snapshots captured from real IBKR/Render flows after sanitization.

## Allowed

- Tickers and strategies.
- Option contract fields required by V30.
- Technical state from TradingView after removing secrets.
- Decision states, blockers, and explanations.
- Sanitized market/session metadata.

## Not Allowed

- IBKR account identifiers.
- Account balances, buying power, cash, margin, or net liquidation values.
- API keys, webhook secrets, bearer tokens, cookies, or auth headers.
- Local filesystem paths or machine/user identifiers.
- Raw unsanitized positions when a derived field is enough.
- Private URLs or deployment credentials.

## Workflow

1. Capture the runtime snapshot outside the repo.
2. Run:

```bash
python3 scripts/sanitize_runtime_snapshot.py path/to/raw.json fixtures/runtime/real_sanitized/example.json
```

3. Review the sanitized output manually.
4. Run:

```bash
python3 scripts/validate_runtime_privacy.py
```

5. Run the full guard:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/check_v30_integrity.py
```

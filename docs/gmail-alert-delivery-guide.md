# Gmail Alert Delivery Guide

Stock Ultimus emails are sent by Resend as:

- From: `Stock Ultimus <onboarding@resend.dev>`
- Subjects:
  - `Stock Ultimus V31 Monitor: ACTION_REQUIRED`
  - `Stock Ultimus V31 Monitor: WARNING`
  - `Stock Ultimus pre-market ...`
  - `Stock Ultimus Weekly Learning ...`

Gmail can place these messages in `CATEGORY_UPDATES`. That is still inbox
delivery, but it may be easy to miss.

## Recommended Gmail Filter

Create a Gmail filter with this search:

```text
from:(onboarding@resend.dev) subject:(Stock Ultimus)
```

Recommended actions:

- Never send it to Spam.
- Star it.
- Apply label: `Stock Ultimus`.
- Categorize as Primary, if Gmail exposes that option in your account.

Do not auto-archive these alerts. The point is to make market-session warnings
visible without treating them as execution authorization.

## Verification Search

Use this Gmail search when checking delivery:

```text
in:anywhere from:onboarding@resend.dev subject:"Stock Ultimus" newer_than:1d
```

Expected labels for a healthy delivery are usually:

- `INBOX`
- `UNREAD` when not opened
- sometimes `CATEGORY_UPDATES`

If the message is in `TRASH` or `SPAM`, fix the Gmail filter before relying on
email alerts.

## Safety

Email alerts are decision support only. They do not authorize orders. Any trade
must still be manually validated in broker/TWS for contract, liquidity, spread,
events, account risk and ticket details.

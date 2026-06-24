#!/usr/bin/env python3
"""Validate V31 manual review console wiring and guardrails."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "main.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    source = APP.read_text()
    required_snippets = [
        "\"/read_auth_login\"",
        "\"/read_auth_logout\"",
        "request.cookies.get(\"stock_ultimus_read_token\")",
        "@app.get(\"/read_auth_login\"",
        "@app.post(\"/read_auth_login\")",
        "@app.get(\"/v31_manual_review_console\"",
        "@app.post(\"/v31_manual_review_console/record\")",
        "@app.get(\"/v31_manual_review_inbox\"",
        "@app.post(\"/v31_manual_review_inbox/record\")",
        "Daily Review Inbox",
        "APPROVAL_REQUIRES_ENTRY_READY",
        "execution_authorized\": False",
        "not_order_instruction\": True",
        "manual_review_console_url",
        "Abrir consola de revisión manual",
    ]
    for snippet in required_snippets:
        require(snippet in source, f"missing expected snippet: {snippet}")

    require(
        "APPROVED_FOR_MANUAL_TRADE" in source and "state == \"ENTRY_READY\"" in source,
        "approval button must be tied to ENTRY_READY state",
    )
    require(
        "response.set_cookie(" in source and "httponly=True" in source and "secure=True" in source,
        "read auth login must set a secure httponly cookie",
    )
    require(
        "Esta consola registra tu revisión humana. No coloca órdenes" in source,
        "console must display no-order guardrail",
    )
    require(
        "Marca tu revisión humana. Esta pantalla no coloca órdenes" in source,
        "inbox must display no-order guardrail",
    )

    print("Validated V31 manual review console/inbox routes, cookie auth, email link, and no-order guardrails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

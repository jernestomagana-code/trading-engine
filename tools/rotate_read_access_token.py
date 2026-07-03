#!/usr/bin/env python3
"""Rotate the local Stock Ultimus read access token safely.

The token is never printed. By default this stores a new random value in the
macOS Keychain service used by the read checks. Use --copy to place it on the
clipboard so it can be pasted into Render and the GPT Action auth field.
"""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys


DEFAULT_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"


def run_command(args: list[str], *, input_text: str | None = None) -> None:
    subprocess.run(
        args,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def rotate_token(service: str, account: str, *, copy: bool = False) -> dict[str, object]:
    token = secrets.token_hex(32)
    run_command([
        "security",
        "add-generic-password",
        "-U",
        "-a",
        account,
        "-s",
        service,
        "-w",
        token,
    ])
    if copy:
        run_command(["pbcopy"], input_text=token)
    return {
        "status": "ROTATED",
        "keychain_service": service,
        "account": account,
        "copied_to_clipboard": bool(copy),
        "token_printed": False,
        "next_required_action": "Paste the clipboard value into Render READ_ACCESS_TOKEN and the GPT Action auth field, then rerun the health check.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rotate local Stock Ultimus read token without printing it.")
    parser.add_argument("--keychain-service", default=DEFAULT_KEYCHAIN_SERVICE)
    parser.add_argument("--account", default="")
    parser.add_argument("--copy", action="store_true", help="Copy the new token to the macOS clipboard without printing it.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    account = args.account or subprocess.check_output(["id", "-un"], text=True).strip()
    try:
        result = rotate_token(args.keychain_service, account, copy=args.copy)
    except Exception as exc:
        print(f"Rotation failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Read access token rotated locally. "
        f"service={result['keychain_service']} copied_to_clipboard={result['copied_to_clipboard']} token_printed=false"
    )
    print(result["next_required_action"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

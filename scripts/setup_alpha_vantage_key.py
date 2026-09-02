#!/usr/bin/env python3
"""Safely store the free Alpha Vantage key in macOS Keychain."""

from __future__ import annotations

import getpass
import os
import subprocess


SERVICE = "stock-ultimus-alpha-vantage-api-key"


def main() -> int:
    value = getpass.getpass("Pega tu clave gratuita de Alpha Vantage (no se mostrará): ").strip()
    if not value:
        print("No se guardó ninguna clave.")
        return 1
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", os.getenv("USER", ""), "-s", SERVICE, "-w", value],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print("No fue posible guardar la clave en Keychain.")
        return 1
    print("Clave guardada de forma segura. La apertura diaria ya puede actualizar earnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

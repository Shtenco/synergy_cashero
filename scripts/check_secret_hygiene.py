#!/usr/bin/env python3
"""Fail CI if tracked wallet-secret files or obvious private-key literals reappear."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {".env", "owner.env", "bot1.env", "bot2.env"}
FORBIDDEN_SUFFIXES = {".key", ".ppk", ".pem", ".p12", ".pfx", ".seed", ".mnemonic"}
PRIVATE_KEY_VALUE = re.compile(r"(?i)^(?:0x)?[0-9a-f]{64}$")
PRIVATE_KEY_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:OWNER_|BOT\d*_)?PRIVATE_KEY\s*=\s*([^\s#]+)"
)
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"PuTTY-User-Key-File-",
)


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [item.decode("utf-8", "surrogateescape") for item in result.stdout.split(b"\0") if item]


def is_forbidden_path(path: str) -> bool:
    p = Path(path)
    name = p.name.lower()
    if name in FORBIDDEN_NAMES:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if p.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    if p.parent.name.lower() == "wallets" and p.suffix.lower() == ".env":
        return True
    return False


def main() -> int:
    paths = tracked_paths()
    errors: list[str] = []
    for path in paths:
        if is_forbidden_path(path):
            errors.append(f"forbidden tracked secret path: {path}")
            continue
        target = ROOT / path
        try:
            data = target.read_bytes()
        except OSError as exc:
            errors.append(f"cannot inspect tracked file {path}: {exc}")
            continue
        if any(marker in data for marker in PRIVATE_KEY_MARKERS):
            errors.append(f"private-key block marker found in tracked file: {path}")
            continue
        if b"\0" in data:
            continue
        text = data.decode("utf-8", "replace")
        for match in PRIVATE_KEY_ASSIGNMENT.finditer(text):
            value = match.group(1).strip().strip('"').strip("'")
            if PRIVATE_KEY_VALUE.fullmatch(value):
                errors.append(f"private-key-like assignment found in tracked file: {path}")
                break

    if errors:
        print("SECRET HYGIENE: FAIL")
        for error in errors:
            print("-", error)
        return 1
    print(f"SECRET HYGIENE: PASS ({len(paths)} tracked files inspected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

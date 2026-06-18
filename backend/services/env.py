"""
Safe environment variable readers with type coercion and validation.

All functions log a clear error and raise SystemExit(1) on invalid
values (e.g., non-numeric string for an int field), so misconfigured
environments fail fast at startup rather than silently at runtime.
"""

import os
import sys


def env_str(key: str, default: str = "") -> str:
    """Read a string environment variable."""
    return os.getenv(key, default)


def env_int(key: str, default: str) -> int:
    """Read an integer environment variable.  Exits with a clear message on parse failure."""
    raw = os.getenv(key, default)
    try:
        return int(raw)
    except (ValueError, TypeError):
        print(f"FATAL: env var {key} must be an integer, got '{raw}'", file=sys.stderr)
        sys.exit(1)


def env_float(key: str, default: str) -> float:
    """Read a float environment variable.  Exits with a clear message on parse failure."""
    raw = os.getenv(key, default)
    try:
        return float(raw)
    except (ValueError, TypeError):
        print(f"FATAL: env var {key} must be a float, got '{raw}'", file=sys.stderr)
        sys.exit(1)

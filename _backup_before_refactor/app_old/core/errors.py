"""Framework-free error type and credential redaction (importable from any layer)."""
from __future__ import annotations

import urllib.parse

from pf_api import ApiError

# Re-exported so services raise the same exception type the engine already uses.
__all__ = ["ApiError", "MAX_JSON", "contains_secret", "redact", "set_secrets"]

MAX_JSON = 64 * 1024 * 1024

_SECRETS: tuple[str, ...] = ()


def set_secrets(secrets) -> None:
    global _SECRETS
    _SECRETS = tuple(s for s in secrets if s)


def contains_secret(data: bytes) -> bool:
    for secret in _SECRETS:
        if secret.encode("utf-8") in data or urllib.parse.quote(secret, safe="").encode("ascii") in data:
            return True
    return False


def redact(message: str) -> str:
    for secret in _SECRETS:
        message = message.replace(secret, "[비공개]").replace(urllib.parse.quote(secret, safe=""), "[비공개]")
    return message

"""
OTP helpers for the REQUIRE_OTP subscription flow (P2 item 10).

Kept separate from api/routers/subscribe.py so they can be unit-tested
without importing the geospatial stack that the router pulls in.
"""

from __future__ import annotations

import hashlib
import hmac
import os

OTP_TTL_MINUTES  = 10
OTP_MAX_ATTEMPTS = 5


def otp_required() -> bool:
    return os.getenv("REQUIRE_OTP", "").strip().lower() in ("1", "true", "yes")


def hash_code(code: str, phone: str) -> str:
    """sha256 over code+phone — binds the code to the requesting number."""
    secret = os.getenv("DISPATCH_SECRET", "")
    if secret:
        return hmac.new(secret.encode(), f"{code}:{phone}".encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(f"{code}:{phone}".encode()).hexdigest()

"""
Shared bearer-token auth for protected endpoints.

Two secrets, both plain environment variables set in Render:

    DISPATCH_SECRET — operator/cron actions (dispatch, unsubscribe,
                      log access). Required for those endpoints to work.
    VERIFY_SECRET   — field-partner verification submissions. Falls back
                      to DISPATCH_SECRET when unset, so a small pilot can
                      run with a single shared secret.

Comparison uses hmac.compare_digest (constant-time) — a plain != leaks
timing information about how much of the token matched.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def _require_bearer(request: Request, env_vars: tuple[str, ...]) -> None:
    secret = ""
    for name in env_vars:
        secret = os.getenv(name, "").strip()
        if secret:
            break
    if not secret:
        raise HTTPException(
            status_code=503,
            detail=f"{env_vars[0]} environment variable not set.",
        )
    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {secret}"
    if not hmac.compare_digest(auth_header.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized.")


def require_dispatch_secret(request: Request) -> None:
    """Operator/cron endpoints: dispatch, unsubscribe, log access."""
    _require_bearer(request, ("DISPATCH_SECRET",))


def require_verify_secret(request: Request) -> None:
    """Field-partner endpoints: verification intake."""
    _require_bearer(request, ("VERIFY_SECRET", "DISPATCH_SECRET"))


def has_dispatch_secret(request: Request) -> bool:
    """Non-raising check — for endpoints that add detail when authorized."""
    try:
        require_dispatch_secret(request)
        return True
    except HTTPException:
        return False

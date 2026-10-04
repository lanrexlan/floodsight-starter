"""Deployment mode and durable-storage policy shared by API routes."""
import os

from fastapi import HTTPException


def production() -> bool:
    return os.getenv("FLOODSIGHT_ENV", "development").lower() == "production"


def experimental_depth_enabled() -> bool:
    # An explicit off switch must work even on a misconfigured public host.
    default = "false" if production() else "true"
    return os.getenv("ENABLE_EXPERIMENTAL_DEPTH", default).lower() == "true"


def require_durable_storage() -> None:
    if production():
        raise HTTPException(503, "Durable storage is unavailable; please retry later.")

"""Deployment mode and durable-storage policy shared by API routes."""
import os

from fastapi import HTTPException


def production() -> bool:
    return os.getenv("FLOODSIGHT_ENV", "development").lower() == "production"


def require_durable_storage() -> None:
    if production():
        raise HTTPException(503, "Durable storage is unavailable; please retry later.")

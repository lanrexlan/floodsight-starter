"""Select commercial endpoints without logging provider API credentials."""
import os
from urllib.parse import quote


def endpoint(service: str, path: str) -> str:
    key = os.getenv("OPENMETEO_API_KEY", "").strip()
    prefix = {"forecast": "api", "marine": "marine-api", "flood": "flood-api"}[service]
    if key:
        prefix = "customer-" + prefix
    return f"https://{prefix}.open-meteo.com/v1/{path}"


def credential_query() -> str:
    key = os.getenv("OPENMETEO_API_KEY", "").strip()
    return "&apikey=" + quote(key, safe="") if key else ""

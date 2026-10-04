"""Explicit operational gates. Being ready to serve does not certify scientific accuracy."""
import os
from api.runtime import production


def startup_errors() -> list[str]:
    if not production():
        return []
    from api.data_provider import SCORED_GRID_PATH
    missing = [name for name in ("SUPABASE_URL", "SUPABASE_KEY", "DISPATCH_SECRET",
               "AT_WEBHOOK_TOKEN", "AT_USERNAME", "AT_API_KEY", "CORS_ORIGINS", "OPENMETEO_API_KEY")
               if not os.getenv(name, "").strip()]
    errors = [f"{name} must be configured" for name in missing]
    if not SCORED_GRID_PATH.exists():
        errors.append("processed risk grid is missing")
    from floodsight.config import PROCESSED_DIR
    if not (PROCESSED_DIR/'lga_index.json').exists():
        errors.append("packaged cell-to-LGA index is missing")
    if "*" in os.getenv("CORS_ORIGINS", ""):
        errors.append("wildcard CORS is forbidden")
    if os.getenv("REQUIRE_OTP", "").lower() != "true":
        errors.append("REQUIRE_OTP=true is required")
    if os.getenv("DATA_PROVIDER_LICENSES_CONFIRMED", "").lower() != "true":
        errors.append("commercial provider agreements must be confirmed")
    return errors


def readiness_report() -> dict:
    errors = startup_errors()
    if production() and not errors:
        try:
            from api.data_provider import get_grid
            get_grid()  # validate source hash, unique cell IDs and packaged LGA index
            from floodsight.db.supabase_client import _get_client
            client = _get_client()
            if client.rpc("release_schema_version", {}).execute().data != 7:
                errors.append("release database migration is missing")
            for table in ("subscribers", "pending_subscriptions", "verifications", "prediction_log"):
                client.table(table).select("id" if table != "pending_subscriptions" else "phone").limit(1).execute()
        except Exception:
            errors.append("grid integrity, database schema or connectivity check failed")
    return {"ready": not errors, "mode": "production" if production() else "development",
            "stage": "controlled_pilot", "checks_failed": errors}

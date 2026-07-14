"""
FloodSight Health Intelligence Layer — DHIS2 Nigeria API Client.

Pulls malaria case data from the Federal Ministry of Health DHIS2 instance
(or the Lagos State Primary Health Care Development Agency instance) and
stores results in the dhis2_malaria_cases Supabase table.

Environment variables required (add to Render + .env):
    DHIS2_BASE_URL   — e.g. https://dhis2.fmoh.gov.ng
    DHIS2_USERNAME   — read-only service account (request from LSPHCDA)
    DHIS2_PASSWORD   — service account password

Setup checklist (Month 2 task)
--------------------------------
1. Request read-only service account from Lagos State Primary Health Care
   Development Agency (LSPHCDA) IT desk.
2. Log in at DHIS2_BASE_URL and navigate to:
   Maintenance → Organisation Units → filter by "Lagos"
   Copy the UID for each of the 15 AOI LGAs and replace the PLACEHOLDER
   values in LGA_ORG_UNIT_MAP below.
3. Navigate to: Data Elements → filter by "malaria"
   Copy UIDs for confirmed cases, suspected cases, RDT positive, and
   treatment started. Replace PLACEHOLDER values in DATA_ELEMENTS.
4. Test with: python scripts/mel_dhis2_pull.py --period YYYYMM --dry-run

DHIS2 analytics API reference:
  https://docs.dhis2.org/en/develop/using-the-api/dhis-core-version-master/analytics.html
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Org unit mapping  — REPLACE ALL PLACEHOLDER_* WITH REAL DHIS2 UIDs
# Find UIDs at: {DHIS2_BASE_URL}/api/organisationUnits?filter=name:ilike:{LGA}
# ---------------------------------------------------------------------------
LGA_ORG_UNIT_MAP: dict[str, str] = {
    "Agege":            "PLACEHOLDER_AGEGE",
    "Ajeromi-Ifelodun": "PLACEHOLDER_AJEROMI",
    "Alimosho":         "PLACEHOLDER_ALIMOSHO",
    "Amuwo-Odofin":     "PLACEHOLDER_AMUWO",
    "Eti-Osa":          "PLACEHOLDER_ETIOSA",
    "Ifako-Ijaiye":     "PLACEHOLDER_IFAKO",
    "Ikeja":            "PLACEHOLDER_IKEJA",
    "Ikorodu":          "PLACEHOLDER_IKORODU",
    "Kosofe":           "PLACEHOLDER_KOSOFE",
    "Lagos Island":     "PLACEHOLDER_LAGOSISLAND",
    "Lagos Mainland":   "PLACEHOLDER_LAGOSMAINLAND",
    "Mushin":           "PLACEHOLDER_MUSHIN",
    "Ojo":              "PLACEHOLDER_OJO",
    "Oshodi-Isolo":     "PLACEHOLDER_OSHODI",
    "Surulere":         "PLACEHOLDER_SURULERE",
}

# ---------------------------------------------------------------------------
# Data element UIDs — REPLACE WITH REAL DHIS2 DATA ELEMENT UIDs
# Find UIDs at: {DHIS2_BASE_URL}/api/dataElements?filter=name:ilike:malaria
# ---------------------------------------------------------------------------
DATA_ELEMENTS: dict[str, str] = {
    "confirmed_cases":   "PLACEHOLDER_MAL_CONFIRMED_DE_UID",
    "suspected_cases":   "PLACEHOLDER_MAL_SUSPECTED_DE_UID",
    "rdt_positive":      "PLACEHOLDER_MAL_RDT_POS_DE_UID",
    "treatment_started": "PLACEHOLDER_MAL_TREATED_DE_UID",
}


def _get_session() -> requests.Session:
    """Build an authenticated requests.Session for the DHIS2 instance."""
    base_url = os.getenv("DHIS2_BASE_URL", "").strip()
    username = os.getenv("DHIS2_USERNAME", "").strip()
    password = os.getenv("DHIS2_PASSWORD", "").strip()
    if not all([base_url, username, password]):
        raise RuntimeError(
            "DHIS2_BASE_URL, DHIS2_USERNAME, and DHIS2_PASSWORD must all be set. "
            "Add them to Render environment variables and .env."
        )
    session = requests.Session()
    session.auth = (username, password)
    # Store base_url as a session attribute for convenience
    session.base_url = base_url  # type: ignore[attr-defined]
    return session


def pull_malaria_cases(
    period: str,
    lga_names: list[str] | None = None,
) -> list[dict]:
    """
    Pull malaria case counts from DHIS2 for a given reporting period.

    Parameters
    ----------
    period : str
        DHIS2 period format. Use:
          Monthly  → YYYYMM   (e.g. "202506")
          Weekly   → YYYYWnn  (e.g. "2025W22")
          Quarterly→ YYYYQn   (e.g. "2025Q2")

    lga_names : list[str] | None
        LGA names to pull. Defaults to all 15 AOI LGAs.

    Returns
    -------
    List of dicts, one per LGA, with keys:
        lga_name, period, confirmed_cases, suspected_cases,
        rdt_positive, treatment_started, org_unit_id
    """
    session  = _get_session()
    base_url = session.base_url  # type: ignore[attr-defined]

    lgas      = lga_names or list(LGA_ORG_UNIT_MAP.keys())
    org_units = [LGA_ORG_UNIT_MAP[lga] for lga in lgas if lga in LGA_ORG_UNIT_MAP]
    de_uids   = list(DATA_ELEMENTS.values())

    # Filter out placeholder UIDs — they will 404 on real DHIS2
    real_ou = [ou for ou in org_units if not ou.startswith("PLACEHOLDER")]
    real_de = [de for de in de_uids   if not de.startswith("PLACEHOLDER")]

    if not real_ou:
        log.warning(
            "All org unit IDs are placeholders. "
            "Replace LGA_ORG_UNIT_MAP values with real DHIS2 UIDs."
        )
        return []

    if not real_de:
        log.warning(
            "All data element IDs are placeholders. "
            "Replace DATA_ELEMENTS values with real DHIS2 UIDs."
        )
        return []

    params = {
        "dimension": [
            f"dx:{';'.join(real_de)}",
            f"pe:{period}",
            f"ou:{';'.join(real_ou)}",
        ],
        "displayProperty": "NAME",
        "skipMeta":        "false",
        "paging":          "false",
    }

    url = f"{base_url}/api/analytics.json"
    log.info("Fetching DHIS2 malaria data: period=%s, %d LGAs", period, len(real_ou))

    resp = session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Build reverse-lookup maps
    ou_to_lga = {v: k for k, v in LGA_ORG_UNIT_MAP.items()}
    de_to_key = {v: k for k, v in DATA_ELEMENTS.items()}

    rows_by_ou: dict[str, dict] = {}
    for row in data.get("rows", []):
        de_uid, ou_uid, _period, value = row
        lga_name = ou_to_lga.get(ou_uid, ou_uid)
        key      = de_to_key.get(de_uid, de_uid)

        if lga_name not in rows_by_ou:
            rows_by_ou[lga_name] = {
                "lga_name":          lga_name,
                "period":            period,
                "org_unit_id":       ou_uid,
                "confirmed_cases":   None,
                "suspected_cases":   None,
                "rdt_positive":      None,
                "treatment_started": None,
            }
        try:
            rows_by_ou[lga_name][key] = int(float(value)) if value else None
        except (ValueError, TypeError):
            rows_by_ou[lga_name][key] = None

    result = list(rows_by_ou.values())
    log.info("DHIS2 pull complete: %d LGA rows retrieved", len(result))
    return result


def test_connection() -> bool:
    """
    Verify DHIS2 credentials and connectivity.
    Returns True if the connection succeeds, False otherwise.
    """
    try:
        session  = _get_session()
        base_url = session.base_url  # type: ignore[attr-defined]
        resp = session.get(f"{base_url}/api/me.json", timeout=10)
        resp.raise_for_status()
        info = resp.json()
        log.info(
            "DHIS2 connection OK — logged in as %s (%s)",
            info.get("username"),
            info.get("displayName"),
        )
        return True
    except Exception as exc:
        log.error("DHIS2 connection test failed: %s", exc)
        return False

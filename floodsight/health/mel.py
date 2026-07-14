"""
FloodSight Health Intelligence Layer — MEL (Monitoring, Evaluation & Learning).

Helper functions for recording and querying MEL events — the health-system
actions taken by CHEWs in response to outbreak alerts.

MEL Design (NEXA PoC)
----------------------
Treatment arm (alerted): Alimosho, Ajeromi-Ifelodun, Kosofe, Oshodi-Isolo, Ikorodu
Control arm (standard):  Agege, Mushin, Surulere, Lagos Mainland, Ikeja

Primary outcome: % change in confirmed malaria cases (DHIS2) in treatment
vs. control LGAs over the 18-month PoC period, evaluated via
difference-in-differences analysis.

Secondary outcomes:
  - CHEW alert response rate (CONFIRM replies / alerts sent)
  - Time from alert to first health-system action (MEL event)
  - Number of bed nets and RDT kits pre-positioned ahead of outbreak window
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "NETS_DISTRIBUTED",
    "RDT_KITS_PREPOSITIONED",
    "IRS_CONDUCTED",
    "COMMUNITY_SENSITIZATION",
    "CASE_MANAGEMENT_TRAINING",
    "STOCK_PREPOSITIONING",
}


def record_mel_event(
    lga_name: str,
    event_type: str,
    event_date: date | str,
    quantity: int | None = None,
    unit: str | None = None,
    reported_by: str | None = None,
    facility_name: str | None = None,
    ward: str | None = None,
    notes: str | None = None,
    alert_id: int | None = None,
) -> dict:
    """
    Log a health-system action taken in response to a FloodSight alert.

    Parameters
    ----------
    lga_name     : LGA where the action took place
    event_type   : one of VALID_EVENT_TYPES
    event_date   : date the action occurred (date object or ISO string)
    quantity     : numeric quantity (e.g. 500 nets, 20 kits)
    unit         : unit of measurement (e.g. "nets", "kits", "households")
    reported_by  : CHEW phone number or officer name
    facility_name: PHC facility where action originated
    ward         : ward within the LGA
    notes        : free-text notes
    alert_id     : ID of the health_alerts row that triggered this action

    Returns
    -------
    dict of the inserted row
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"Invalid event_type {event_type!r}. "
            f"Must be one of: {sorted(VALID_EVENT_TYPES)}"
        )

    from floodsight.db.supabase_client import log_mel_event

    event = {
        "lga_name":      lga_name,
        "event_type":    event_type,
        "event_date":    event_date.isoformat() if hasattr(event_date, "isoformat") else event_date,
        "quantity":      quantity,
        "unit":          unit,
        "reported_by":   reported_by,
        "facility_name": facility_name,
        "ward":          ward,
        "notes":         notes,
        "alert_id":      alert_id,
    }
    return log_mel_event(event)


def get_mel_summary(lga_name: str | None = None) -> dict[str, Any]:
    """
    Return aggregated MEL statistics, optionally filtered by LGA.

    Returns
    -------
    dict with keys:
        total_events, events_by_type, nets_distributed,
        rdt_kits_prepositioned, lgas_with_events
    """
    from floodsight.db.supabase_client import _get_client

    client = _get_client()
    query  = client.table("mel_events").select("event_type,quantity,lga_name")
    if lga_name:
        query = query.eq("lga_name", lga_name)

    rows = (query.execute()).data or []

    events_by_type: dict[str, int] = {}
    nets_total = 0
    rdt_total  = 0
    lgas_seen: set[str] = set()

    for r in rows:
        et = r.get("event_type", "UNKNOWN")
        q  = r.get("quantity") or 0
        events_by_type[et] = events_by_type.get(et, 0) + 1
        lgas_seen.add(r.get("lga_name", ""))
        if et == "NETS_DISTRIBUTED":
            nets_total += q
        elif et == "RDT_KITS_PREPOSITIONED":
            rdt_total += q

    return {
        "total_events":            len(rows),
        "events_by_type":          events_by_type,
        "nets_distributed":        nets_total,
        "rdt_kits_prepositioned":  rdt_total,
        "lgas_with_events":        sorted(lgas_seen - {""}),
    }

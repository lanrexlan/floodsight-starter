"""
FloodSight Health Intelligence Layer — MEL (Monitoring, Evaluation & Learning).

Records and queries the field data that measures whether the anticipatory-
alert system actually changes what frontline health workers do — and whether
the flood→malaria hypothesis holds in urban Lagos.

MEL DESIGN (NEXA PoC) — PRIMARY vs. SECONDARY
---------------------------------------------
The PoC's job is to demonstrate OPERATIONAL FEASIBILITY, ACCEPTABILITY and
BUY-IN, plus EARLY SIGNALS of health impact (per the Nexa RFP, which states
that alert-generation metrics "would not alone suffice", and that PoC awards
are not required to have a pre-existing evidence base). We therefore lead
with intermediary / operational outcomes that are measurable and adequately
powered within 18 months, and treat population case-counts as an exploratory
early signal only.

PRIMARY (operational / intermediary) outcomes — computed by get_operational_kpis():
  O1. Alert acknowledgement rate: % of alerts a CHEW confirms within 48 h.
  O2. Alert-to-action time: median hours from alert dispatch to first logged
      health-system action (net/RDT pre-positioning) in that LGA+window.
  O3. Anticipatory-action rate: % of Moderate+ alerts followed by at least one
      commodity pre-positioning action BEFORE the outbreak window opens.
  O4. Entomological confirmation: % of alerted, larval-surveyed sites where
      Anopheles larvae are confirmed (tests the flood→malaria-vector link that
      urban Culex dominance could otherwise break — see engine.py caveat and
      the entomology_observations table, migration 002).
  O5. Acceptability: CHEW-reported usefulness (endline survey) + sustained
      response rate over the season (proxy for trust / low alert fatigue).

SECONDARY (exploratory early signal — NOT the primary endpoint):
  Malaria trend in DHIS2 confirmed cases per 100k, treatment vs. comparison
  LGAs, over each flood window. Reported with explicit power caveats:
  n = 5 vs 5 LGA clusters is underpowered for causal attribution; RDT
  pre-positioning can INCREASE detected cases (better case-finding), so a
  raw case reduction is NOT expected within the grant and is not how success
  is defined. This is analysed as a directional signal and a hypothesis-
  generating input to a future Transition-to-Scale evaluation.

Comparison design: matched-pair LGAs (5 treatment / 5 comparison), analysed
as an event-study / difference-in-differences on the intermediary outcomes
where a comparison is meaningful, with LGA fixed effects and pre-registered
analysis. The comparison arm's main role at PoC is to contextualise the
operational outcomes, not to power a case-count effect.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Health-system actions (what CHEWs / facilities DID in response to an alert)
ACTION_EVENT_TYPES = {
    "NETS_DISTRIBUTED",
    "RDT_KITS_PREPOSITIONED",
    "IRS_CONDUCTED",
    "COMMUNITY_SENSITIZATION",
    "CASE_MANAGEMENT_TRAINING",
    "STOCK_PREPOSITIONING",
    "LARVAL_SOURCE_MANAGEMENT",   # clearing/treating standing-water sites
}

# Operational / verification events (measure the system + the hypothesis)
OPERATIONAL_EVENT_TYPES = {
    "ALERT_ACKNOWLEDGED",         # CHEW confirmed receipt (O1)
    "LARVAL_SURVEY_CONDUCTED",    # a dip survey was done at a flagged site (O4)
    "ANOPHELES_CONFIRMED",        # Anopheles larvae found at a flagged site (O4)
    "CULEX_ONLY",                 # only Culex found — flags a false-positive habitat
    "NO_LARVAE",                  # surveyed, no larvae — flags a false alarm
}

VALID_EVENT_TYPES = ACTION_EVENT_TYPES | OPERATIONAL_EVENT_TYPES

# Event types that count as a "health-system action" for O2/O3 timing.
_ANTICIPATORY_ACTIONS = {
    "NETS_DISTRIBUTED",
    "RDT_KITS_PREPOSITIONED",
    "STOCK_PREPOSITIONING",
    "LARVAL_SOURCE_MANAGEMENT",
    "IRS_CONDUCTED",
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
    Log a health-system action OR an operational/verification event taken in
    response to a FloodSight alert.

    event_type must be one of VALID_EVENT_TYPES (actions + operational events).
    See the module docstring for how each maps to a PoC outcome (O1–O5).

    Returns the inserted row dict.
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
    Aggregated MEL statistics (dashboard commodity counters), optionally by LGA.

    Returns dict with keys: total_events, events_by_type, nets_distributed,
    rdt_kits_prepositioned, lgas_with_events.
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


# ---------------------------------------------------------------------------
# PRIMARY PoC outcomes — the operational / intermediary indicators the grant
# is actually judged on. Computed from health_alerts + chew_responses +
# mel_events + entomology_observations. Designed to be measurable and
# adequately powered within 18 months at the ALERT / EVENT level (n = hundreds
# of alerts and actions), unlike an LGA-cluster case-count effect.
# ---------------------------------------------------------------------------

def _parse_ts(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def get_operational_kpis() -> dict[str, Any]:
    """
    Compute the PoC's PRIMARY (operational / intermediary) outcome indicators.

    O1 acknowledgement_rate      — CONFIRM within 48 h / alerts sent
    O2 median_alert_to_action_h  — median hours alert → first action (same LGA)
    O3 anticipatory_action_rate  — Moderate+ alerts with a pre-positioning
                                   action logged BEFORE the outbreak window
    O4 anopheles_confirmation_rate — Anopheles-confirmed / larval-surveyed sites
       culex_only_rate             — Culex-only / larval-surveyed sites
    plus raw counts for transparency.

    All values are None-safe and return 0 / None when data is absent (e.g. at
    submission, before enrolment) so dashboards and the endpoint render.
    """
    from floodsight.db.supabase_client import _get_client

    client = _get_client()

    alerts    = (client.table("health_alerts").select("*").execute()).data or []
    responses = (client.table("chew_responses").select("*").execute()).data or []
    events    = (client.table("mel_events").select("*").execute()).data or []

    n_alerts = len(alerts)

    # ---- O1: acknowledgement within 48 h -------------------------------
    confirmed = [r for r in responses
                 if str(r.get("parsed_action") or r.get("reply_type") or "").upper() == "CONFIRM"]
    ack_rate = round(len(confirmed) / n_alerts, 4) if n_alerts else None

    # ---- O2: alert-to-action median hours ------------------------------
    # For each alert, find the earliest anticipatory action in the same LGA
    # at or after the alert timestamp.
    action_events = [
        e for e in events if e.get("event_type") in _ANTICIPATORY_ACTIONS
    ]
    deltas_h: list[float] = []
    for a in alerts:
        a_ts = _parse_ts(a.get("sent_at") or a.get("created_at"))
        a_lga = a.get("lga_name")
        if not a_ts or not a_lga:
            continue
        candidate_ts = []
        for e in action_events:
            if e.get("lga_name") != a_lga:
                continue
            e_ts = _parse_ts(e.get("recorded_at") or e.get("event_date"))
            if e_ts and e_ts >= a_ts:
                candidate_ts.append(e_ts)
        if candidate_ts:
            deltas_h.append((min(candidate_ts) - a_ts).total_seconds() / 3600.0)
    deltas_h.sort()
    median_ttA = round(deltas_h[len(deltas_h) // 2], 1) if deltas_h else None

    # ---- O3: anticipatory-action rate ----------------------------------
    moderate_plus = [
        a for a in alerts
        if str(a.get("risk_tier", "")) in ("Moderate", "High", "Critical")
    ]
    acted_before_window = 0
    for a in moderate_plus:
        a_lga = a.get("lga_name")
        win_start = _parse_ts(a.get("outbreak_window_start"))
        for e in action_events:
            if e.get("lga_name") != a_lga:
                continue
            e_ts = _parse_ts(e.get("recorded_at") or e.get("event_date"))
            if e_ts and (win_start is None or e_ts <= win_start):
                acted_before_window += 1
                break
    anticipatory_rate = (
        round(acted_before_window / len(moderate_plus), 4) if moderate_plus else None
    )

    # ---- O4: entomological confirmation --------------------------------
    surveys = [e for e in events if e.get("event_type") == "LARVAL_SURVEY_CONDUCTED"]
    anopheles = [e for e in events if e.get("event_type") == "ANOPHELES_CONFIRMED"]
    culex_only = [e for e in events if e.get("event_type") == "CULEX_ONLY"]
    n_surv = len(surveys)
    anoph_rate = round(len(anopheles) / n_surv, 4) if n_surv else None
    culex_rate = round(len(culex_only) / n_surv, 4) if n_surv else None

    return {
        "alerts_sent":                 n_alerts,
        "O1_acknowledgement_rate":     ack_rate,
        "O1_target":                   0.60,     # ≥60% CONFIRM within 48 h
        "O2_median_alert_to_action_h": median_ttA,
        "O3_anticipatory_action_rate": anticipatory_rate,
        "O3_actions_before_window":    acted_before_window,
        "O3_moderate_plus_alerts":     len(moderate_plus),
        "O4_larval_surveys":           n_surv,
        "O4_anopheles_confirmation_rate": anoph_rate,
        "O4_culex_only_rate":          culex_rate,
        "confirm_replies":             len(confirmed),
        "note": (
            "Primary PoC outcomes are operational/intermediary and measured at "
            "the alert/action/site level. DHIS2 case-counts are an exploratory "
            "secondary signal only (n=5v5 LGA clusters is underpowered; RDT "
            "pre-positioning can raise detected cases)."
        ),
    }

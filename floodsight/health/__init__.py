"""
FloodSight Health Intelligence Layer.

Translates flood predictions into mosquito outbreak probability scores,
dispatches SMS alerts to Community Health Extension Workers (CHEWs), and
collects MEL data for the NEXA Proof of Concept evaluation.

Modules
-------
engine        — Outbreak probability scorer (epidemiological model)
chew_alerts   — CHEW SMS alert composition and dispatch
dhis2_client  — DHIS2 Nigeria malaria case data client
mel           — MEL data collection helpers
"""

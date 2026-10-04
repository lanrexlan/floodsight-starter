"""Normalize event identity without inventing observed label provenance."""
import pandas as pd


def normalize_dataset(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    primary = df.get("event_name", pd.Series(index=df.index, dtype=object)).replace(r"^\s*$", pd.NA, regex=True)
    legacy = df.get("event", pd.Series(index=df.index, dtype=object)).replace(r"^\s*$", pd.NA, regex=True)
    conflict = primary.notna() & legacy.notna() & (primary != legacy)
    if conflict.any():
        raise ValueError("Conflicting event and event_name identities; resolve before training.")
    if "event_name" in df or "event" in df:
        df["event_name"] = primary.fillna(legacy)
        if df["event_name"].isna().any():
            raise ValueError("Every training row needs an event identity.")
    if "label_source" not in df:
        df["label_source"] = "unknown"
    else:
        df["label_source"] = df["label_source"].fillna("unknown")
    return df

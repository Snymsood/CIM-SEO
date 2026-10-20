"""Track issue lifecycle across weekly crawl artifacts."""

from __future__ import annotations

import pandas as pd


def update_issue_history(previous: pd.DataFrame, current: pd.DataFrame, key: str, as_of) -> pd.DataFrame:
    today = str(as_of)
    now = current.drop_duplicates(key).copy()
    now["first_seen"] = today
    now["last_seen"] = today
    now["status"] = "open"
    if previous.empty or key not in previous:
        return now
    old = previous.drop_duplicates(key, keep="last").set_index(key)
    now = now.set_index(key)
    shared = now.index.intersection(old.index)
    now.loc[shared, "first_seen"] = old.loc[shared, "first_seen"].fillna(today).values
    resolved = old.loc[old.index.difference(now.index)].copy()
    resolved["status"] = "resolved"
    return pd.concat([now, resolved]).reset_index()

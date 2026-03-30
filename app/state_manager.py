from __future__ import annotations

import json
from typing import Any

from paths import TRACKER_STATE_PATH


def default_state() -> dict[str, Any]:
    return {
        "last_attempt_status": None,
        "last_attempt_message": None,

        "last_snapshot_hash": None,
        "last_snapshot_path": None,
        "last_snapshot_saved_at": None,

        "last_reported_hash": None,
        "last_reported_snapshot_path": None,
        "last_reported_at": None,

        "pending_report_hash": None,
        "pending_snapshot_path": None,
        "pending_previous_snapshot_path": None,
    }


def load_state() -> dict[str, Any]:
    if not TRACKER_STATE_PATH.exists():
        return default_state()

    try:
        with open(TRACKER_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_state()

    merged = default_state()
    merged.update(data)
    return merged


def save_state(state: dict[str, Any]) -> None:
    TRACKER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
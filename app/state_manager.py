from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from exceptions import StateCorruptionError
from paths import ROOT_DIR, TRACKER_STATE_PATH

STATE_SCHEMA_VERSION = 2


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
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
    except Exception as exc:
        raise StateCorruptionError(f"상태 파일을 읽을 수 없습니다: {TRACKER_STATE_PATH}: {exc}") from exc

    if not isinstance(data, dict):
        raise StateCorruptionError("상태 파일의 최상위 JSON은 객체여야 합니다")

    raw_schema_version = data.get("schema_version", 1)
    if not isinstance(raw_schema_version, int) or raw_schema_version < 1:
        raise StateCorruptionError(f"상태 스키마 버전이 잘못되었습니다: {raw_schema_version}")
    if raw_schema_version > STATE_SCHEMA_VERSION:
        raise StateCorruptionError(
            f"지원하지 않는 미래 상태 스키마입니다: {raw_schema_version}"
        )

    merged = default_state()
    merged.update(data)
    merged["schema_version"] = STATE_SCHEMA_VERSION
    return merged


def save_state(state: dict[str, Any]) -> None:
    TRACKER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["schema_version"] = STATE_SCHEMA_VERSION
    temp_path = TRACKER_STATE_PATH.with_name(
        f".{TRACKER_STATE_PATH.name}.{uuid4().hex}.tmp"
    )

    try:
        with open(temp_path, "w", encoding="utf-8") as temp_file:
            json.dump(state, temp_file, ensure_ascii=False, indent=2)
            temp_file.flush()

        temp_path.replace(TRACKER_STATE_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def path_to_state_value(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def resolve_state_path(value: str | None) -> Path | None:
    if not value:
        return None

    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path

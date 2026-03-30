from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from paths import SNAPSHOTS_DIR


def compute_snapshot_hash(df: pd.DataFrame) -> str:
    cols = ["asset_key", "종목명", "수량", "평가금액(원)", "비중(%)", "asset_type"]

    normalized = df[cols].copy()
    normalized = normalized.sort_values("asset_key").reset_index(drop=True)

    normalized["수량"] = normalized["수량"].fillna(0)
    normalized["평가금액(원)"] = normalized["평가금액(원)"].fillna(0)
    normalized["비중(%)"] = normalized["비중(%)"].fillna(0).round(6)

    payload = normalized.to_csv(index=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_snapshot_filename(snapshot_date: str | None = None) -> str:
    if snapshot_date:
        return f"{snapshot_date}.csv"

    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    return now_kst.strftime("%Y-%m-%d.csv")


def save_snapshot(df: pd.DataFrame, snapshot_date: str | None = None) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    file_name = make_snapshot_filename(snapshot_date)
    path = SNAPSHOTS_DIR / file_name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def save_snapshot_as(df: pd.DataFrame, file_name: str) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / file_name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def list_snapshot_paths() -> list[Path]:
    return sorted(SNAPSHOTS_DIR.glob("*.csv"))


def get_latest_snapshot_path() -> Path | None:
    files = list_snapshot_paths()
    return files[-1] if files else None


def load_snapshot_df(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    return pd.read_csv(path, encoding="utf-8-sig")
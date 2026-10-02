from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from paths import SNAPSHOTS_DIR


def compute_snapshot_hash(df: pd.DataFrame, *, legacy: bool = False) -> str:
    cols = ["asset_key", "종목명", "수량", "평가금액(원)", "비중(%)", "asset_type"]

    normalized = df[cols].copy()
    normalized = normalized.sort_values("asset_key").reset_index(drop=True)

    if legacy:
        # 배포 전에 저장된 미발송 보고서의 무결성 확인에만 사용한다.
        normalized["수량"] = normalized["수량"].fillna(0)
        normalized["평가금액(원)"] = normalized["평가금액(원)"].fillna(0)
        normalized["비중(%)"] = normalized["비중(%)"].fillna(0).round(6)
        payload = normalized.to_csv(index=False)
    else:
        for col in ["수량", "평가금액(원)", "비중(%)"]:
            numeric = pd.to_numeric(normalized[col], errors="raise")
            if col == "비중(%)":
                numeric = numeric.round(6)
            def canonical(value):
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError(f"스냅샷 {col}에 유효하지 않은 숫자가 있습니다")
                return "0" if number == 0 else format(number.normalize(), "f")
            normalized[col] = numeric.map(canonical)
        if normalized.isna().any().any():
            raise ValueError("스냅샷에 누락된 값이 있습니다")
        payload = json.dumps(normalized.values.tolist(), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_snapshot_filename(snapshot_date: str | None = None) -> str:
    if snapshot_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot_date):
            raise ValueError("스냅샷 날짜는 YYYY-MM-DD 형식이어야 합니다")
        datetime.strptime(snapshot_date, "%Y-%m-%d")
        return f"{snapshot_date}.csv"

    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    return now_kst.strftime("%Y-%m-%d.csv")


def save_snapshot(df: pd.DataFrame, snapshot_date: str | None = None) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    file_name = make_snapshot_filename(snapshot_date)
    base_path = SNAPSHOTS_DIR / file_name
    snapshot_hash = compute_snapshot_hash(df)

    if not base_path.exists():
        _write_snapshot_atomic(df, base_path)
        return base_path

    try:
        if compute_snapshot_hash(load_snapshot_df(base_path)) == snapshot_hash:
            return base_path
    except Exception:
        pass

    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    timestamp = now_kst.strftime("%H%M%S")
    dated_stem = Path(file_name).stem
    existing_matches = sorted(
        SNAPSHOTS_DIR.glob(f"{dated_stem}_*_{snapshot_hash[:8]}.csv")
    )
    for existing_path in reversed(existing_matches):
        try:
            if compute_snapshot_hash(load_snapshot_df(existing_path)) == snapshot_hash:
                return existing_path
        except Exception:
            continue

    unique_path = SNAPSHOTS_DIR / f"{dated_stem}_{timestamp}_{snapshot_hash[:8]}.csv"

    if unique_path.exists():
        raise FileExistsError(f"스냅샷 저장 경로 충돌: {unique_path.name}")

    _write_snapshot_atomic(df, unique_path)
    return unique_path


def _write_snapshot_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def list_snapshot_paths() -> list[Path]:
    return sorted(SNAPSHOTS_DIR.glob("*.csv"))


def get_latest_snapshot_path() -> Path | None:
    files = list_snapshot_paths()
    return files[-1] if files else None


def get_latest_two_snapshot_paths() -> tuple[Path, Path]:
    files = list_snapshot_paths()
    if len(files) < 2:
        raise FileNotFoundError("비교하려면 snapshot CSV 파일이 최소 2개 필요합니다")
    return files[-2], files[-1]


def load_snapshot_df(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    return pd.read_csv(path, encoding="utf-8-sig")

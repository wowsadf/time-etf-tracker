from __future__ import annotations

import numpy as np
import pandas as pd

from exceptions import DataNotReadyError
from logging_utils import setup_logger

logger = setup_logger()


def validate_holdings(df: pd.DataFrame) -> None:
    required_cols = [
        "asset_key",
        "종목명",
        "수량",
        "평가금액(원)",
        "비중(%)",
        "asset_type",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"검증 실패: 필수 컬럼 누락 {missing}")

    # 헤더만 있고 실제 데이터가 없는 경우
    if len(df) == 0:
        raise DataNotReadyError("헤더만 있고 실제 구성종목 데이터가 없습니다")

    if len(df) < 10:
        raise ValueError(f"검증 실패: 행 수가 너무 적습니다 ({len(df)})")

    nan_count = df["비중(%)"].isna().sum()
    if nan_count > 0:
        raise ValueError(f"검증 실패: 비중(%) NaN이 {nan_count}개 있습니다")

    duplicated = df["asset_key"].duplicated().sum()
    if duplicated > 0:
        raise ValueError(f"검증 실패: asset_key 중복이 {duplicated}개 있습니다")

    empty_names = df["종목명"].fillna("").astype(str).str.strip().eq("").sum()
    if empty_names > 0:
        raise ValueError(f"검증 실패: 종목명이 비어 있는 행이 {empty_names}개 있습니다")

    allowed_asset_types = {"stock", "cash", "futures", "other"}
    invalid_asset_types = sorted(set(df["asset_type"].dropna()) - allowed_asset_types)
    if invalid_asset_types:
        raise ValueError(f"검증 실패: 알 수 없는 asset_type이 있습니다: {invalid_asset_types}")

    for col in ["수량", "평가금액(원)", "비중(%)"]:
        numeric = pd.to_numeric(df[col], errors="coerce")
        invalid_count = int((numeric.isna() | ~np.isfinite(numeric)).sum())
        if invalid_count > 0:
            raise ValueError(f"검증 실패: {col} 비정상 값이 {invalid_count}개 있습니다")
        negative_count = int(
            ((numeric < 0) & df["asset_type"].isin(["stock", "cash"])).sum()
        )
        if negative_count > 0:
            raise ValueError(
                f"검증 실패: 주식/현금 {col} 음수 값이 {negative_count}개 있습니다"
            )

    total_weight = df["비중(%)"].sum()
    logger.info(f"[VALIDATE] total_weight={total_weight:.4f}")

    if not (98 <= total_weight <= 102):
        raise ValueError(f"검증 실패: 비중 합계가 비정상적입니다 ({total_weight:.4f}%)")

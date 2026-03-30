from __future__ import annotations

import pandas as pd

from exceptions import DataNotReadyError
from logging_utils import setup_logger

logger = setup_logger()


def validate_holdings(df: pd.DataFrame) -> None:
    required_cols = ["asset_key", "종목명", "비중(%)", "asset_type"]
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

    total_weight = df["비중(%)"].sum()
    logger.info(f"[VALIDATE] total_weight={total_weight:.4f}")

    if not (95 <= total_weight <= 105):
        raise ValueError(f"검증 실패: 비중 합계가 비정상적입니다 ({total_weight:.4f}%)")
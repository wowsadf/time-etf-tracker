from __future__ import annotations

import pandas as pd
import numpy as np


def add_rank(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.reset_index(drop=True).copy()
    columns = ["수량", "평가금액(원)", "비중(%)"]
    numeric = ranked[columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("비교 데이터에 누락되거나 무한대인 숫자가 있습니다")
    ranked[columns] = numeric
    ranked["rank"] = pd.NA

    stock_indices = ranked[ranked["asset_type"] == "stock"].sort_values(
        ["비중(%)", "asset_key"],
        ascending=[False, True],
    ).index
    ranked.loc[stock_indices, "rank"] = range(1, len(stock_indices) + 1)
    ranked["rank"] = pd.to_numeric(ranked["rank"], errors="coerce")
    return ranked


def compare_holdings(today_df: pd.DataFrame, prev_df: pd.DataFrame) -> pd.DataFrame:
    today_df = add_rank(today_df)
    prev_df = add_rank(prev_df)

    merged = today_df.merge(
        prev_df,
        on="asset_key",
        how="outer",
        suffixes=("_today", "_prev"),
        indicator=True,
        validate="one_to_one",
    )

    merged["종목명"] = merged["종목명_today"].fillna(merged["종목명_prev"])
    both = merged["_merge"] == "both"
    if (merged.loc[both, "asset_type_today"] != merged.loc[both, "asset_type_prev"]).any():
        raise ValueError("같은 종목 키의 자산 분류가 변경되었습니다. 원본을 확인하세요")
    merged["asset_type"] = merged["asset_type_today"].fillna(merged["asset_type_prev"])

    merged["비중(%)_today"] = merged["비중(%)_today"].fillna(0)
    merged["비중(%)_prev"] = merged["비중(%)_prev"].fillna(0)

    merged["diff_pctp"] = (merged["비중(%)_today"] - merged["비중(%)_prev"]).round(6)
    merged["rank_diff"] = merged["rank_prev"] - merged["rank_today"]

    merged["수량_today"] = pd.to_numeric(merged["수량_today"], errors="coerce").fillna(0)
    merged["수량_prev"] = pd.to_numeric(merged["수량_prev"], errors="coerce").fillna(0)
    merged["quantity_diff"] = (merged["수량_today"] - merged["수량_prev"]).round(6)
    merged["quantity_change_pct"] = (
        merged["quantity_diff"] / merged["수량_prev"].where(merged["수량_prev"] > 0) * 100
    ).round(4)

    merged["평가금액(원)_today"] = pd.to_numeric(
        merged["평가금액(원)_today"], errors="coerce"
    ).fillna(0)
    merged["평가금액(원)_prev"] = pd.to_numeric(
        merged["평가금액(원)_prev"], errors="coerce"
    ).fillna(0)
    merged["valuation_diff_krw"] = (
        merged["평가금액(원)_today"] - merged["평가금액(원)_prev"]
    )

    merged["status"] = "unchanged"
    merged.loc[merged["_merge"] == "left_only", "status"] = "new"
    merged.loc[merged["_merge"] == "right_only", "status"] = "removed"
    merged.loc[
        (merged["_merge"] == "both") & (merged["diff_pctp"] > 0),
        "status"
    ] = "increased"
    merged.loc[
        (merged["_merge"] == "both") & (merged["diff_pctp"] < 0),
        "status"
    ] = "decreased"

    merged["quantity_status"] = "unchanged"
    merged.loc[merged["_merge"] == "left_only", "quantity_status"] = "new"
    merged.loc[merged["_merge"] == "right_only", "quantity_status"] = "removed"
    merged.loc[
        (merged["_merge"] == "both") & (merged["quantity_diff"] > 0),
        "quantity_status",
    ] = "bought"
    merged.loc[
        (merged["_merge"] == "both") & (merged["quantity_diff"] < 0),
        "quantity_status",
    ] = "sold"

    return merged.drop(columns=["_merge"])


def has_stock_quantity_changes(compared: pd.DataFrame) -> bool:
    """편입·편출 또는 기존 주식 수량 증감만 자동 메일의 발송 사유로 본다."""
    return bool((
        compared["asset_type"].eq("stock")
        & compared["quantity_status"].isin(["new", "removed", "bought", "sold"])
    ).any())

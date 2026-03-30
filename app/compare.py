from __future__ import annotations

import pandas as pd


def add_rank(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.copy().sort_values("비중(%)", ascending=False).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    return ranked


def compare_holdings(today_df: pd.DataFrame, prev_df: pd.DataFrame) -> pd.DataFrame:
    today_df = add_rank(today_df)
    prev_df = add_rank(prev_df)

    merged = today_df.merge(
        prev_df,
        on="asset_key",
        how="outer",
        suffixes=("_today", "_prev"),
    )

    merged["종목명"] = merged["종목명_today"].fillna(merged["종목명_prev"])
    merged["asset_type"] = merged["asset_type_today"].fillna(merged["asset_type_prev"])

    merged["비중(%)_today"] = merged["비중(%)_today"].fillna(0)
    merged["비중(%)_prev"] = merged["비중(%)_prev"].fillna(0)

    merged["rank_today"] = merged["rank_today"].fillna(999)
    merged["rank_prev"] = merged["rank_prev"].fillna(999)

    merged["diff_pctp"] = (merged["비중(%)_today"] - merged["비중(%)_prev"]).round(6)
    merged["rank_diff"] = merged["rank_prev"] - merged["rank_today"]

    merged["status"] = "unchanged"
    merged.loc[
        (merged["비중(%)_prev"] == 0) & (merged["비중(%)_today"] > 0),
        "status"
    ] = "new"
    merged.loc[
        (merged["비중(%)_prev"] > 0) & (merged["비중(%)_today"] == 0),
        "status"
    ] = "removed"
    merged.loc[
        (merged["비중(%)_prev"] > 0) & (merged["비중(%)_today"] > 0) & (merged["diff_pctp"] > 0),
        "status"
    ] = "increased"
    merged.loc[
        (merged["비중(%)_prev"] > 0) & (merged["비중(%)_today"] > 0) & (merged["diff_pctp"] < 0),
        "status"
    ] = "decreased"

    return merged
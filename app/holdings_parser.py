from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from logging_utils import setup_logger

logger = setup_logger()

REQUIRED_COLUMNS = ["종목코드", "종목명", "수량", "평가금액(원)", "비중(%)"]


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def detect_header_row(file_path: Path, max_scan_rows: int = 10) -> int:
    preview = pd.read_excel(file_path, header=None, nrows=max_scan_rows)

    best_row = 0
    best_score = -1

    for idx, row in preview.iterrows():
        row_values = [normalize_text(v) for v in row.tolist()]
        score = sum(1 for col in REQUIRED_COLUMNS if col in row_values)
        if score > best_score:
            best_score = score
            best_row = idx

    logger.info(f"[PARSE] detected header row={best_row}")
    return best_row


def validate_required_columns(df: pd.DataFrame) -> None:
    actual_cols = [normalize_text(c) for c in df.columns]
    missing = [col for col in REQUIRED_COLUMNS if col not in actual_cols]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing} / actual={actual_cols}")


def classify_asset(row: pd.Series) -> str:
    code = normalize_text(row.get("종목코드", "")).upper()
    name = normalize_text(row.get("종목명", ""))

    if name == "현금":
        return "cash"
    if "INDEX" in code:
        return "futures"
    if "EQUITY" in code:
        return "stock"
    return "other"


def make_asset_key(row: pd.Series) -> str:
    code = normalize_text(row.get("종목코드", ""))
    name = normalize_text(row.get("종목명", ""))

    if code:
        return code.upper()
    return name.upper()


def load_holdings_excel(file_path: Path) -> pd.DataFrame:
    header_row = detect_header_row(file_path)
    df = pd.read_excel(file_path, header=header_row)

    df.columns = [normalize_text(c) for c in df.columns]
    validate_required_columns(df)

    df["종목코드"] = df["종목코드"].apply(normalize_text)
    df["종목명"] = df["종목명"].apply(normalize_text)

    df["수량"] = (
        df["수량"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce")

    df["평가금액(원)"] = (
        df["평가금액(원)"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["평가금액(원)"] = pd.to_numeric(df["평가금액(원)"], errors="coerce")

    df["비중(%)"] = pd.to_numeric(df["비중(%)"], errors="coerce")

    df = df.dropna(how="all").copy()

    df["asset_key"] = df.apply(make_asset_key, axis=1)
    df["asset_type"] = df.apply(classify_asset, axis=1)

    df = df[df["asset_key"] != ""].copy()
    df = df.drop_duplicates(subset=["asset_key"], keep="first").copy()

    logger.info(f"[PARSE] parsed rows={len(df)}")
    return df
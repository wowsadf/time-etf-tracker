from __future__ import annotations

import pandas as pd

from compare import compare_holdings
from logging_utils import setup_logger
from paths import SNAPSHOTS_DIR
from reporter import build_compare_report_text

logger = setup_logger()


def main() -> None:
    prev_path = SNAPSHOTS_DIR / "2026-03-26.csv"
    today_path = SNAPSHOTS_DIR / "2026-03-27.csv"

    if not prev_path.exists():
        raise FileNotFoundError(f"이전 snapshot 파일이 없습니다: {prev_path}")
    if not today_path.exists():
        raise FileNotFoundError(f"오늘 snapshot 파일이 없습니다: {today_path}")

    logger.info(f"[COMPARE] prev snapshot: {prev_path.name}")
    logger.info(f"[COMPARE] today snapshot: {today_path.name}")

    prev_df = pd.read_csv(prev_path, encoding="utf-8-sig")
    today_df = pd.read_csv(today_path, encoding="utf-8-sig")

    compared = compare_holdings(today_df, prev_df)
    report_text = build_compare_report_text(compared)

    print(report_text)


if __name__ == "__main__":
    main()
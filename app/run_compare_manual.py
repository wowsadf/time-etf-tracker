from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from compare import compare_holdings
from logging_utils import setup_logger
from reporter import build_compare_report_text
from snapshot_manager import get_latest_two_snapshot_paths

logger = setup_logger()


def main() -> None:
    parser = argparse.ArgumentParser(description="두 ETF snapshot CSV를 비교합니다")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--current", type=Path)
    args = parser.parse_args()

    default_prev, default_today = (
        get_latest_two_snapshot_paths()
        if args.previous is None or args.current is None
        else (args.previous, args.current)
    )
    prev_path = args.previous or default_prev
    today_path = args.current or default_today

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

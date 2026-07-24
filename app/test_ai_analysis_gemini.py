from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ai_analyzer_gemini import analyze_compare_payload_with_gemini
from compare import compare_holdings
from logging_utils import setup_logger
from paths import ROOT_DIR
from reporter import build_compare_ai_payload
from snapshot_manager import get_latest_two_snapshot_paths

logger = setup_logger()


def main() -> None:
    parser = argparse.ArgumentParser(description="두 snapshot으로 Gemini 분석을 시험합니다")
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

    prev_df = pd.read_csv(prev_path, encoding="utf-8-sig")
    today_df = pd.read_csv(today_path, encoding="utf-8-sig")

    compared = compare_holdings(today_df, prev_df)
    payload = build_compare_ai_payload(compared)

    result = analyze_compare_payload_with_gemini(payload)

    output_path = ROOT_DIR / "temp" / "gemini_analysis_preview.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )

    logger.info(f"[AI TEST] analysis saved: {output_path}")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

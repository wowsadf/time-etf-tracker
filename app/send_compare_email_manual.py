from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ai_analyzer_gemini import analyze_compare_payload_with_gemini
from compare import compare_holdings
from email_sender import send_html_email
from logging_utils import setup_logger
from reporter import build_compare_ai_payload, build_compare_report_html, build_compare_report_text
from snapshot_manager import get_latest_two_snapshot_paths

logger = setup_logger()


def main() -> None:
    parser = argparse.ArgumentParser(description="두 snapshot 비교 리포트를 이메일로 보냅니다")
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

    ai_payload = build_compare_ai_payload(compared)
    logger.info(f"[EMAIL TEST] AI payload summary keys: {list(ai_payload.keys())}")
    logger.info("[EMAIL TEST] requesting Gemini analysis")
    ai_analysis = analyze_compare_payload_with_gemini(ai_payload).model_dump()

    html_body = build_compare_report_html(
        compared,
        title="TIME 미국나스닥100 액티브 구성종목 변화",
        ai_analysis=ai_analysis,
    )
    text_body = build_compare_report_text(compared)

    send_html_email(
        subject="[ETF AI 테스트] TIME 미국나스닥100 액티브 구성종목 변화",
        html_body=html_body,
        text_body=text_body,
    )


if __name__ == "__main__":
    main()

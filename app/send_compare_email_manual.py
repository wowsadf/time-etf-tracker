from __future__ import annotations

import pandas as pd

from compare import compare_holdings
from email_sender import send_html_email
from logging_utils import setup_logger
from paths import SNAPSHOTS_DIR
from reporter import build_compare_ai_payload, build_compare_report_html, build_compare_report_text

logger = setup_logger()


def main() -> None:
    prev_path = SNAPSHOTS_DIR / "2026-03-26.csv"
    today_path = SNAPSHOTS_DIR / "2026-03-27.csv"

    if not prev_path.exists():
        raise FileNotFoundError(f"이전 snapshot 파일이 없습니다: {prev_path}")
    if not today_path.exists():
        raise FileNotFoundError(f"오늘 snapshot 파일이 없습니다: {today_path}")

    prev_df = pd.read_csv(prev_path, encoding="utf-8-sig")
    today_df = pd.read_csv(today_path, encoding="utf-8-sig")

    compared = compare_holdings(today_df, prev_df)

    html_body = build_compare_report_html(
        compared,
        title="TIME 미국나스닥100 액티브 구성종목 변화"
    )
    text_body = build_compare_report_text(compared)

    ai_payload = build_compare_ai_payload(compared)
    logger.info(f"[EMAIL TEST] AI payload summary keys: {list(ai_payload.keys())}")

    send_html_email(
        subject="[ETF 테스트] TIME 미국나스닥100 액티브 구성종목 변화",
        html_body=html_body,
        text_body=text_body,
    )


if __name__ == "__main__":
    main()
from __future__ import annotations

import json

import pandas as pd

from compare import compare_holdings
from paths import ROOT_DIR, SNAPSHOTS_DIR
from reporter import build_compare_report_html


def main() -> None:
    prev_path = SNAPSHOTS_DIR / "2026-03-26.csv"
    today_path = SNAPSHOTS_DIR / "2026-03-27.csv"
    ai_analysis_path = ROOT_DIR / "temp" / "gemini_analysis_preview.json"

    prev_df = pd.read_csv(prev_path, encoding="utf-8-sig")
    today_df = pd.read_csv(today_path, encoding="utf-8-sig")

    compared = compare_holdings(today_df, prev_df)

    ai_analysis = None
    if ai_analysis_path.exists():
        ai_analysis = json.loads(ai_analysis_path.read_text(encoding="utf-8"))

    html_report = build_compare_report_html(
        compared,
        title="TIME 미국나스닥100 액티브 구성종목 변화",
        ai_analysis=ai_analysis,
    )

    output_path = ROOT_DIR / "temp" / "compare_report_preview.html"
    output_path.write_text(html_report, encoding="utf-8")

    print(f"HTML 리포트 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
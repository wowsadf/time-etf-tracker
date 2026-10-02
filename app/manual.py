"""수동 점검 도구. email 명령 외에는 메일이나 운영 state를 변경하지 않는다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_analyzer import analyze_compare_payload
from compare import compare_holdings
from config import REPORT_TITLE
from email_sender import send_html_email
from fetcher import download_excel_with_retry
from holdings_parser import load_holdings_excel
from logging_utils import setup_logger
from paths import TEMP_DIR
from reporter import build_compare_ai_payload, build_compare_report_html, build_compare_report_text
from snapshot_manager import get_latest_two_snapshot_paths, load_snapshot_df, save_snapshot
from validator import validate_holdings

logger = setup_logger()


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF 수동 점검: 운영 state는 변경하지 않습니다")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ["compare", "preview", "analyze", "email"]:
        sub = commands.add_parser(command)
        sub.add_argument("--previous", type=Path)
        sub.add_argument("--current", type=Path)
        if command in {"preview", "analyze", "email"}:
            sub.add_argument("--provider", choices=["auto", "gemini", "glm"], default="auto")
        if command == "preview":
            sub.add_argument("--ai", action="store_true", help="선택한 두 스냅샷으로 AI를 새로 호출")
        if command == "email":
            sub.add_argument("--no-ai", action="store_true")
    commands.add_parser("fetch", help="최신 엑셀을 내려받아 검증만 수행")
    importer = commands.add_parser("import", help="엑셀 한 개를 CSV로 저장; 기존 파일을 덮어쓰지 않음")
    importer.add_argument("--input", type=Path, required=True)
    importer.add_argument("--date", help="YYYY-MM-DD; 생략하면 엑셀 파일명 사용")
    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    if args.command in {"fetch", "import"}:
        path = (download_excel_with_retry(TEMP_DIR / "manual_latest.xlsx")
                if args.command == "fetch" else args.input)
        data = load_holdings_excel(path)
        validate_holdings(data)
        logger.info("[MANUAL] validated rows=%s", len(data))
        if args.command == "import":
            saved = save_snapshot(data, args.date or path.stem)
            logger.info("[MANUAL] snapshot saved: %s (state unchanged)", saved)
        return

    if (args.previous is None) != (args.current is None):
        parser.error("--previous와 --current는 함께 지정해야 합니다")
    previous, current = ((args.previous, args.current) if args.previous is not None
                         else get_latest_two_snapshot_paths())
    if previous.resolve() == current.resolve():
        parser.error("서로 다른 스냅샷 두 개를 선택하세요")
    prev_df, current_df = load_snapshot_df(previous), load_snapshot_df(current)
    validate_holdings(prev_df)
    validate_holdings(current_df)
    compared = compare_holdings(current_df, prev_df)
    labels = {"previous_label": previous.stem, "current_label": current.stem}
    logger.info("[MANUAL] comparing %s -> %s", previous.name, current.name)
    if args.command == "compare":
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        compared.to_csv(TEMP_DIR / "compare_preview.csv", index=False, encoding="utf-8-sig")
        print(build_compare_report_text(compared, **labels))
        return

    wants_ai = (args.command == "analyze" or
                (args.command == "email" and not args.no_ai) or
                (args.command == "preview" and args.ai))
    analysis = None
    if wants_ai:
        payload = build_compare_ai_payload(compared, **labels)
        analysis = analyze_compare_payload(payload, provider=args.provider)
        logger.info("[MANUAL] AI validated: %s / %s", analysis["provider"], analysis["model"])
    body = build_compare_report_html(compared, ai_analysis=analysis, **labels)
    if args.command == "email":
        send_html_email(
            subject=f"[ETF 테스트] {REPORT_TITLE} | {previous.stem} → {current.stem}",
            html_body=body,
            text_body=build_compare_report_text(compared, ai_analysis=analysis, **labels),
        )
        return
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TEMP_DIR / "report_preview.html"
    target.write_text(body, encoding="utf-8")
    if analysis:
        (TEMP_DIR / "ai_analysis_preview.json").write_text(
            json.dumps({"comparison": labels, "analysis": analysis}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    logger.info("[MANUAL] HTML preview: %s", target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # API exceptions may include request details; never print keys or raw responses.
        logger.error("[MANUAL] failed (%s). 입력 파일·환경변수·API 권한을 확인하세요.", type(exc).__name__)
        raise SystemExit(1) from None

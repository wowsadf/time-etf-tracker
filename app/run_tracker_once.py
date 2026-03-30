from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_analyzer_gemini import analyze_compare_payload_with_gemini
from compare import compare_holdings
from config import EMAIL_SUBJECT_PREFIX, REPORT_TITLE
from email_sender import send_html_email
from exceptions import DataNotReadyError
from fetcher import download_excel_with_retry
from holdings_parser import load_holdings_excel
from logging_utils import setup_logger
from reporter import (
    build_compare_ai_payload,
    build_compare_report_html,
    build_compare_report_text,
)
from snapshot_manager import compute_snapshot_hash, load_snapshot_df, save_snapshot
from state_manager import load_state, save_state
from validator import validate_holdings

logger = setup_logger()


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def make_email_subject(snapshot_path: Path) -> str:
    return f"{EMAIL_SUBJECT_PREFIX} {REPORT_TITLE} | {snapshot_path.stem}"


def clear_pending_report_fields(state: dict) -> None:
    state["pending_report_hash"] = None
    state["pending_snapshot_path"] = None
    state["pending_previous_snapshot_path"] = None


def try_build_ai_analysis(compared_df):
    try:
        ai_payload = build_compare_ai_payload(compared_df)
        ai_result = analyze_compare_payload_with_gemini(ai_payload)
        return ai_result.model_dump()
    except Exception as exc:
        logger.warning(f"[AI] analysis skipped due to error: {exc}")
        return None


def send_report(prev_snapshot_path: Path, current_snapshot_path: Path) -> None:
    prev_df = load_snapshot_df(prev_snapshot_path)
    current_df = load_snapshot_df(current_snapshot_path)

    compared = compare_holdings(current_df, prev_df)
    ai_analysis = try_build_ai_analysis(compared)

    html_body = build_compare_report_html(
        compared,
        title=REPORT_TITLE,
        ai_analysis=ai_analysis,
    )
    text_body = build_compare_report_text(compared)

    send_html_email(
        subject=make_email_subject(current_snapshot_path),
        html_body=html_body,
        text_body=text_body,
    )


def retry_pending_report_if_needed(state: dict, current_hash: str) -> bool:
    pending_hash = state.get("pending_report_hash")
    pending_snapshot_path = state.get("pending_snapshot_path")
    pending_previous_snapshot_path = state.get("pending_previous_snapshot_path")

    if pending_hash != current_hash:
        return False
    if not pending_snapshot_path or not pending_previous_snapshot_path:
        return False

    current_path = Path(pending_snapshot_path)
    prev_path = Path(pending_previous_snapshot_path)

    if not current_path.exists() or not prev_path.exists():
        raise FileNotFoundError("pending report용 snapshot 파일이 존재하지 않습니다")

    logger.info("[TRACKER] pending report detected. retrying report send.")
    send_report(prev_path, current_path)

    state["last_reported_hash"] = pending_hash
    state["last_reported_snapshot_path"] = str(current_path)
    state["last_reported_at"] = now_kst_iso()
    state["last_attempt_status"] = "reported_after_retry"
    state["last_attempt_message"] = "이전 실패 건 보고 재시도 성공"
    clear_pending_report_fields(state)
    save_state(state)
    return True


def main() -> None:
    state = load_state()

    try:
        download_path = download_excel_with_retry()
        df = load_holdings_excel(download_path)
        validate_holdings(df)

        snapshot_hash = compute_snapshot_hash(df)

        last_snapshot_hash = state.get("last_snapshot_hash")
        last_snapshot_path_str = state.get("last_snapshot_path")

        # 이미 본 유효 스냅샷과 동일
        if snapshot_hash == last_snapshot_hash:
            if retry_pending_report_if_needed(state, snapshot_hash):
                return

            logger.info("[TRACKER] duplicate valid snapshot detected. skipped.")
            state["last_attempt_status"] = "duplicate_valid_snapshot"
            state["last_attempt_message"] = "직전 유효 스냅샷과 내용이 동일합니다"
            save_state(state)
            return

        previous_snapshot_path = Path(last_snapshot_path_str) if last_snapshot_path_str else None

        saved_path = save_snapshot(df, snapshot_date=now_kst_iso()[:10])

        state["last_snapshot_hash"] = snapshot_hash
        state["last_snapshot_path"] = str(saved_path)
        state["last_snapshot_saved_at"] = now_kst_iso()

        # 첫 유효 스냅샷이면 저장만 하고 비교/보고는 하지 않음
        if previous_snapshot_path is None:
            state["last_attempt_status"] = "saved_initial_snapshot"
            state["last_attempt_message"] = "첫 유효 스냅샷 저장 완료. 비교 대상이 없어 보고는 생략합니다"
            clear_pending_report_fields(state)
            save_state(state)

            logger.info(f"[TRACKER] initial snapshot saved: {saved_path}")
            return

        if not previous_snapshot_path.exists():
            raise FileNotFoundError(f"직전 유효 스냅샷 파일이 없습니다: {previous_snapshot_path}")

        # 새 유효 스냅샷 저장 후 보고 전 상태 기록
        state["pending_report_hash"] = snapshot_hash
        state["pending_snapshot_path"] = str(saved_path)
        state["pending_previous_snapshot_path"] = str(previous_snapshot_path)
        state["last_attempt_status"] = "saved_pending_report"
        state["last_attempt_message"] = "새 유효 스냅샷 저장 완료. 이제 비교/보고를 진행합니다"
        save_state(state)

        send_report(previous_snapshot_path, saved_path)

        state["last_reported_hash"] = snapshot_hash
        state["last_reported_snapshot_path"] = str(saved_path)
        state["last_reported_at"] = now_kst_iso()
        state["last_attempt_status"] = "reported"
        state["last_attempt_message"] = "새 유효 스냅샷 비교 및 이메일 발송 완료"
        clear_pending_report_fields(state)
        save_state(state)

        logger.info(f"[TRACKER] report sent successfully for snapshot: {saved_path}")

    except DataNotReadyError as exc:
        logger.info(f"[TRACKER] skip: {exc}")
        state["last_attempt_status"] = "empty_template"
        state["last_attempt_message"] = str(exc)
        save_state(state)
        return

    except Exception as exc:
        state["last_attempt_status"] = "error"
        state["last_attempt_message"] = str(exc)
        save_state(state)
        raise


if __name__ == "__main__":
    main()
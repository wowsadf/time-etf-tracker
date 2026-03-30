from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from exceptions import DataNotReadyError
from fetcher import download_excel_with_retry
from holdings_parser import load_holdings_excel
from logging_utils import setup_logger
from snapshot_manager import compute_snapshot_hash, save_snapshot
from state_manager import load_state, save_state
from validator import validate_holdings

logger = setup_logger()


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def main() -> None:
    state = load_state()

    path = download_excel_with_retry()
    df = load_holdings_excel(path)

    try:
        validate_holdings(df)
    except DataNotReadyError as exc:
        logger.info(f"[COLLECT] skip: {exc}")
        state["last_attempt_status"] = "empty_template"
        state["last_attempt_message"] = str(exc)
        save_state(state)
        return

    snapshot_hash = compute_snapshot_hash(df)

    if state.get("last_success_hash") == snapshot_hash:
        logger.info("[COLLECT] duplicate valid snapshot detected. save skipped.")
        state["last_attempt_status"] = "duplicate_valid_snapshot"
        state["last_attempt_message"] = "직전 유효 스냅샷과 내용이 동일합니다"
        save_state(state)
        return

    saved_path = save_snapshot(df)

    state["last_attempt_status"] = "saved"
    state["last_attempt_message"] = "새 유효 스냅샷 저장 완료"
    state["last_success_hash"] = snapshot_hash
    state["last_success_snapshot"] = str(saved_path)
    state["last_success_saved_at"] = now_kst_iso()
    save_state(state)

    logger.info(f"[COLLECT] snapshot saved: {saved_path}")
    logger.info(f"[COLLECT] rows={len(df)}")


if __name__ == "__main__":
    main()
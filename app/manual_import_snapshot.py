from __future__ import annotations

from pathlib import Path

from holdings_parser import load_holdings_excel
from logging_utils import setup_logger
from paths import MANUAL_INPUTS_DIR
from snapshot_manager import compute_snapshot_hash, save_snapshot_as
from validator import validate_holdings

logger = setup_logger()


def main() -> None:
    input_files = sorted(MANUAL_INPUTS_DIR.glob("*.xlsx"))

    if len(input_files) < 2:
        raise RuntimeError("manual_inputs 폴더에 xlsx 파일이 최소 2개 있어야 합니다")

    logger.info(f"[IMPORT] found {len(input_files)} xlsx files")

    for file_path in input_files:
        logger.info(f"[IMPORT] reading file: {file_path.name}")

        df = load_holdings_excel(file_path)
        validate_holdings(df)

        snapshot_name = f"{file_path.stem}.csv"
        saved_path = save_snapshot_as(df, snapshot_name)
        snapshot_hash = compute_snapshot_hash(df)

        logger.info(f"[IMPORT] saved snapshot: {saved_path.name}")
        logger.info(f"[IMPORT] rows={len(df)}")
        logger.info(f"[IMPORT] hash={snapshot_hash}")


if __name__ == "__main__":
    main()
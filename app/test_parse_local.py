from __future__ import annotations

from fetcher import download_excel_with_retry
from holdings_parser import load_holdings_excel
from validator import validate_holdings
from logging_utils import setup_logger

logger = setup_logger()


def main() -> None:
    path = download_excel_with_retry()
    df = load_holdings_excel(path)
    validate_holdings(df)

    logger.info("[TEST] parsing and validation succeeded")
    logger.info(f"[TEST] top 10 rows preview:\n{df.head(10).to_string(index=False)}")


if __name__ == "__main__":
    main()
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from config import DOWNLOAD_MAX_RETRIES, DOWNLOAD_TIMEOUT_SEC, ETF_DOWNLOAD_URL
from logging_utils import setup_logger
from paths import LATEST_XLSX_PATH

logger = setup_logger()


def download_excel_with_retry(
    save_path: Path = LATEST_XLSX_PATH,
    max_retries: int | None = None,
    timeout: int | None = None,
) -> Path:
    max_retries = max_retries or DOWNLOAD_MAX_RETRIES or 3
    timeout = timeout or DOWNLOAD_TIMEOUT_SEC or 30

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        )
    }

    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[FETCH] download attempt {attempt}/{max_retries}")

            response = requests.get(
                ETF_DOWNLOAD_URL,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()

            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(response.content)

            file_size = save_path.stat().st_size
            logger.info(f"[FETCH] downloaded file size={file_size} bytes")

            if file_size < 1024:
                raise ValueError(f"다운로드 파일 크기가 너무 작습니다: {file_size} bytes")

            pd.read_excel(save_path, nrows=5)
            logger.info(f"[FETCH] excel validation passed: {save_path}")
            return save_path

        except Exception as exc:
            last_exception = exc
            logger.warning(f"[FETCH] attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                time.sleep(2)

    raise RuntimeError(f"엑셀 다운로드 실패: {last_exception}")
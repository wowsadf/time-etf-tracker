from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pandas as pd
import requests

from config import DOWNLOAD_MAX_RETRIES, DOWNLOAD_TIMEOUT_SEC, ETF_DOWNLOAD_URL
from logging_utils import setup_logger
from paths import LATEST_XLSX_PATH

logger = setup_logger()

MAX_DOWNLOAD_SIZE_BYTES = 20 * 1024 * 1024


def download_excel_with_retry(
    save_path: Path = LATEST_XLSX_PATH,
    max_retries: int | None = None,
    timeout: int | None = None,
) -> Path:
    max_retries = max_retries if max_retries is not None else (DOWNLOAD_MAX_RETRIES or 3)
    timeout = timeout if timeout is not None else (DOWNLOAD_TIMEOUT_SEC or 30)

    if max_retries < 1:
        raise ValueError("max_retries는 1 이상이어야 합니다")
    if timeout < 1:
        raise ValueError("timeout은 1 이상이어야 합니다")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        )
    }

    last_exception: Exception | None = None
    temp_path: Path | None = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[FETCH] download attempt {attempt}/{max_retries}")

            response = requests.get(
                ETF_DOWNLOAD_URL,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise ValueError(f"엑셀 대신 HTML 응답을 받았습니다: {content_type}")

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOWNLOAD_SIZE_BYTES:
                raise ValueError(f"다운로드 파일이 너무 큽니다: {content_length} bytes")

            if len(response.content) > MAX_DOWNLOAD_SIZE_BYTES:
                raise ValueError(f"다운로드 파일이 너무 큽니다: {len(response.content)} bytes")

            save_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = save_path.with_name(f".{save_path.name}.{uuid4().hex}.tmp")
            temp_path.write_bytes(response.content)

            file_size = temp_path.stat().st_size
            logger.info(f"[FETCH] downloaded file size={file_size} bytes")

            if file_size < 1024:
                raise ValueError(f"다운로드 파일 크기가 너무 작습니다: {file_size} bytes")

            pd.read_excel(temp_path, nrows=5)
            temp_path.replace(save_path)
            temp_path = None
            logger.info(f"[FETCH] excel validation passed: {save_path}")
            return save_path

        except Exception as exc:
            last_exception = exc
            logger.warning(f"[FETCH] attempt {attempt} failed: {exc}")
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
                temp_path = None
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 10))

    raise RuntimeError(f"엑셀 다운로드 실패: {last_exception}")

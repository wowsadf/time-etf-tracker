from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"필수 환경변수가 없습니다: {name}")
    return value


def get_int_env(name: str, required: bool = False, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if required and default is None:
            raise RuntimeError(f"필수 환경변수가 없습니다: {name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"정수 환경변수 형식이 잘못되었습니다: {name}={raw}") from exc


SMTP_USER = get_env("SMTP_USER", required=False)
SMTP_PASS = get_env("SMTP_PASS", required=False)
TO_EMAIL = get_env("TO_EMAIL", required=False)

ETF_DOWNLOAD_URL = get_env(
    "ETF_DOWNLOAD_URL",
    required=False,
    default="https://timeetf.co.kr/pdf_excel.php?idx=2&",
)

REPORT_TITLE = get_env(
    "REPORT_TITLE",
    required=False,
    default="TIME 미국나스닥100 액티브 구성종목 변화",
)

EMAIL_SUBJECT_PREFIX = get_env(
    "EMAIL_SUBJECT_PREFIX",
    required=False,
    default="[ETF]",
)

DOWNLOAD_TIMEOUT_SEC = get_int_env(
    "DOWNLOAD_TIMEOUT_SEC",
    required=False,
    default=30,
)

DOWNLOAD_MAX_RETRIES = get_int_env(
    "DOWNLOAD_MAX_RETRIES",
    required=False,
    default=3,
)

GEMINI_API_KEY = get_env("GEMINI_API_KEY", required=False)
GEMINI_MODEL = get_env("GEMINI_MODEL", required=False, default="gemini-3.1-flash-lite-preview")
GEMINI_FALLBACK_MODEL = get_env("GEMINI_FALLBACK_MODEL", required=False, default="gemini-3-flash-preview")
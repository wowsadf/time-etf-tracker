from __future__ import annotations

import json
import random
import time
from typing import Literal

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field

from config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL
from logging_utils import setup_logger

logger = setup_logger()


class ScenarioItem(BaseModel):
    thesis: str = Field(description="시나리오 핵심 문장")
    confidence: Literal["low", "medium", "high"] = Field(description="시나리오 신뢰 수준")
    implications: list[str] = Field(description="이 시나리오가 맞다면 확인될 후속 변화 2~3개")


class RiskItem(BaseModel):
    level: Literal["low", "medium", "high"] = Field(description="리스크 수준")
    issue: str = Field(description="핵심 리스크")
    evidence: str = Field(description="입력 데이터 근거")


class WatchItem(BaseModel):
    name: str = Field(description="종목명 또는 관찰 대상")
    direction: Literal["positive", "negative", "neutral"] = Field(description="현재 해석 방향")
    reason: str = Field(description="왜 봐야 하는지")
    next_check: str = Field(description="다음에 확인할 포인트")


class GeminiAnalysisResult(BaseModel):
    one_line_take: str = Field(description="가장 중요한 한 줄 결론")
    core_view: str = Field(description="핵심 해석 4~6문장")
    what_changed_in_plain_english: list[str] = Field(description="이번 리밸런싱에서 구조적으로 달라진 점 3개")
    manager_intent: str = Field(description="운용 의도에 대한 가장 그럴듯한 해석 1문단")
    base_case: ScenarioItem = Field(description="기본 시나리오")
    bull_case: ScenarioItem = Field(description="낙관 시나리오")
    bear_case: ScenarioItem = Field(description="비관 시나리오")
    key_risks: list[RiskItem] = Field(description="중요 리스크 3개")
    what_to_watch_next: list[str] = Field(description="다음 확인 포인트 4개")
    watchlist: list[WatchItem] = Field(description="중점 관찰 종목 또는 항목 4개")


SYSTEM_PROMPT = """
당신은 ETF 리밸런싱을 해석하는 전문 애널리스트입니다.

입력 JSON은 전일 대비 구성 종목 변화, 전체 종목 변화, 포트폴리오 수준 지표를 담고 있습니다.

반드시 지켜야 할 규칙:
1. 입력 JSON에 있는 숫자와 항목만 근거로 사용하세요.
2. 표 내용을 길게 재진술하지 마세요.
3. 핵심은 '무엇이 바뀌었는가'보다 '왜 이렇게 바뀌었는가'와 '이 변화가 무엇을 시사하는가'입니다.
4. 가격 목표나 단정적 수익률 예측은 금지합니다.
5. 대신 운용 의도, 포지셔닝 변화, 시나리오, 리스크, 후속 체크포인트를 제시하세요.
6. 과장, 홍보, 감탄, 상투적 표현을 쓰지 마세요.
7. 중복을 피하고, 짧고 압축적으로 쓰세요.
8. one_line_take는 한 문장만 쓰세요.
9. what_changed_in_plain_english는 정확히 3개만 쓰세요.
10. key_risks는 정확히 3개만 쓰세요.
11. what_to_watch_next는 정확히 4개만 쓰세요.
12. watchlist는 정확히 4개만 쓰세요.
13. 출력은 반드시 지정된 JSON 스키마만 반환하세요.
""".strip()


def _build_user_prompt(payload: dict) -> str:
    return f"""
아래 JSON은 ETF 구성 종목 변화 데이터입니다.

당신의 임무:
- 리밸런싱의 의도를 해석하세요.
- 전체 포트폴리오 구조가 어떻게 바뀌었는지 설명하세요.
- 상위 몇 종목의 변화보다 전체 breadth, concentration, asset mix 변화를 우선적으로 해석하세요.
- 가격 방향을 단정하지 말고, 시나리오와 확인 포인트 중심으로 정리하세요.
- 답변은 짧고 단단하게 쓰세요. 같은 말을 반복하지 마세요.

입력 JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def _call_gemini_once(client: genai.Client, model_name: str, payload: dict) -> GeminiAnalysisResult:
    user_prompt = _build_user_prompt(payload)

    logger.info(f"[AI] sending payload to Gemini model={model_name}")

    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=GeminiAnalysisResult,
        ),
    )

    logger.info(f"[AI] Gemini response received from model={model_name}")

    if getattr(response, "parsed", None) is not None:
        return response.parsed

    return GeminiAnalysisResult.model_validate_json(response.text)


def _call_with_retry(
    client: genai.Client,
    model_name: str,
    payload: dict,
    max_retries: int = 4,
) -> GeminiAnalysisResult:
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return _call_gemini_once(client, model_name, payload)

        except APIError as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)

            if status_code in (429, 500, 503):
                sleep_seconds = (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    f"[AI] retryable error from {model_name}: status={status_code}, "
                    f"attempt={attempt}/{max_retries}, sleep={sleep_seconds:.2f}s"
                )
                if attempt < max_retries:
                    time.sleep(sleep_seconds)
                    continue

            raise

        except Exception as exc:
            last_error = exc
            raise

    raise RuntimeError(f"Gemini 호출 실패: {last_error}")


def analyze_compare_payload_with_gemini(payload: dict) -> GeminiAnalysisResult:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다")

    client = genai.Client(api_key=GEMINI_API_KEY)

    primary_model = GEMINI_MODEL or "gemini-3-flash-preview"
    fallback_model = GEMINI_FALLBACK_MODEL or "gemini-3.1-flash-lite-preview"

    try:
        return _call_with_retry(client, primary_model, payload)
    except APIError as exc:
        status_code = getattr(exc, "status_code", None)

        if status_code in (429, 500, 503) and fallback_model != primary_model:
            logger.warning(
                f"[AI] primary model failed with status={status_code}. "
                f"fallback to {fallback_model}"
            )
            return _call_with_retry(client, fallback_model, payload)

        raise
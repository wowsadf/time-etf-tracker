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
    implications: list[str] = Field(
        description="이 시나리오가 맞다면 확인될 후속 변화 3개",
        min_length=3,
        max_length=3,
    )


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
    core_view: str = Field(description="사실, 해석, 불확실성을 구분한 핵심 해석 7~10문장")
    what_changed_in_plain_english: list[str] = Field(
        description="이번 변화에서 구조적으로 달라진 점 4개",
        min_length=4,
        max_length=4,
    )
    evidence_based_observations: list[str] = Field(
        description="입력 데이터의 구체적 수치를 인용한 핵심 관찰 5개",
        min_length=5,
        max_length=5,
    )
    portfolio_implications: list[str] = Field(
        description="집중도, 자산배분, 위험 노출 관점의 의미 4개",
        min_length=4,
        max_length=4,
    )
    manager_intent: str = Field(description="수량 변화로 확인 가능한 운용 의도 가설 또는 확인 불가 설명 2개 문단 분량")
    base_case: ScenarioItem = Field(description="기본 시나리오")
    bull_case: ScenarioItem = Field(description="낙관 시나리오")
    bear_case: ScenarioItem = Field(description="비관 시나리오")
    key_risks: list[RiskItem] = Field(description="중요 리스크 4개", min_length=4, max_length=4)
    what_to_watch_next: list[str] = Field(description="다음 확인 포인트 5개", min_length=5, max_length=5)
    watchlist: list[WatchItem] = Field(
        description="중점 관찰 종목 또는 항목 5개",
        min_length=5,
        max_length=5,
    )
    data_limitations: list[str] = Field(
        description="이번 데이터만으로 확정할 수 없는 한계 2개",
        min_length=2,
        max_length=2,
    )


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
FALLBACK_STATUS_CODES = {403, 404, 429, 500, 502, 503, 504}


SYSTEM_PROMPT = """
당신은 ETF 구성 변화를 해석하는 전문 애널리스트입니다.

입력 JSON은 전일 대비 구성 종목 변화, 전체 종목 변화, 포트폴리오 수준 지표를 담고 있습니다.

반드시 지켜야 할 규칙:
1. 입력 JSON에 있는 숫자와 항목만 근거로 사용하세요.
2. 표 내용을 길게 재진술하지 마세요.
3. quantity_status와 quantity_diff는 실제 보유 수량 변화의 단서입니다.
4. 수량이 변하지 않고 비중만 변한 종목은 매수·매도나 운용 의도로 단정하지 마세요. 가격, 환율, 다른 자산가치 변화에 따른 비중 표류일 수 있다고 설명하세요.
5. 운용 의도는 수량 변화가 확인된 경우에만 데이터 기반 가설로 제시하고, 사실처럼 단정하지 마세요.
6. 신규·편출·수량 변화와 단순 비중 변화를 명확히 구분하세요.
7. 가격 목표나 단정적 수익률 예측은 금지합니다.
8. 외부 뉴스나 시장 상황을 입력에 없는 사실처럼 추가하지 마세요.
9. 과장, 홍보, 감탄, 상투적 표현을 쓰지 마세요.
10. 중복은 피하되, 각 판단의 데이터 근거와 불확실성을 충분히 설명하세요.
11. one_line_take는 한 문장만 쓰세요.
12. core_view는 7~10문장으로 작성하고 사실, 해석, 불확실성을 구분하세요.
13. what_changed_in_plain_english는 정확히 4개만 쓰세요.
14. evidence_based_observations는 정확히 5개이며 가능한 경우 종목명, 수량, 비중, 순위 수치를 포함하세요.
15. portfolio_implications는 정확히 4개만 쓰세요.
16. 각 시나리오의 implications는 정확히 3개만 쓰세요.
17. key_risks는 정확히 4개만 쓰세요.
18. what_to_watch_next와 watchlist는 각각 정확히 5개만 쓰세요.
19. data_limitations는 정확히 2개만 쓰세요.
20. 출력은 반드시 지정된 JSON 스키마만 반환하세요.
""".strip()


def _build_user_prompt(payload: dict) -> str:
    return f"""
아래 JSON은 ETF 구성 종목 변화 데이터입니다.

당신의 임무:
- 실제 수량 변화가 있을 때에만 가능한 운용 의도를 가설로 해석하세요.
- 전체 포트폴리오 구조가 어떻게 바뀌었는지 설명하세요.
- 실제 수량 변화가 있었는지 먼저 확인하고, 수량 변화가 없으면 비중 변화를 매매로 해석하지 마세요.
- 상위 몇 종목의 변화보다 전체 breadth, concentration, asset mix 변화를 우선적으로 해석하세요.
- 가격 방향을 단정하지 말고, 시나리오와 확인 포인트 중심으로 정리하세요.
- 핵심 판단마다 입력 JSON의 종목명·수량·비중·순위 중 사용 가능한 구체적 근거를 연결하세요.
- 관찰된 사실, 가능한 해석, 데이터만으로 확정할 수 없는 부분을 명확히 구분하세요.
- 다음 스냅샷에서 무엇이 확인되면 각 가설이 강화되거나 약화되는지 구체적으로 적으세요.
- 충분히 상세하게 쓰되 같은 내용을 다른 필드에서 반복하지 마세요.

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
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            max_output_tokens=4096,
            temperature=0.2,
        ),
    )

    logger.info(f"[AI] Gemini response received from model={model_name}")

    if getattr(response, "parsed", None) is not None:
        return GeminiAnalysisResult.model_validate(response.parsed)

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

            if status_code in RETRYABLE_STATUS_CODES:
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

    primary_model = GEMINI_MODEL
    fallback_model = GEMINI_FALLBACK_MODEL

    try:
        return _call_with_retry(client, primary_model, payload)
    except APIError as exc:
        status_code = getattr(exc, "status_code", None)

        if status_code in FALLBACK_STATUS_CODES and fallback_model != primary_model:
            logger.warning(
                f"[AI] primary model failed with status={status_code}. "
                f"fallback to {fallback_model}"
            )
            return _call_with_retry(client, fallback_model, payload)

        raise

    except (ValueError, TypeError) as exc:
        if fallback_model == primary_model:
            raise
        logger.warning(
            f"[AI] primary model returned an invalid structured response: {exc}. "
            f"fallback to {fallback_model}"
        )
        return _call_with_retry(client, fallback_model, payload)

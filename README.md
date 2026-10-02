# TIME ETF Tracker

TIME 미국나스닥100 액티브 ETF의 공개 구성종목을 직전 정상 스냅샷과 비교하고, HTML 메일과 AI 보조 해석으로 전달합니다. 계산은 Python, 해석만 AI가 담당합니다.

## 동작과 보존 정책

1. GitHub Actions가 4시간마다 실행합니다.
2. 이전 메일 발송 실패 건이 있으면 저장된 두 스냅샷으로 재시도합니다.
3. 최신 Excel을 다운로드하고 필수 컬럼·종목 키·숫자·비중 합계를 검증합니다.
4. 헤더만 있는 빈 템플릿과 직전 정상 데이터와 동일한 파일은 정상 스킵합니다.
5. 새 데이터는 CSV로 저장하고 구성 변화·수량 증감·TOP10 순위를 계산합니다.
6. Gemini → 실패 시 GLM 순으로 AI 분석을 시도합니다. 둘 다 실패해도 기본 리포트는 발송합니다.
7. 이메일 성공 여부를 state에 기록하고 snapshots/state를 저장소에 반영합니다.

첫 정상 데이터는 기준점으로만 저장합니다. 같은 날짜에 데이터가 다시 바뀌면 기존 CSV를 덮어쓰지 않고 `날짜_시각_해시.csv`로 보존합니다. state 손상이나 기준 파일 누락은 조용히 초기화하지 않고 오류로 처리합니다.

수량 변화는 실제 매매뿐 아니라 **ETF 설정·환매, 액면분할 등 기업행동** 때문일 수 있습니다. 비중 변화는 가격·환율 등에 따라서도 생깁니다. 이 데이터만으로 운용 의도나 실제 거래를 확정할 수 없습니다. 선물 평가액 비중도 실제 시장 노출을 뜻하지 않습니다.

## 이메일 구성

- 비교 날짜와 신규 편입·편출·기존 수량 증가·감소 요약
- 변화한 주식 전체 목록: 10개로 잘라 중요한 종목을 누락하지 않음
- 데이터 근거, 운용 의도 가설, 포트폴리오 영향, 시나리오, 리스크, 관찰 항목
- 현재 TOP10, TOP10 이탈, 보조 지표인 주요 비중 변화 최대 5개
- 주식 외 자산 변화와 분석 한계

모바일을 고려한 3열 표, 2×2 요약 카드, 이메일용 table 레이아웃을 사용합니다. 종목명과 AI 문장은 HTML 이스케이프합니다. 실제 사용한 AI 제공자와 모델을 메일에 표시합니다. 과거 분석 JSON을 다른 날짜의 메일에 재사용하지 않습니다.

메일 상단 사실 요약은 Python 계산 결과만 사용합니다. AI에는 수량 변화 사실 확인표도 요구하며 누락·추가 종목·잘못된 상태나 수량이 있으면 분석을 거부합니다. 이 검산이 자유 서술 전체의 정확성을 보장하지는 않습니다. AI 해석은 참고 가설로 읽고 숫자 표를 우선하세요.

## 파일 구조

```text
.github/workflows/etf-tracker.yml  자동 실행·테스트·상태 저장
app/
  run_tracker_once.py            운영 진입점
  manual.py                      수동 비교·미리보기·AI·메일·가져오기
  ai_analyzer.py                 Gemini primary / GLM fallback
  reporter.py                    AI 입력 데이터·HTML·텍스트 리포트
  compare.py                     수량·비중·순위 비교
  fetcher.py                     다운로드·크기 제한·재시도
  holdings_parser.py             Excel 정규화
  validator.py                   정상 데이터 검증
  snapshot_manager.py            내용 해시·덮어쓰기 없는 CSV 저장
  state_manager.py               상태 검증·원자적 저장
  email_sender.py                 Gmail SMTP
  config.py / paths.py            환경변수·경로
  logging_utils.py / exceptions.py
tests/test_core.py               외부 API/SMTP 없는 회귀 테스트
snapshots/                      정상 CSV 기록 (삭제하지 않기)
state/tracker_state.json          운영 기준점 (삭제하지 않기)
manual_inputs/ / temp/            로컬 원본·미리보기 (Git 제외)
.env.example / requirements.txt
```

기존의 중복 수동 실행 스크립트는 `manual.py`로 통합했습니다. 수동 도구는 운영 state를 변경하지 않습니다.

## 설치와 로컬 설정

Python 3.13을 사용합니다. PowerShell에서:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

처음 설정할 때만 `.env.example`을 `.env`로 복사하고 값을 채우세요. 이미 있는 `.env`는 덮어쓰지 마세요.

| 환경변수 | 용도 |
|---|---|
| SMTP_USER / SMTP_PASS / TO_EMAIL | Gmail 주소 / 앱 비밀번호 / 수신 주소 |
| GEMINI_API_KEY | Google AI Studio 키 |
| GEMINI_MODEL | 기본 `gemini-3.8-flash` |
| GLM_API_KEY | GLM fallback 키 |
| GLM_MODEL | 기본 `glm-4.7-flash` |
| GLM_BASE_URL | 기본 `https://open.bigmodel.cn/api/paas/v4` |
| AI_TIMEOUT_SEC | AI 요청 타임아웃, 기본 90초 |
| ETF_DOWNLOAD_URL | 구성종목 Excel 주소 |
| DOWNLOAD_TIMEOUT_SEC / DOWNLOAD_MAX_RETRIES | 기본 30초 / 3회 |
| REPORT_TITLE / EMAIL_SUBJECT_PREFIX | 리포트 제목 / 메일 접두사 |

키를 코드·README·워크플로에 직접 넣지 않습니다. `.env`는 Git에서 제외합니다. 외부 API에는 공개 ETF 데이터만 보내며 API 키나 메일 설정을 분석 입력에 넣지 않습니다.

## AI 모델과 무료 이용

2026-10-02 기준 primary는 **Gemini 3.8 Flash**, fallback은 **GLM-4.7-Flash**입니다. GLM의 더 최신 5.3 계열과 FlashX는 무료 모델이 아닙니다. 무료 모델도 요청 한도와 계정별 이용 권한이 있습니다.

- [Gemini 3.8 Flash 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Gemini 가격과 무료 티어](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini 요청 한도](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Z.AI GLM 가격표](https://docs.z.ai/guides/overview/pricing)

BigModel 키와 Z.AI 키는 발급 플랫폼에 맞는 주소를 사용해야 합니다. Z.AI에서 발급했다면 `GLM_BASE_URL=https://api.z.ai/api/paas/v4`로 변경하세요. 키를 여러 서버에 보내 보며 자동 탐색하지 않습니다. 선택한 플랫폼의 요금표와 모델 권한도 확인하세요.

Gemini 429/권한/응답 검증 실패는 GLM으로 전환합니다. 일시적인 5xx만 제한적으로 재시도합니다. 두 제공자의 출력은 같은 스키마로 검증하며 잘린 응답은 사용하지 않습니다. 무료 API의 데이터 처리 정책을 확인하고 민감한 자료를 입력하지 마세요.

## 안전한 수동 점검

```powershell
python -m unittest discover -s tests -v
python app/manual.py preview
```

미리보기는 `temp/report_preview.html`에 생성됩니다. API나 메일을 사용하지 않습니다. 기본 비교 대상은 파일명 순으로 가장 최근 스냅샷 두 개이며, 실제 오늘 데이터라는 뜻은 아닙니다.

특정 날짜를 비교하려면 두 인자를 함께 지정합니다:

```powershell
python app/manual.py compare --previous snapshots/2026-03-27.csv --current snapshots/2026-03-30.csv
python app/manual.py preview --previous snapshots/2026-03-27.csv --current snapshots/2026-03-30.csv --ai
```

다음 명령은 **외부 API에 보유종목 데이터를 전송하고 무료 할당량을 사용**합니다:

```powershell
python app/manual.py analyze
python app/manual.py analyze --provider gemini
python app/manual.py analyze --provider glm
```

자동 전환 없이 지정한 제공자만 테스트할 수도 있습니다. 분석 JSON에는 비교 날짜를 함께 저장하고, HTML은 해당 분석 결과로 새로 생성합니다.

다음 명령은 **실제 메일을 발송**합니다. 기본적으로 AI도 새로 호출하며 AI 실패 시 수동 발송은 중단됩니다:

```powershell
python app/manual.py email
python app/manual.py email --no-ai
```

다운로드만 점검하거나 수동 원본을 가져옵니다:

```powershell
python app/manual.py fetch
python app/manual.py import --input manual_inputs/2026-03-30.xlsx
```

원본 이름이 날짜가 아니면 `--date YYYY-MM-DD`를 추가하세요. import는 CSV를 저장하지만 운영 기준 state는 바꾸지 않습니다.

`python app/run_tracker_once.py`는 실제 다운로드·AI 호출·메일 발송·state 변경이 가능한 **운영 명령**입니다. 단순 미리보기에는 사용하지 마세요.

## GitHub Actions 적용

기존 SMTP 설정과 실행 일정은 그대로 유지합니다. 저장소의 **Settings → Secrets and variables → Actions → Repository secrets**에 다음 이름으로 값을 설정하세요:

```text
SMTP_USER
SMTP_PASS
TO_EMAIL
GEMINI_API_KEY
GLM_API_KEY
```

로컬 `.env`의 GLM 키가 GitHub에 자동으로 전달되지는 않습니다. `GLM_API_KEY` Secret을 별도로 등록해야 fallback이 작동합니다. 모델과 기본 주소는 워크플로에도 지정돼 있습니다. Z.AI 키라면 워크플로의 GLM_BASE_URL도 함께 변경하세요.

현재 일정은 Asia/Seoul 기준 00:17 / 04:17 / 08:17 / 12:17 / 16:17 / 20:17입니다. GitHub 스케줄은 지연될 수 있으며 데이터가 같으면 메일이 오지 않는 것이 정상입니다.

코드를 커밋·push한 뒤 Actions → TIME ETF Tracker → Run workflow로 수동 실행을 확인하세요. **발송 후 상태를 GitHub에 push하는 데 실패하면 다음 실행에서 같은 메일이 다시 올 수 있습니다.** SMTP와 Git 저장을 하나의 거래로 묶을 수 없으므로 완전한 exactly-once 발송을 보장하지 않습니다.

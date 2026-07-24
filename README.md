# TIME ETF Tracker

TIME 미국나스닥100 액티브 ETF의 구성 종목 변화를 자동으로 추적하고, 직전 정상 스냅샷과 비교해 리포트 생성, AI 보조 해석, 이메일 발송까지 수행하는 자동화 프로젝트입니다.

이 프로젝트의 목적은 단순히 ETF 구성 종목 파일을 내려받는 것이 아니라 **오늘 어떤 종목의 수량과 비중이 어떻게 바뀌었는지**를 자동으로 감시하는 것입니다.

> 이 프로젝트의 결과는 데이터 모니터링과 연구를 위한 참고 자료입니다. 투자 자문이나 수익을 보장하는 자료가 아닙니다.

## 1. 주요 기능

- ETF 사이트에서 최신 구성 종목 Excel 다운로드
- 헤더만 존재하는 빈 템플릿 자동 스킵
- 필수 컬럼, 행 수, 중복 종목, 수량·평가금액·비중 검증
- 직전 정상 CSV 스냅샷과 비교
- 신규 편입·편출 계산
- 실제 보유 수량 증가·감소 계산
- 비중 증가·감소와 TOP10 순위 변화 계산
- 텍스트 및 HTML 리포트 생성
- Gemini 기반 AI 보조 해석
- Gmail SMTP 이메일 발송
- 날짜별 스냅샷과 실행 상태 저장
- SMTP 실패 시 pending 리포트 재시도
- GitHub Actions 기반 자동 실행

## 2. 수량 변화와 비중 변화

이 프로젝트는 수량 변화와 비중 변화를 서로 다른 신호로 취급합니다.

- **수량 변화**: 실제 매수·매도의 단서입니다. 다만 액면분할, 합병 등 기업행동의 영향도 확인해야 합니다.
- **비중 변화**: 매매가 없어도 가격, 환율, 다른 종목의 가치, 현금 규모에 따라 발생할 수 있습니다.

따라서 수량이 그대로인데 비중만 달라진 경우 이를 운용사의 매수·매도로 단정하지 않습니다. AI 분석에도 수량 신호와 비중 신호가 분리되어 전달됩니다.

## 3. 전체 동작 흐름

1. GitHub Actions가 KST 기준 4시간마다 실행됩니다.
2. 이전에 발송 실패한 pending 리포트가 있으면 먼저 재시도합니다.
3. ETF 사이트에서 최신 Excel 파일을 다운로드합니다.
4. 파일이 헤더만 있는 빈 템플릿이면 정상적으로 스킵합니다.
5. 정상 데이터면 스키마와 값의 유효성을 검사합니다.
6. 직전 정상 스냅샷과 내용 해시가 같으면 중복으로 스킵합니다.
7. 내용이 다르면 이전 파일의 존재 여부를 확인하고 새 스냅샷을 안전하게 저장합니다.
8. 종목 수량, 비중, 평가금액, 주식 TOP10 순위를 비교합니다.
9. Gemini가 데이터에 근거한 보조 분석을 생성합니다.
10. HTML·텍스트 리포트를 이메일로 발송합니다.
11. 성공한 스냅샷과 state를 Git 저장소에 반영합니다.

## 4. 중복과 스냅샷 보존 정책

동일한 내용의 스냅샷은 다시 저장하거나 이메일로 발송하지 않습니다.

기본 파일명은 다음과 같습니다.

```text
snapshots/2026-03-31.csv
```

같은 날짜에 서로 다른 데이터가 다시 들어오면 기존 파일을 덮어쓰지 않고 고유 파일을 만듭니다.

```text
snapshots/2026-03-31_121700_4b285e3f.csv
```

이를 통해 같은 날 여러 번 데이터가 바뀌어도 이전 비교 기준이 보존됩니다.

## 5. 프로젝트 구조

```text
time-etf-tracker/
├─ .github/
│  └─ workflows/
│     └─ etf-tracker.yml
├─ app/
│  ├─ ai_analyzer_gemini.py
│  ├─ collect_snapshot.py
│  ├─ compare.py
│  ├─ config.py
│  ├─ email_sender.py
│  ├─ exceptions.py
│  ├─ fetcher.py
│  ├─ holdings_parser.py
│  ├─ logging_utils.py
│  ├─ manual_import_snapshot.py
│  ├─ paths.py
│  ├─ reporter.py
│  ├─ run_compare_manual.py
│  ├─ run_tracker_once.py
│  ├─ send_compare_email_manual.py
│  ├─ snapshot_manager.py
│  ├─ state_manager.py
│  ├─ test_ai_analysis_gemini.py
│  ├─ test_parse_local.py
│  ├─ test_report_html.py
│  └─ validator.py
├─ tests/
│  └─ test_core.py
├─ manual_inputs/
├─ snapshots/
├─ state/
│  └─ tracker_state.json
├─ temp/
├─ .env.example
├─ .gitignore
├─ README.md
└─ requirements.txt
```

## 6. 설치

Python 3.13 기준으로 운영됩니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 7. 환경변수

`.env.example`을 `.env`로 복사한 뒤 실제 값을 입력합니다.

```powershell
Copy-Item .env.example .env
```

주요 환경변수:

| 이름 | 필수 여부 | 설명 |
|---|---|---|
| `SMTP_USER` | 이메일 발송 시 필수 | Gmail 주소 |
| `SMTP_PASS` | 이메일 발송 시 필수 | Gmail 앱 비밀번호 |
| `TO_EMAIL` | 이메일 발송 시 필수 | 리포트 수신 주소 |
| `GEMINI_API_KEY` | AI 분석 시 필수 | Google AI Studio API 키 |
| `GEMINI_MODEL` | 선택 | 기본 AI 모델 |
| `GEMINI_FALLBACK_MODEL` | 선택 | 기본 모델 실패 시 대체 모델 |
| `ETF_DOWNLOAD_URL` | 선택 | ETF Excel 다운로드 URL |
| `REPORT_TITLE` | 선택 | 리포트 제목 |
| `EMAIL_SUBJECT_PREFIX` | 선택 | 이메일 제목 접두사 |
| `DOWNLOAD_TIMEOUT_SEC` | 선택 | 다운로드 타임아웃, 기본 30초 |
| `DOWNLOAD_MAX_RETRIES` | 선택 | 다운로드 최대 재시도, 기본 3회 |

`.env`는 Git에 커밋하지 않습니다.

## 8. Gemini 모델

기본 구성:

```text
primary  : gemini-3.6-flash
fallback : gemini-3.5-flash-lite
```

기본 모델은 structured output으로 JSON을 생성합니다. 429·5xx 등 재시도 가능한 오류가 계속되거나 모델 접근 문제가 발생하면 fallback 모델을 사용합니다.

무료 티어 할당량은 계정과 프로젝트에 따라 달라질 수 있습니다. Google AI Studio에서 실제 한도를 확인해야 합니다. 무료 티어에 전송된 데이터는 Google 제품 개선에 사용될 수 있으므로 민감한 데이터를 전송하지 마세요.

- [Gemini API 가격](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API 한도](https://ai.google.dev/gemini-api/docs/rate-limits)

## 9. 로컬 실행

운영 흐름을 한 번 실행합니다.

```powershell
python app/run_tracker_once.py
```

이 명령은 실제 다운로드, Gemini 호출, 이메일 발송 및 state 변경을 수행할 수 있습니다.

다운로드와 파싱만 확인합니다.

```powershell
python app/test_parse_local.py
```

## 10. 수동 비교

인자를 생략하면 가장 최근 snapshot 두 개를 비교합니다.

```powershell
python app/run_compare_manual.py
```

파일을 직접 지정할 수도 있습니다.

```powershell
python app/run_compare_manual.py `
  --previous snapshots/2026-03-30.csv `
  --current snapshots/2026-03-31.csv
```

HTML 리포트 미리보기:

```powershell
python app/test_report_html.py `
  --previous snapshots/2026-03-30.csv `
  --current snapshots/2026-03-31.csv
```

Gemini 분석 테스트는 무료 할당량을 사용합니다.

```powershell
python app/test_ai_analysis_gemini.py `
  --previous snapshots/2026-03-30.csv `
  --current snapshots/2026-03-31.csv
```

수동 이메일 발송은 실제 메일을 보냅니다.

```powershell
python app/send_compare_email_manual.py `
  --previous snapshots/2026-03-30.csv `
  --current snapshots/2026-03-31.csv
```

## 11. 수동 XLSX 가져오기

원본 Excel 파일을 `manual_inputs/`에 넣고 실행합니다.

```powershell
python app/manual_import_snapshot.py
```

파일 이름의 stem을 그대로 사용해 snapshot CSV가 생성됩니다.

```text
manual_inputs/2026-03-30.xlsx
→ snapshots/2026-03-30.csv
```

## 12. 테스트

네트워크, Gemini, SMTP를 사용하지 않는 오프라인 테스트:

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions도 운영 tracker를 실행하기 전에 같은 테스트를 수행합니다.

현재 테스트는 다음을 확인합니다.

- 가격·비중 변화가 실제 수량 변화로 오분류되지 않는지
- 주식 순위에서 현금·선물이 제외되는지
- 동일 날짜의 서로 다른 snapshot이 덮어써지지 않는지
- 중복 종목이 거부되는지
- 상태 파일이 원자적으로 저장되고 손상을 조용히 초기화하지 않는지
- 이메일 HTML에 원본 AI payload가 숨겨져 포함되지 않는지

## 13. GitHub Actions 설정

Repository Secrets에 다음 값을 등록합니다.

```text
SMTP_USER
SMTP_PASS
TO_EMAIL
GEMINI_API_KEY
```

워크플로는 `Asia/Seoul` 기준 매 4시간마다 17분에 실행됩니다.

```text
00:17, 04:17, 08:17, 12:17, 16:17, 20:17 KST
```

실행 순서:

```text
checkout
→ Python 설치
→ 의존성 설치
→ 오프라인 테스트
→ tracker 실행
→ snapshots/state 커밋
→ 실패 시 debug artifact 업로드
```

## 14. state 파일

`state/tracker_state.json`은 다음을 관리합니다.

- 마지막 정상 snapshot 해시와 경로
- 마지막 보고 완료 snapshot
- 마지막 시도 상태와 메시지
- 이메일 발송 대기 중인 pending snapshot
- state 스키마 버전

snapshot 경로는 저장소 루트 기준 상대 경로로 저장합니다. 상태 파일은 임시 파일에 먼저 기록한 뒤 원자적으로 교체합니다.

state 파일이 손상되면 초기 상태로 조용히 되돌리지 않고 실행을 실패시켜 잘못된 기준점 생성을 방지합니다.

## 15. 빈 템플릿과 오류 처리

ETF 사이트가 헤더만 있고 실제 종목이 없는 Excel을 반환하면 `DataNotReadyError`로 분류하고 정상 스킵합니다.

다음은 오류로 처리합니다.

- 필수 컬럼 누락
- 데이터 행 부족
- 중복 종목코드
- 비어 있는 종목명
- NaN·무한대·음수 수량 또는 비중
- 비중 합계 이상
- 이전 기준 snapshot 파일 누락
- 손상된 state JSON
- 다운로드 실패
- SMTP 발송 실패

Gemini 분석만 실패한 경우에는 AI 섹션을 생략하고 Python이 계산한 기본 리포트는 계속 발송합니다.

## 16. 운영 시 주의사항

- AI 해석은 사실이 아니라 입력 데이터에 기반한 보조 가설입니다.
- 수량 변화가 있어도 액면분할 같은 기업행동일 수 있습니다.
- 비중 변화만으로 매수·매도를 판단하면 안 됩니다.
- 무료 Gemini 티어의 한도와 데이터 사용 정책을 확인하세요.
- Gmail은 일반 비밀번호 대신 앱 비밀번호를 사용하세요.
- `state/`와 `snapshots/`를 임의로 삭제하면 비교 기준이 사라질 수 있습니다.
- 실제 이메일을 보내기 전에는 오프라인 테스트와 HTML 미리보기를 먼저 확인하세요.

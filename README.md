# TIME ETF Tracker

TIME 미국나스닥100 액티브 ETF의 구성 종목 변화를 자동으로 추적하고,  
직전 정상 스냅샷과 비교해 **리포트 생성 + AI 해석 + 이메일 발송**까지 수행하는 자동화 프로젝트입니다.

이 프로젝트는 단순히 ETF 구성 종목 파일을 다운로드하는 수준이 아니라,  
“오늘 무엇이 어떻게 바뀌었는가”를 자동으로 감시하는 데 목적이 있습니다.

---

## 1. What this project does

이 프로젝트는 아래 과정을 자동화합니다.

- ETF 사이트에서 최신 구성 종목 엑셀 파일 다운로드
- 엑셀 파일이 실제 데이터인지 판별
- 헤더만 있고 내용이 없는 빈 템플릿 파일 자동 스킵
- 직전 정상 스냅샷과 비교
- 비중 증가/감소, 신규 편입/편출, TOP10 순위 변화 계산
- HTML 리포트 생성
- Gemini 기반 AI 해석 추가
- 이메일 발송
- 날짜별 CSV 스냅샷 저장

---

## 2. Why this project exists

액티브 ETF는 구성 종목과 비중이 바뀔 수 있기 때문에,  
단순히 현재 보유 종목을 보는 것보다 **이전 대비 변화**를 보는 것이 더 중요합니다.

예를 들어 이런 질문에 답하고 싶을 때 유용합니다.

- 오늘 새로 편입된 종목은 무엇인가
- 빠진 종목은 무엇인가
- 어떤 종목의 비중이 가장 많이 늘었는가
- 어떤 종목의 비중이 가장 많이 줄었는가
- 핵심 상위 종목 구조가 바뀌었는가
- 이런 변화가 어떤 운용 의도로 해석될 수 있는가

이 프로젝트는 그런 작업을 사람이 매번 엑셀로 수동 비교하지 않도록 만들었습니다.

---

## 3. Core idea

이 시스템의 핵심 아이디어는 간단합니다.

1. 최신 ETF 구성 종목 파일을 가져온다  
2. 직전 정상 데이터와 비교한다  
3. 변화 내용을 구조적으로 정리한다  
4. 이메일로 바로 받아본다  

즉, 이 프로젝트는 **ETF 변화 감시 시스템**입니다.

---

## 4. How it works

전체 동작 흐름은 아래와 같습니다.

1. GitHub Actions가 4시간마다 실행됩니다.
2. ETF 사이트에서 최신 엑셀 파일을 다운로드합니다.
3. 파일이 헤더만 있고 실제 종목 데이터가 없으면 스킵합니다.
4. 정상 파일이면 직전 정상 CSV 스냅샷과 비교합니다.
5. 동일하면 스킵합니다.
6. 다르면 새 스냅샷을 저장하고 비교 결과를 계산합니다.
7. HTML 리포트를 생성합니다.
8. 필요 시 Gemini로 포트폴리오 변화 해석을 추가합니다.
9. 최종 결과를 이메일로 발송합니다.
10. 새로운 기준 스냅샷과 state를 저장합니다.

---

## 5. Key features

### 5.1 Empty-template protection
ETF 사이트가 가끔 헤더만 있고 실제 데이터가 없는 엑셀 파일을 줄 수 있습니다.  
이 프로젝트는 그런 파일을 오류로 터뜨리지 않고 **정상 skip** 처리합니다.

### 5.2 Duplicate detection
직전 정상 스냅샷과 내용이 같으면, 중복 알림을 보내지 않습니다.

### 5.3 Snapshot-based comparison
엑셀 파일끼리 직접 비교하지 않고, 정리된 CSV 스냅샷끼리 비교합니다.

### 5.4 AI-assisted interpretation
숫자 계산은 Python이 직접 수행하고, AI는 변화의 의미를 해석하는 보조 역할만 합니다.

### 5.5 Cloud execution
GitHub Actions 기반이라 사용자의 컴퓨터가 꺼져 있어도 실행됩니다.

---

## 6. Project structure

```text
time-etf-tracker/
├─ .github/
│  └─ workflows/
│     └─ etf-tracker.yml          # GitHub Actions workflow
├─ app/
│  ├─ ai_analyzer_gemini.py       # Gemini 기반 AI 해석
│  ├─ collect_snapshot.py         # 스냅샷 수집 관련 보조 스크립트
│  ├─ compare.py                  # 전/후 스냅샷 비교 로직
│  ├─ config.py                   # 환경변수 로드
│  ├─ email_sender.py             # 이메일 발송
│  ├─ exceptions.py               # 커스텀 예외 정의
│  ├─ fetcher.py                  # 최신 엑셀 다운로드
│  ├─ holdings_parser.py          # 엑셀 파싱
│  ├─ logging_utils.py            # 로그 설정
│  ├─ manual_import_snapshot.py   # 수동 원본 xlsx -> snapshot csv 변환
│  ├─ paths.py                    # 프로젝트 경로 관리
│  ├─ reporter.py                 # 텍스트/HTML 리포트 생성
│  ├─ run_compare_manual.py       # 수동 비교 실행
│  ├─ run_tracker_once.py         # 운영용 진입점
│  ├─ send_compare_email_manual.py# 수동 이메일 발송 테스트
│  ├─ snapshot_manager.py         # snapshot 저장 및 hash 계산
│  ├─ state_manager.py            # state 파일 관리
│  ├─ test_ai_analysis_gemini.py  # AI 분석 테스트
│  ├─ test_parse_local.py         # 파싱 테스트
│  ├─ test_report_html.py         # HTML 리포트 테스트
│  └─ validator.py                # 유효성 검증
├─ manual_inputs/                 # 수동 테스트용 원본 xlsx
├─ snapshots/                     # 정상 데이터 CSV 스냅샷
├─ state/
│  └─ tracker_state.json          # 현재 기준 스냅샷 및 상태 정보
├─ temp/                          # 임시 파일
├─ .gitignore
├─ README.md
└─ requirements.txt

# 반듯 AI

웹캠으로 앉은 자세를 지켜보고 무너지면 알려 주는 자세교정 서비스 **"반듯"** 의 AI 저장소.
(카카오테크 부트캠프 4기 해커톤 2팀)

이 저장소가 실제로 배포하는 것은 **일일 자세 리포트를 Claude로 분석해 주는 FastAPI 서버 하나**
([`report-service/`](report-service/))다. 실시간 자세 감지(MediaPipe)는 해커톤 중 프론트엔드 온디바이스로
이관됐고, 이관 전 원본 서버는 [`backup/`](backup/)에 보관돼 있다.

## 한눈에 보기

```
[frontend]  브라우저 MediaPipe로 자세 감지 · 경고 · 스트레칭 따라하기
     │  시간대별 유지율 / 경고 / 스트레칭 기록
     ▼
[backend]   유저별 일일 데이터 집계 (모니터링 종료 시)
     │  POST /api/report/daily/analyze
     ▼
[AI · report-service]  집계치 계산 → Claude 분석 (실패 시 규칙 기반 폴백)
     │  summary / grade / highlights / advice / stats
     ▼
[frontend]  자세 진단 리포트 화면
```

| 관련 저장소 | 역할 |
|---|---|
| [frontend](https://github.com/ktb-4-hackathon-team-2/frontend) | 웹캠 화면, 온디바이스 자세 감지, 리포트 화면 |
| [backend](https://github.com/ktb-4-hackathon-team-2/backend) | 유저·기록 저장, 일일 집계, AI 서버 호출 |
| **AI (여기)** | 일일 리포트 LLM 분석 서버 |

## 디렉터리 구조

| 경로 | 내용 |
|---|---|
| [`report-service/`](report-service/) | **EC2에 배포되는 서버.** 이 폴더만 가져가면 실행되도록 자기완결 구성. 실행법·API 계약은 [폴더 README](report-service/README.md) |
| [`backup/`](backup/) | 이관 전 원본 풀서버 — 가이드 정합·캘리브레이션·실시간 모니터링·스트레칭 감지 + 리포트. 프론트 포팅의 원본 스펙 ([API 문서](backup/README.md)) |
| `backup/experiments/` | 2장 촬영(정면 + 자유 배치) 캘리브레이션 실험 코드와 결과 문서 |
| `Dockerfile` | 루트 기준으로 `report-service`를 빌드하는 Dockerfile |
| `.github/workflows/` | CI(`ci.yml`)와 수동 배포(`deploy.yml`) |

## 빠른 시작

```bash
cd report-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # 없어도 규칙 기반 폴백으로 동작
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 헬스체크: `GET http://localhost:8000/health` → `{"status": "ok"}`
- Swagger: `http://localhost:8000/docs`
- 테스트: `cd report-service && python test_report.py`

Docker로 실행:

```bash
docker build -t bandeut-ai .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... bandeut-ai
```

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스체크 |
| `POST` | `/api/report/daily/analyze` | 시간대별 자세 데이터 → 요약·등급·하이라이트·조언 + 집계치 |

요청 예시:

```json
{
  "date": "2026-08-20",
  "user_id": "user-42",
  "hourly": [
    {"hour": 9, "good_ratio": 0.9, "monitored_min": 55, "alerts": 1},
    {"hour": 10, "good_ratio": 0.6, "monitored_min": 60, "alerts": 5}
  ],
  "stretch_suggested": 3,
  "stretch_done": 1
}
```

응답의 핵심 필드는 `summary`, `grade`(`excellent`|`good`|`normal`|`bad`), `highlights`, `advice`,
`source`(`llm`|`rule_based`), `stats`다. 필드 전체와 입력 클리닝 규칙은
[report-service README](report-service/README.md#api)를 기준으로 한다.

## 설계 포인트

- **항상 200 응답** — API 키가 없거나 Claude 호출이 실패하면 규칙 기반 분석으로 자동 폴백한다.
  응답의 `source`로 어느 쪽인지 구분한다.
- **관대한 입력 파싱** — backend 페이로드 형식이 흔들려도 500이 나지 않도록 스키마 검증 대신
  클리닝(퍼센트 자동 환산, NaN·음수 보정 등)을 한다.
- **LLM 쿨다운** — 종료 버튼 연타로 API가 낭비되지 않게 같은 `(user_id, date)`는 기본 5분간
  기존 코멘트를 재사용한다. 수치(`stats`)는 매번 새로 계산되고, 사용자가 직접 재생성을 누르면
  `force: true`로 쿨다운을 건너뛴다.
- **수치 낭독 대신 패턴 해석** — 프롬프트는 시간대 추이·급락 구간·경고 밀집 시간대를 해석하고,
  조언을 행동 습관 / 스트레칭 / 근력·환경 세 갈래로 나누도록 지시한다.
- **모델 교체 용이** — `ANTHROPIC_MODEL`만 바꾸면 된다. Haiku 등 `effort`를 지원하지 않는 모델에서도
  조용히 폴백되지 않도록 호출부에서 `effort`를 뺐다.
- **가벼운 이미지** — 자세 감지가 프론트로 이관돼 mediapipe·opencv·numpy 의존성이 없다.

## 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | 권장 | (없음) | 없거나 호출 실패 시 규칙 기반 폴백 |
| `ANTHROPIC_MODEL` | 선택 | `claude-sonnet-5` | 리포트 분석 모델 |
| `REPORT_LLM_COOLDOWN_SEC` | 선택 | `300` | LLM 재호출 쿨다운(초) |

## CI/CD

둘 다 `report-service/` 기준으로 동작한다.

- **CI** (`ci.yml`) — `main`/`test` 브랜치 push·PR 시 자동 실행. Python 3.11에서 flake8 문법 검사,
  `compileall`, `test_report.py`.
- **배포** (`deploy.yml`) — 자동 아님. **Actions 탭 → "Deploy AI Server to EC2 (Manual ECR & Auto Rollback)"
  → Run workflow**로 수동 실행한다. ECR에 이미지 빌드·푸시 → EC2에서 `posture-ai` 컨테이너 교체 →
  `/health` 실패 시 이전 이미지로 자동 롤백.

필요한 레포 시크릿:

| 시크릿 | 용도 |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | ECR 푸시 |
| `AWS_REGION` | 기본 `ap-northeast-2` |
| `ECR_AI_REPOSITORY` | 기본 `bandeut-ai` |
| `EC2_HOST`, `EC2_USER`(기본 `ubuntu`), `EC2_SSH_KEY` | EC2 접속 |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | 컨테이너 환경변수 주입 |

## 개발 히스토리

| 날짜 | 내용 |
|---|---|
| 2026-08-19 | 자세 감지(MediaPipe) + 리포트 분석 풀서버 구현, Sonnet 전환, 2장 캘리브레이션 실험, LLM 쿨다운 추가 |
| 2026-08-20 | ECR·EC2 무중단 배포/자동 롤백 파이프라인 구축 (#1) |
| 2026-08-20 | 자세 감지 프론트 이관에 맞춰 `report-service` 분리, 원본은 `backup/`으로 이동 (#2) |
| 2026-08-20 | 프롬프트 개선(패턴 해석·조언 다양화), 비차단 쿨다운 락으로 스레드풀 고갈 방지 |
| 2026-08-21 | `force` 플래그로 사용자 재생성 시 쿨다운 우회 |

## 알려진 한계

- 쿨다운 캐시는 인메모리라 단일 인스턴스 기준이다. 인스턴스를 늘리면 쿨다운이 인스턴스별로 따로 걸린다.
- CORS가 해커톤용으로 전체 허용(`*`) 상태다.
- `hour` 값은 범위 검증을 하지 않으므로 backend에서 0~23을 보장해야 한다.

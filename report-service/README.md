# 반듯 AI 리포트 서버 (report-service)

일일 자세 데이터를 받아 **Claude로 요약·하이라이트·조언을 생성**하는 단독 FastAPI 서비스.
이 폴더 하나만 통째로 가져가면 배포 가능하도록 자기완결로 구성했다.

> 배경: 원래 AI 서버(`backup/app/`)에는 자세 감지(MediaPipe)와 리포트 분석이 함께
> 있었는데, 자세 감지는 프론트엔드(브라우저 MediaPipe)로 이관됐다. 서버에 남는 건
> 리포트 분석뿐이라 이 폴더로 분리했다. 원본 풀서버는 `backup/`에 백업돼 있다.
> **mediapipe / opencv / numpy 의존성이 없으므로** 이미지가 가볍고 시스템 패키지도 불필요.

## 실행 (로컬)

```bash
cd report-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # 없어도 규칙 기반 폴백으로 동작
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t bandut-report .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... bandut-report
```

EC2 배포 파이프라인(ECR 빌드 → 컨테이너 교체 → 헬스체크 → 실패 시 자동 롤백)이
준비돼 있다. 자동 트리거는 아니고 **Actions 탭 → "Deploy AI Server to EC2" →
Run workflow** 로 실행한다. 필요한 레포 시크릿은 [루트 README](../README.md) 참고.

## 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | 권장 | (없음) | 없거나 호출 실패 시 규칙 기반 분석으로 폴백 (`source: "rule_based"`) |
| `ANTHROPIC_MODEL` | 선택 | `claude-sonnet-5` | 리포트 분석에 쓸 Claude 모델 |
| `REPORT_LLM_COOLDOWN_SEC` | 선택 | `300` | 같은 (user_id, date) 재호출 시 LLM 재사용 쿨다운(초) |

**모델 교체**: `ANTHROPIC_MODEL`만 바꾸면 된다 (예: `claude-haiku-4-5`).
호출부에 `output_config.effort`를 넣지 않는 이유가 이것 — Haiku 4.5는 `effort`를
지원하지 않아 400이 나고, 그 예외가 폴백에 잡혀 **에러 없이 조용히 규칙 기반으로
떨어지기** 때문이다. structured outputs(`json_schema`)은 Haiku 4.5에서도 지원되므로 유지.

## API

FastAPI 자동 문서: `GET /docs` (Swagger UI), `GET /redoc`, `GET /openapi.json`.
단, 요청 바디를 스키마 검증 없이 받으므로(아래 *입력 클리닝* 참고) Swagger에는
요청 필드가 자유 객체로만 표시된다. **요청 형식은 이 문서가 기준.**

### `GET /health`

```json
{"status": "ok"}
```

로드밸런서/헬스체크용. 인증 없음.

### `POST /api/report/daily/analyze`

backend가 집계한 일일 데이터를 보내면 담백한 서술체 분석을 돌려줌.

**호출 시점**: 모니터링 종료 버튼을 누를 때 backend가 그날 데이터를 집계해 호출.

#### 요청 필드

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `date` | string | 선택 | `YYYY-MM-DD`. 누락 시 서버 기준 오늘 |
| `hourly` | array | 선택 | 시간대별 버킷 (아래). 누락/빈 배열이면 "기록 없음" 분석 |
| `hourly[].hour` | int | — | 0~23 |
| `hourly[].good_ratio` | float | — | 바른 자세 유지율 0~1 (0~100으로 보내도 자동 흡수) |
| `hourly[].monitored_min` | float | — | 해당 시간대 모니터링 시간(분) |
| `hourly[].alerts` | int | — | 해당 시간대 경고 횟수 |
| `stretch_suggested` | int | 선택 | 그날 제안된 스트레칭 횟수 (기본 0) |
| `stretch_done` | int | 선택 | 그날 수행한 스트레칭 횟수 (기본 0) |
| `user_id` | string | **권장** | LLM 쿨다운 구분용. 누락 시 `"default_user"` 공유 키 |
| `user_name` | string | 선택 | 현재 분석에 사용하지 않음 (아바타 기획 보류분) |

**입력 클리닝 (관대한 파싱)**: backend 연동 중 페이로드 형식이 흔들려도 500이
나지 않도록 스키마 검증 대신 클리닝을 한다.

- `good_ratio`가 1보다 크면 %(0~100)로 간주해 100으로 나눠 흡수하고 0~1로 클램프
- 형이 어긋난 `hourly` 항목(dict 아님)은 조용히 건너뜀
- 숫자 필드는 변환 실패·`Infinity`·`NaN`이면 0으로 대체
- `monitored_min`·`alerts`는 음수면 0으로 클램프. `monitored_min`이 0인 버킷은
  집계에서 제외되므로, 음수를 보내면 그 시간대는 통째로 빠진다
- **`hour`는 범위 검증을 하지 않는다** — `99`를 보내면 그대로 통과해 결과에 섞이니
  backend에서 0~23을 보장할 것
- 422는 바디가 JSON 객체가 아닐 때(예: 배열·문자열)만 발생

**연타 보호 (LLM 쿨다운)**: 같은 `(user_id, date)`로 쿨다운(기본 5분) 안에 다시 호출하면
LLM을 다시 부르지 않고 기존 코멘트를 재사용 (`analysis_cached: true`).
단 `stats`(일일 레포트 수치)는 매 호출 새로 계산되므로 연타해도 수치는 갱신된다.
LLM이 실패해 규칙 기반으로 떨어진 경우에도 쿨다운은 시작된다 (API 남용 방지가 목적).

요청 예시:

```json
{
  "date": "2026-08-20",
  "hourly": [
    {"hour": 9, "good_ratio": 0.9, "monitored_min": 55, "alerts": 1},
    {"hour": 10, "good_ratio": 0.6, "monitored_min": 60, "alerts": 5}
  ],
  "stretch_suggested": 3,
  "stretch_done": 1,
  "user_id": "user-42"
}
```

#### 응답 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `summary` | string | 하루 데이터 해석 (한국어 2~3문장) |
| `grade` | string | `excellent` \| `good` \| `normal` \| `bad` |
| `highlights` | string[] | 특징적인 패턴·추이 (최대 4개) |
| `advice` | string[] | 내일을 위한 조언 (최대 3개) |
| `source` | string | `llm`(Claude 분석) \| `rule_based`(폴백) |
| `stats` | object | 서버가 계산한 집계치 (아래) |
| `stats.total_monitored_min` | float | 모니터링 시간 합(분) |
| `stats.avg_good_ratio` | float | 시간 가중 평균 유지율 0~1 |
| `stats.total_alerts` | int | 경고 총 횟수 |
| `stats.worst_hour` / `best_hour` | object\|null | 유지율 최저/최고 버킷 (기록 없으면 null) |
| `stats.stretch_done` / `stretch_suggested` | int | 스트레칭 수행/제안 횟수 |
| `analysis_cached` | bool | true면 쿨다운으로 기존 코멘트 재사용 (`stats`는 최신) |
| `analysis_age_sec` | float | 재사용한 코멘트가 만들어진 지 몇 초 됐는지 |
| `cooldown_remaining_sec` | float | 다음 LLM 갱신까지 남은 시간 (UI "N분 후 갱신" 표시용) |

`monitored_min`이 0인 버킷은 집계에서 제외된다. 모니터링 기록이 전혀 없으면
`avg_good_ratio: 0.0`, `worst_hour`/`best_hour`는 `null`.

응답 예시 (실제 폴백 출력):

```json
{
  "summary": "바른 자세 유지율은 74%로 양호한 수준입니다.",
  "grade": "good",
  "highlights": [
    "10시 유지율이 60%로 가장 낮았습니다",
    "9시 유지율이 90%로 가장 높았습니다",
    "자세 경고가 총 6회 발생했습니다"
  ],
  "advice": [
    "10시 무렵 자세가 가장 많이 무너집니다. 그 전에 잠깐 일어나 몸을 푸는 것을 권장합니다",
    "제안된 스트레칭 3회 중 1회를 수행했습니다. 목 옆 늘리기·턱 당기기부터 짧게 시작해 보세요",
    "플랭크·버드독 같은 코어 운동은 앉은 자세를 오래 유지하는 힘을 길러 줍니다"
  ],
  "source": "rule_based",
  "stats": {
    "total_monitored_min": 115.0,
    "avg_good_ratio": 0.743,
    "total_alerts": 6,
    "worst_hour": {"hour": 10, "good_ratio": 0.6, "monitored_min": 60.0, "alerts": 5},
    "best_hour": {"hour": 9, "good_ratio": 0.9, "monitored_min": 55.0, "alerts": 1},
    "stretch_done": 1,
    "stretch_suggested": 3
  },
  "analysis_cached": false,
  "analysis_age_sec": 0.0,
  "cooldown_remaining_sec": 300.0
}
```

#### 분석 내용 설계

LLM에는 수치를 나열하지 말고 **패턴을 해석**하도록 지시한다 (시간대 추이, 급락·회복
구간, 경고 밀집 시간대, 스트레칭 이행률). `advice`는 서로 다른 세 갈래로 구성한다:

1. **행동 습관** — 가장 취약한 시간대에 맞춘 구체적 제안
2. **스트레칭** — 앱에 실제 있는 동작 중에서 (목 옆 늘리기, 턱 당기기, 어깨 으쓱하기, 가슴 열기, 팔 위로 뻗기)
3. **근력·환경** — 코어 운동(플랭크, 버드독 등) 또는 모니터 높이·휴식 주기 개선

측정되는 값은 유지율·모니터링 시간·경고 횟수·스트레칭 수행뿐이므로, 구체적인 자세
문제 종류나 통증은 단정하지 않도록 프롬프트에 명시돼 있다.

## 테스트

```bash
cd report-service
python test_report.py
```

LLM 직접 호출과 라우터 경유 호출을 각각 실행해 결과를 출력한다
(`ANTHROPIC_API_KEY` 없으면 `rule_based` 폴백 결과가 나오는 게 정상).
같은 검사가 `main`/`test` 브랜치 push·PR마다 CI에서 자동 실행된다.

## 배포 메모 (클라우드 담당자용)

- 포트 **8000**, 헬스체크 `GET /health`.
- 상태는 인메모리 LLM 쿨다운 캐시뿐 — 디스크 볼륨/DB 불필요. 단일 인스턴스 기준이며,
  다중 인스턴스로 늘리면 쿨다운이 인스턴스별로 따로 걸린다 (해커톤 규모에선 무시 가능).
- CORS는 해커톤용으로 전체 허용(`*`) 상태.
- LLM 호출 타임아웃 60초 내장, 재시도 없음. 실패하면 자동으로 규칙 기반 폴백 →
  키가 없거나 API가 죽어도 서비스는 항상 200으로 응답한다.
- **LLM이 도는지 확인**: 응답의 `source`가 `"llm"`인지 보면 된다. 계속 `"rule_based"`면
  컨테이너 로그(`docker logs posture-ai`)에 폴백 사유가 경고로 찍혀 있다.

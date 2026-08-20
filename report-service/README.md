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

참고용 `Dockerfile`을 넣어뒀다 (담당자가 자유롭게 수정/대체).

```bash
docker build -t bandut-report .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... bandut-report
```

## 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | 권장 | (없음) | 없거나 호출 실패 시 규칙 기반 분석으로 폴백 (`source: "rule_based"`) |
| `ANTHROPIC_MODEL` | 선택 | `claude-sonnet-5` | 리포트 분석에 쓸 Claude 모델 |
| `REPORT_LLM_COOLDOWN_SEC` | 선택 | `300` | 같은 (user_id, date) 재호출 시 LLM 재사용 쿨다운(초) |

## API

### `GET /health`

```json
{"status": "ok"}
```

로드밸런서/헬스체크용.

### `POST /api/report/daily/analyze`

backend가 집계한 일일 데이터를 보내면 담백한 서술체 분석을 돌려줌.

**호출 시점**: 모니터링 종료 버튼을 누를 때 backend가 그날 데이터를 집계해 호출.

**연타 보호 (LLM 쿨다운)**: 같은 `(user_id, date)`로 쿨다운(기본 5분) 안에 다시 호출하면
LLM을 다시 부르지 않고 기존 코멘트를 재사용 (`analysis_cached: true`).
단 `stats`(일일 레포트 수치)는 매 호출 새로 계산되므로 연타해도 수치는 갱신됨.
`user_id`를 안 보내면 `default_user` 공유 키로 쿨다운이 걸리니 **user_id 전송 권장**.

**입력 클리닝 (관대한 파싱)**: backend 연동 중 페이로드 형식이 흔들려도 500/422가
나지 않도록 스키마 검증 대신 클리닝을 함.
- `good_ratio`가 1보다 크면 %(0~100)로 간주해 100으로 나눠서 흡수, 0~1로 클램프
- 형이 어긋난 `hourly` 항목은 조용히 건너뜀, 숫자 필드는 변환 실패 시 0
- `date` 누락 시 서버 기준 오늘 날짜, `user_id` 누락 시 `"default_user"`

요청:

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

응답:

```json
{
  "summary": "바른 자세 유지율은 74%로 양호한 수준입니다. ...",
  "grade": "excellent | good | normal | bad",
  "highlights": ["10시 유지율이 60%로 가장 낮았습니다"],
  "advice": ["50분마다 한 번씩 스트레칭으로 몸을 푸는 것을 권장합니다"],
  "source": "llm | rule_based",
  "stats": {
    "total_monitored_min": 115, "avg_good_ratio": 0.74, "total_alerts": 6,
    "worst_hour": {"hour": 10, "good_ratio": 0.6, "monitored_min": 60, "alerts": 5},
    "best_hour": {"hour": 9, "good_ratio": 0.9, "monitored_min": 55, "alerts": 1},
    "stretch_done": 1, "stretch_suggested": 3
  },
  "analysis_cached": false,
  "analysis_age_sec": 0.0,
  "cooldown_remaining_sec": 300.0
}
```

- `summary` 2~3문장, `highlights` 최대 4개, `advice` 최대 3개, 전부 한국어.

## 테스트

```bash
cd report-service
python test_report.py
```

LLM 직접 호출과 라우터 경유 호출을 각각 실행해 결과를 출력한다
(`ANTHROPIC_API_KEY` 없으면 `rule_based` 폴백 결과가 나오는 게 정상).

## 배포 메모 (클라우드 담당자용)

- 포트 **8000**, 헬스체크 `GET /health`.
- 상태는 인메모리 LLM 쿨다운 캐시뿐 — 디스크 볼륨/DB 불필요. 단일 인스턴스 기준이며,
  다중 인스턴스로 늘리면 쿨다운이 인스턴스별로 따로 걸린다 (해커톤 규모에선 무시 가능).
- CORS는 해커톤용으로 전체 허용(`*`) 상태.
- LLM 호출 타임아웃 60초 내장, 실패 시 자동으로 규칙 기반 폴백 → 키가 없어도 서비스는 항상 응답함.

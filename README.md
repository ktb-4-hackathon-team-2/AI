# 반듯 AI 서버

웹캠 프레임 기반 **자세 감지**(OpenCV + MediaPipe Pose)와 **자세 진단 리포트 분석**(Claude)을 제공하는 FastAPI 서버입니다.

| 기능 | 사용하는 화면 |
|---|---|
| 자세 가이드 오버레이 + 정합 판정 | 초기 진입(우대각/좌대각/정면 선택), 스트레칭 화면 |
| 초기 자세 캘리브레이션 | 바른 자세 한 컷 촬영 → 스켈레톤 좌표만 저장 |
| 실시간 모니터링 + 경고 알람 | 모니터링 화면 (REST 또는 WebSocket) |
| 스트레칭 추천 + 따라하기 감지 | 스트레칭 화면 |
| 일일 리포트 분석 | 자세 진단 리포트 화면 |

## 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Swagger 문서: `http://localhost:8000/docs`
- 리포트 LLM 분석을 쓰려면 `ANTHROPIC_API_KEY` 환경변수 설정 (없어도 규칙 기반 폴백으로 동작)
- baseline은 `data/baselines.json`에 저장됨 (git 제외)

## 공통 규칙

- **이미지 입력**: JPEG/PNG를 base64로 인코딩한 문자열. `data:image/jpeg;base64,...` data URL도 허용.
  깨진 이미지는 `400 {"detail": ...}`.
- **좌표계**: 모든 좌표(랜드마크, 가이드 앵커, 실루엣)는 **프레임 기준 정규화 좌표** (x, y ∈ 0~1, 좌상단 원점).
  캔버스 크기를 곱해서 그리면 됨. **셀피 미러링 화면에서는 x를 `1-x`로 뒤집어 그릴 것** (안내 문구는 화면에 보이는 방향 기준으로 이미 작성됨).
- **landmarks**: MediaPipe Pose 33개 `[{x, y, z, visibility}]`. 사람이 안 보이면 프레임형 응답은 `detected: false`로 옴 (에러 아님).
- 프레임 전송 주기는 프론트가 결정. **1~2초에 1프레임 권장** (모니터링 용도로 충분).

---

## 1. 가이드 & 캘리브레이션 (초기 진입)

### `GET /api/guide`
선택 가능한 뷰 목록.

```json
{
  "views": [{"view": "front", "label": "정면"}, {"view": "left_diagonal", ...}, ...],
  "calibration_views": ["front", "left_diagonal", "right_diagonal"]
}
```

`stretch` 뷰는 가이드/정합용으로만 쓰고 캘리브레이션은 불가.

### `GET /api/guide/{view}`
카메라 화면에 오버레이할 가이드 데이터.

```json
{
  "view": "front",
  "label": "정면",
  "anchors": {"nose": {"x": 0.5, "y": 0.3}, "left_ear": ..., "left_shoulder": ...},
  "silhouette": [{"x": ..., "y": ...}, ...],   // 상반신 실루엣 폴리곤 (그대로 path로 그리기)
  "tolerance": 0.09,                            // 앵커 허용 오차
  "instructions": ["카메라를 정면으로 바라봐 주세요", ...]
}
```

### `POST /api/align`
실시간 프레임이 가이드에 맞게 앉았는지 판정. 캘리브레이션 촬영 전 위치 잡기 + 스트레칭 화면 위치 잡기에 사용.

요청: `{"image": "<base64>", "view": "front" | "left_diagonal" | "right_diagonal" | "stretch"}`

```json
{
  "detected": true,
  "aligned": false,
  "offsets": {"nose": 0.04, "left_shoulder": 0.11, ...},  // 앵커별 거리 오차
  "dx": 0.12, "dy": -0.02, "scale": 0.05,                  // 어깨중심 편차 (raw 프레임 기준)
  "messages": ["오른쪽으로 조금 이동해 주세요", "카메라에 조금 가까이 와 주세요"],
  "landmarks": [ ...33개... ]
}
```

앵커/실루엣의 left_/right_는 **이미지 기준 좌우**이며, 판정은 프레임 미러링 여부와 무관하게 동작함
(raw 프레임을 그대로 보내면 됨). 이동 안내 문구는 유저 몸 기준 = 미러링된 셀피 화면 기준 방향.

`aligned: true`가 되면 `messages`는 `["좋아요! 이 자세를 유지해 주세요"]` — 이때 촬영 버튼 활성화 추천.

### `POST /api/calibrate`
바른 자세 한 컷 → 스켈레톤 좌표만 저장하고 `baseline_id` 발급. **이미지는 저장하지 않음.**

요청: `{"image": "<base64>", "user_id": "<backend의 유저 id>", "view": "front"}`

```json
// 성공
{"ok": true, "baseline_id": "2ba7c8b5a9d5", "view": "front",
 "aligned": true, "alignment_messages": [...], "metrics": {...}, "landmarks": [...]}

// 실패 (HTTP 200 — 사유를 UI에 표시)
{"ok": false, "reason": "person_not_detected" | "upper_body_not_visible", "messages": [...]}
```

`baseline_id`는 backend가 유저와 함께 저장해 두고 모니터링 때 넘겨주면 됨.

### `GET /api/baseline/{baseline_id}` / `GET /api/users/{user_id}/baseline`
baseline 조회 / 해당 유저의 최신 baseline (재접속 시 재캘리브레이션 생략용). 없으면 404.

---

## 2. 실시간 모니터링 + 경고 알람

### `POST /api/monitor/frame`

```json
{
  "image": "<base64>",
  "baseline_id": "2ba7c8b5a9d5",
  "session_id": "탭마다 고유한 임의 문자열 권장 (선택, REST에서 생략 시 baseline_id 사용)",
  "strictness": "low" | "medium" | "high",     // 환경설정의 경고 엄격도 (기본 medium, 그 외 값은 422)
  "warn_after_sec": 5.0,                        // 나쁜 자세 지속 → 팝업 경고까지 시간 (선택, ≥0)
  "alarm_after_sec": 15.0                       // → 강한 경고까지 시간 (선택, ≥0, warn 이상이어야 함)
}
```

```json
{
  "detected": true,
  "posture_ok": false,
  "score": 1.42,                    // 최대 편차 비율. 1.0 이상이면 임계치 초과
  "issues": [{"code": "neck_tilt", "message": "목이 기울거나 앞으로 나왔어요 (거북목 주의)", "severity": 1.42}],
  "issue_codes": ["neck_tilt"],     // 그대로 /api/stretch/recommend에 넘기면 됨
  "deviations": {"neck_tilt": 1.42, "shoulder_tilt": 0.3, "head_down": 0.1, "lean_in": 0.0, "lean_out": 0.2, "shift_x": 0.05},
  "alert_level": 1,                 // 0=정상, 1=팝업 경고, 2=강한 경고(개지랄 모드)
  "alarm": false,                   // 강한 경고(level 2)일 때만 true → 알람 소리 울리기
  "bad_duration_sec": 7.2,
  "landmarks": [...]
}
```

- **경고 UX**: `alert_level 1` → 자세 안좋다는 팝업, `alert_level 2` → 강한 경고. 좋은 자세로 돌아오면 즉시 0으로 리셋.
- 사람이 없거나 상반신이 가려지면 `{"detected": false, "alert_level": 0, ...}` — 자리 비움은 나쁜 자세로 치지 않음.
- issue code 종류: `neck_tilt`(거북목/목기울임) `shoulder_tilt`(어깨 기울어짐) `head_down`(고개 숙임) `lean_in`(화면에 붙음) `lean_out`(뒤로 처짐) `shift_x`(좌우 이탈)

### `POST /api/monitor/reset`
일시정지 후 재개 등으로 경고 지속시간을 리셋. 요청: `{"session_id": "..."}`

### `WS /api/monitor/ws`
같은 판정을 WebSocket으로. 보내는 JSON과 받는 JSON 모두 `/monitor/frame`과 동일.
`session_id`를 생략하면 연결 단위로 경고 상태를 추적함 (연결이 끊기면 리셋).
에러 프레임은 `{"error": "invalid_request" | "invalid_json" | "image_decode_failed" | "request_rejected", "detail": ...}` — 연결은 유지됨.

```js
const ws = new WebSocket("ws://localhost:8000/api/monitor/ws");
ws.onopen = () => ws.send(JSON.stringify({image: b64, baseline_id, session_id: "tab-1"}));
ws.onmessage = (e) => { const r = JSON.parse(e.data); if (r.alert_level >= 1) showWarning(r); };
```

---

## 3. 스트레칭

### `GET /api/stretch/exercises`
앉아서 하는 상반신 스트레칭 6종 카탈로그. 각 항목: `{id, name, targets, hold_sec, description}`

### `POST /api/stretch/recommend`
요청: `{"issue_codes": ["neck_tilt", "head_down"]}` (모니터링 응답의 `issue_codes` 그대로).
빈 배열이면 기본 3종 추천. 응답: `{"exercises": [...관련도 순...]}`

### `POST /api/stretch/session`
따라하기 세션 시작. 요청: `{"exercise_id": "chin_tuck"}`

```json
{"session_id": "eb899ee45c43", "exercise_id": "chin_tuck", "hold_target_sec": 8,
 "held_sec": 0.0, "completed": false, "exercise": {...}}
```

### `POST /api/stretch/session/{session_id}/frame`
스트레칭 화면은 **정면(stretch 뷰) 기준** — 먼저 `/api/align`(view=stretch)으로 위치를 잡게 한 뒤 프레임 전송.

요청: `{"image": "<base64>"}`

```json
{
  "detected": true,
  "in_pose": false,                              // 지금 동작을 하고 있는지
  "feedback": ["턱을 뒤로 당겨 귀가 어깨 위에 오도록 해 주세요"],
  "held_sec": 3.4,                               // 누적 유지 시간
  "hold_target_sec": 8,
  "completed": false,                            // held_sec가 목표에 도달하면 true
  "landmarks": [...]
}
```

`completed: true`가 오면 완료 처리(리포트의 stretch_done 집계에 사용).

---

## 4. 자세 진단 리포트 분석

### `POST /api/report/daily/analyze`
backend가 집계한 일일 데이터를 보내면 담백한 서술체 분석을 돌려줌.
(아바타 말투·`avatar_state` 생성은 기획 보류로 코드에 주석처리돼 있음 — 확정되면 복원)

**호출 시점**: 모니터링 종료 버튼을 누를 때 backend가 그날 데이터를 집계해 호출.

**연타 보호 (LLM 쿨다운)**: 같은 `(user_id, date)`로 **5분 안에** 다시 호출하면
LLM API를 다시 부르지 않고 **기존 코멘트를 재사용**함 (`analysis_cached: true`).
단, **`stats`(일일 레포트 수치)는 매 호출 새로 계산**되므로 일일 레포트 갱신은 연타해도 됨.
쿨다운은 `REPORT_LLM_COOLDOWN_SEC` 환경변수로 조정 (기본 300초).
`user_id`를 안 보내면 전체 공유 키로 쿨다운이 걸리니 **user_id 전송 권장**.

```json
{
  "date": "2026-08-19",
  "hourly": [
    {"hour": 9, "good_ratio": 0.9, "monitored_min": 55, "alerts": 1},
    {"hour": 10, "good_ratio": 0.6, "monitored_min": 60, "alerts": 5}
  ],
  "stretch_suggested": 3,
  "stretch_done": 1,
  "user_id": "user-42"       // 쿨다운 구분용 (권장)
}
```

```json
{
  "summary": "바른 자세 유지율은 74%로 양호한 수준입니다. ...",      // 2~3문장, 담백한 서술체
  "grade": "excellent" | "good" | "normal" | "bad",
  "highlights": ["10시 유지율이 60%로 가장 낮았습니다", ...],        // 최대 4개
  "advice": ["50분마다 한 번씩 스트레칭으로 몸을 푸는 것을 권장합니다", ...],  // 최대 3개
  "source": "llm" | "rule_based",   // ANTHROPIC_API_KEY 없거나 호출 실패 시 rule_based
  "stats": {"total_monitored_min": 115, "avg_good_ratio": 0.74, "total_alerts": 6,
            "worst_hour": {...}, "best_hour": {...}, "stretch_done": 1, "stretch_suggested": 3},
  "analysis_cached": false,           // true면 쿨다운으로 기존 코멘트 재사용 (stats는 최신)
  "analysis_age_sec": 0.0,            // 재사용한 코멘트가 만들어진 지 몇 초 됐는지
  "cooldown_remaining_sec": 300.0     // 다음 LLM 갱신까지 남은 시간 — UI에 "N분 후 갱신" 표시용
}
```

LLM 분석 모델은 `claude-sonnet-5` (환경변수 `ANTHROPIC_MODEL`로 변경 가능).

---

## 권장 연동 플로우

```
[초기 진입]
GET /api/guide → 뷰 선택 UI
GET /api/guide/{view} → 실루엣 오버레이 그리기
POST /api/align (반복) → aligned=true면 촬영 버튼 활성화
POST /api/calibrate → baseline_id를 backend에 저장

[모니터링]
POST /api/monitor/frame 1~2초 간격 (또는 WS /api/monitor/ws)
alert_level 1 → 팝업 / 2 → 강한 경고
issue_codes를 모아 뒀다가 스트레칭 제안 타이밍(50~60분)에 사용
일시정지/재개 시 POST /api/monitor/reset

[스트레칭]
POST /api/stretch/recommend (모니터링에서 모은 issue_codes)
GET /api/guide/stretch + POST /api/align(view=stretch) → 위치 잡기
POST /api/stretch/session → session_id
POST /api/stretch/session/{id}/frame (반복) → completed=true면 종료

[리포트]
backend가 모니터링 응답(posture_ok, alerts)을 시간대별로 집계
POST /api/report/daily/analyze → 일일 리포트 화면에 표시
```

## 구조

```
app/
  main.py              FastAPI 엔트리 (CORS, 라우터, 에러 핸들러)
  schemas.py           요청 pydantic 모델
  store.py             baseline(JSON 파일 영속) · 모니터/스트레칭 세션(인메모리)
  config.py            임계값 · 엄격도 배율 · 경고 시간 기본값
  routers/
    guide.py           /api/guide /api/align /api/calibrate /api/baseline
    monitor.py         /api/monitor/frame /api/monitor/reset WS /api/monitor/ws
    stretch.py         /api/stretch/*
    report.py          /api/report/daily/analyze
  core/
    pose_engine.py     MediaPipe Pose Landmarker 래퍼 (base64 → 33 landmarks)
    guides.py          뷰별 오버레이 가이드(하드코딩) + 정합 판정
    posture.py         자세 지표 계산 · baseline 대비 판정 · 경고 상태머신
    stretch.py         스트레칭 카탈로그 · 추천 · 동작 감지 규칙
    report.py          일일 리포트 분석 (Claude, 규칙 기반 폴백)
    view_invariant.py  월드 랜드마크(3D) 기반 뷰 불변 자세 특징 (2장 캘리브레이션 실험용)
models/
  pose_landmarker_lite.task   MediaPipe pose 모델
experiments/
  two_shot_test.py            2장 촬영(정면+자유 배치) 캘리브레이션 실험 + 팀원용 CLI
  two-shot-calibration.md     실험 결과와 기존 방식 대비 트레이드오프 (결정용 문서)
```

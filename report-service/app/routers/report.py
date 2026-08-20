"""자세 진단 리포트 분석 (일일 레포트 → LLM 해석, 실패 시 규칙 기반 폴백)."""

from datetime import date as _date
from typing import Any, Dict

from fastapi import APIRouter, Body

from app.core import report

router = APIRouter()


def _to_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):  # Overflow: JSON Infinity 방어
        return default


def _to_float(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default  # NaN/Infinity 방어


@router.post("/report/daily/analyze")
def analyze_daily(req: Dict[str, Any] = Body(default_factory=dict)):
    """backend가 집계한 일일 데이터를 보내면 요약·하이라이트·조언을 돌려준다.

    backend 연동 중 페이로드 형식이 흔들려도 500이 나지 않도록 스키마 검증
    대신 관대한 클리닝을 쓴다: good_ratio가 1보다 크면 %(0~100)로 보고
    100으로 나누고, 형이 어긋난 hourly 항목은 건너뛴다.

    - 응답의 source가 "llm"이면 Claude 분석, "rule_based"면 폴백 결과.
    - 종료 버튼 연타 보호: 같은 (user_id, date)로 쿨다운(기본 5분) 안에 다시
      호출하면 LLM을 부르지 않고 기존 코멘트를 재사용(analysis_cached=true)하되,
      stats(일일 레포트 수치)는 항상 새로 계산해 돌려준다.
    """
    user_id = str(req.get("user_id") or "default_user")
    date_str = str(req.get("date") or _date.today().isoformat())
    hourly = req.get("hourly") or []

    cleaned_hourly = []
    if isinstance(hourly, list):
        for h in hourly:
            if not isinstance(h, dict):
                continue
            raw_ratio = _to_float(h.get("good_ratio", 0.0))
            if raw_ratio > 1.0:  # %(0~100) 단위로 온 경우 흡수
                raw_ratio = raw_ratio / 100.0
            cleaned_hourly.append({
                "hour": _to_int(h.get("hour", 0)),
                "good_ratio": max(0.0, min(1.0, raw_ratio)),
                "monitored_min": max(0.0, _to_float(h.get("monitored_min", 0.0))),
                "alerts": max(0, _to_int(h.get("alerts", 0))),
            })

    cleaned_payload = {
        "date": date_str,
        "hourly": cleaned_hourly,
        "stretch_suggested": _to_int(req.get("stretch_suggested", 0)),
        "stretch_done": _to_int(req.get("stretch_done", 0)),
        "user_id": user_id,
        "user_name": req.get("user_name"),
    }

    # force=true면 쿨다운을 건너뛴다 — 사용자가 '재생성'을 직접 누른 경우
    force = bool(req.get("force"))
    print(
        f"[report] 분석 요청: user={user_id}, date={date_str}, hourly {len(cleaned_hourly)}건, "
        f"스트레칭 {cleaned_payload['stretch_done']}/{cleaned_payload['stretch_suggested']}회"
        f"{' (force)' if force else ''}",
        flush=True,
    )
    return report.analyze_daily(cleaned_payload, cache_key=f"{user_id}:{date_str}", force=force)

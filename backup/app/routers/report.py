"""자세 진단 리포트 분석 (일일 레포트 → LLM 해석, 실패 시 규칙 기반 폴백)."""

from typing import Any, Dict
from fastapi import APIRouter, Body
import logging
import json

from app.core import report

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/report/daily/analyze")
def analyze_daily(req: Dict[str, Any] = Body(default_factory=dict)):
    """backend가 집계한 일일 데이터를 보내면 요약·하이라이트·조언을 돌려준다."""
    print(f"\n🔥 [FastAPI AI Router] 1. 수신된 원본 요청:\n{json.dumps(req, ensure_ascii=False, indent=2)}", flush=True)

    user_id = str(req.get("user_id") or "default_user")
    date_str = str(req.get("date") or "2026-08-19")
    hourly = req.get("hourly") or []

    # hourly 항목들 안전하게 클리닝
    cleaned_hourly = []
    if isinstance(hourly, list):
        for h in hourly:
            if not isinstance(h, dict):
                continue
            try:
                hour = int(h.get("hour", 0))
                raw_ratio = float(h.get("good_ratio", 0.0))
                if raw_ratio > 1.0:
                    raw_ratio = raw_ratio / 100.0
                good_ratio = max(0.0, min(1.0, raw_ratio))
                monitored_min = max(0.0, float(h.get("monitored_min", 0.0)))
                alerts = max(0, int(h.get("alerts", 0)))
                cleaned_hourly.append({
                    "hour": hour,
                    "good_ratio": good_ratio,
                    "monitored_min": monitored_min,
                    "alerts": alerts,
                })
            except Exception as e:
                print(f"⚠️ Error parsing hourly item {h}: {e}", flush=True)
                continue

    cleaned_payload = {
        "date": date_str,
        "hourly": cleaned_hourly,
        "stretch_suggested": int(req.get("stretch_suggested", 0) or 0),
        "stretch_done": int(req.get("stretch_done", 0) or 0),
        "user_id": user_id,
        "user_name": req.get("user_name"),
    }

    print(f"🔥 [FastAPI AI Router] 2. 정제된 페이로드 (hourly 개수: {len(cleaned_hourly)}):\n{json.dumps(cleaned_payload, ensure_ascii=False, indent=2)}", flush=True)

    res = report.analyze_daily(cleaned_payload, cache_key=None)
    print(f"🔥 [FastAPI AI Router] 3. 분석 결과 요약:\n{res.get('summary')}\n", flush=True)
    return res

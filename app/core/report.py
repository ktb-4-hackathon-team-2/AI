"""일일 자세 리포트 분석.

Claude API(모델: claude-opus-5)로 시간대별 자세 데이터를 해석해
요약·하이라이트·조언·아바타 상태를 만든다. API 키가 없거나 호출이
실패하면 규칙 기반 분석으로 폴백해서 데모가 항상 동작하게 한다.
"""

import json
import logging

from app.config import ANTHROPIC_MODEL

logger = logging.getLogger(__name__)

_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "오늘 하루 자세에 대한 2~3문장 요약 (한국어, 아바타가 말하듯 친근한 말투)"},
        "grade": {"type": "string", "enum": ["excellent", "good", "normal", "bad"]},
        "highlights": {
            "type": "array",
            "items": {"type": "string"},
            "description": "짚을만한 추이·주목할 데이터 포인트 (한국어, 최대 4개)",
        },
        "advice": {
            "type": "array",
            "items": {"type": "string"},
            "description": "내일을 위한 구체적인 조언 (한국어, 최대 3개)",
        },
        "avatar_state": {
            "type": "string",
            "enum": ["proud", "happy", "neutral", "worried", "slouching"],
            "description": "리포트와 함께 보여줄 아바타 상태",
        },
    },
    "required": ["summary", "grade", "highlights", "advice", "avatar_state"],
    "additionalProperties": False,
}


def _stats(daily: dict) -> dict:
    hours = daily.get("hourly", [])
    monitored = [h for h in hours if h.get("monitored_min", 0) > 0]
    total_min = sum(h.get("monitored_min", 0) for h in monitored)
    total_alerts = sum(h.get("alerts", 0) for h in monitored)
    if monitored:
        # monitored에 든 버킷은 전부 monitored_min > 0이라 total_min > 0 보장
        avg_ratio = sum(h["good_ratio"] * h.get("monitored_min", 0) for h in monitored) / total_min
        worst = min(monitored, key=lambda h: h["good_ratio"])
        best = max(monitored, key=lambda h: h["good_ratio"])
    else:
        avg_ratio, worst, best = 0.0, None, None
    return {
        "total_monitored_min": total_min,
        "avg_good_ratio": round(avg_ratio, 3),
        "total_alerts": total_alerts,
        "worst_hour": worst,
        "best_hour": best,
        "stretch_done": daily.get("stretch_done", 0),
        "stretch_suggested": daily.get("stretch_suggested", 0),
    }


def _fallback_analysis(daily: dict) -> dict:
    s = _stats(daily)
    r = s["avg_good_ratio"]
    if s["total_monitored_min"] == 0:
        return {
            "summary": "오늘은 모니터링 기록이 없어요. 내일은 함께 바른 자세에 도전해 봐요!",
            "grade": "normal",
            "highlights": [],
            "advice": ["모니터링을 켜 두면 자세 습관을 추적해 드릴 수 있어요"],
            "avatar_state": "neutral",
        }
    if r >= 0.85:
        grade, state = "excellent", "proud"
        summary = f"오늘 바른 자세 유지율이 {round(r*100)}%로 아주 훌륭했어요! 이 감각을 기억해 주세요."
    elif r >= 0.7:
        grade, state = "good", "happy"
        summary = f"바른 자세 유지율 {round(r*100)}%, 꽤 잘 지켰어요. 조금만 더 신경 쓰면 완벽해요."
    elif r >= 0.5:
        grade, state = "normal", "worried"
        summary = f"바른 자세 유지율이 {round(r*100)}%였어요. 자세가 무너지는 시간대가 보여요."
    else:
        grade, state = "bad", "slouching"
        summary = f"오늘은 바른 자세 유지율이 {round(r*100)}%에 그쳤어요. 허리와 목이 걱정돼요."
    highlights = []
    if s["worst_hour"]:
        highlights.append(
            f"{s['worst_hour']['hour']}시에 유지율이 {round(s['worst_hour']['good_ratio']*100)}%로 가장 낮았어요"
        )
    if s["best_hour"]:
        highlights.append(
            f"{s['best_hour']['hour']}시가 {round(s['best_hour']['good_ratio']*100)}%로 가장 좋았어요"
        )
    if s["total_alerts"]:
        highlights.append(f"자세 경고가 총 {s['total_alerts']}회 울렸어요")
    advice = ["50분마다 한 번씩 스트레칭 알림에 따라 몸을 풀어 주세요"]
    if s["stretch_suggested"] and s["stretch_done"] < s["stretch_suggested"]:
        advice.append(
            f"제안된 스트레칭 {s['stretch_suggested']}회 중 {s['stretch_done']}회만 했어요. 내일은 다 채워 봐요"
        )
    return {
        "summary": summary,
        "grade": grade,
        "highlights": highlights[:4],
        "advice": advice[:3],
        "avatar_state": state,
    }


def analyze_daily(daily: dict) -> dict:
    """일일 리포트 데이터 → 분석 결과. LLM 우선, 실패 시 규칙 기반."""
    stats = _stats(daily)
    result = _llm_analysis(daily, stats)
    if result is None:
        result = _fallback_analysis(daily)
        result["source"] = "rule_based"
    else:
        result["source"] = "llm"
    result["stats"] = stats
    return result


def _llm_analysis(daily: dict, stats: dict):
    try:
        import anthropic
        # 리포트 화면이 무한정 기다리지 않도록 시간 상한을 두고, 실패하면
        # 재시도 없이 바로 규칙 기반으로 폴백한다
        client = anthropic.Anthropic(timeout=60.0, max_retries=0)
        payload = {"daily_report": daily, "computed_stats": stats}
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            # opus-5는 기본으로 사고(thinking)가 켜져 있고 max_tokens에
            # 사고 토큰까지 포함되므로 JSON이 잘리지 않게 여유를 둔다
            max_tokens=8192,
            output_config={
                "effort": "low",  # 짧은 요약 작업 — 지연시간 우선
                "format": {"type": "json_schema", "schema": _REPORT_SCHEMA},
            },
            system=(
                "당신은 자세 교정 서비스의 아바타 캐릭터로서 사용자의 일일 자세 데이터를 분석합니다. "
                "hourly는 시간대별 바른 자세 유지율(good_ratio 0~1), 모니터링 시간(분), 경고 횟수입니다. "
                "짚을만한 추이와 주목할 데이터를 근거 숫자와 함께 해석하고, 친근하되 과장 없이 말하세요. "
                "모든 출력은 한국어로 작성합니다."
            ),
            messages=[{
                "role": "user",
                "content": "다음 일일 자세 데이터를 분석해 주세요:\n" + json.dumps(payload, ensure_ascii=False),
            }],
        )
        if response.stop_reason == "refusal":
            return None
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
    except Exception as e:  # 키 없음/네트워크/파싱 등 어떤 실패든 폴백
        logger.warning("LLM 리포트 분석 실패, 규칙 기반으로 폴백: %s", e)
        return None

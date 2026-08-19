"""일일 자세 리포트 분석.

Claude API(기본 모델: claude-sonnet-5)로 시간대별 자세 데이터를 해석해
요약·하이라이트·조언을 만든다. API 키가 없거나 호출이 실패하면
규칙 기반 분석으로 폴백해서 데모가 항상 동작하게 한다.

아바타 말투·아바타 상태 생성은 기획 보류로 주석처리해 둠 —
확정되면 avatar_state 관련 주석을 해제하면 된다.
"""

import json
import logging
import threading
import time

from app.config import ANTHROPIC_MODEL, REPORT_LLM_COOLDOWN_SEC

logger = logging.getLogger(__name__)

# (user_id:date)별 LLM 분석 캐시 — 종료 버튼 연타 시 쿨다운 동안 재사용.
# 항목 수는 유저×날짜 수준이라 인메모리로 충분하다.
_analysis_cache = {}
_cache_guard = threading.Lock()
_key_locks = {}


def _lock_for(key: str) -> threading.Lock:
    with _cache_guard:
        if key not in _key_locks:
            _key_locks[key] = threading.Lock()
        return _key_locks[key]

_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "오늘 하루 자세 데이터 요약 (한국어, 2~3문장, 담백한 서술체)"},
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
        # 아바타 상태 생성 — 기획 보류로 주석처리
        # "avatar_state": {
        #     "type": "string",
        #     "enum": ["proud", "happy", "neutral", "worried", "slouching"],
        #     "description": "리포트와 함께 보여줄 아바타 상태",
        # },
    },
    "required": ["summary", "grade", "highlights", "advice"],
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
            "summary": "오늘은 모니터링 기록이 없습니다.",
            "grade": "normal",
            "highlights": [],
            "advice": ["모니터링을 켜 두면 자세 습관을 추적할 수 있습니다"],
            # "avatar_state": "neutral",  # 아바타 상태 — 기획 보류
        }
    if r >= 0.85:
        grade = "excellent"
        summary = f"오늘 바른 자세 유지율은 {round(r*100)}%로 매우 높았습니다."
    elif r >= 0.7:
        grade = "good"
        summary = f"바른 자세 유지율은 {round(r*100)}%로 양호한 수준입니다."
    elif r >= 0.5:
        grade = "normal"
        summary = f"바른 자세 유지율은 {round(r*100)}%였습니다. 자세가 무너지는 시간대가 있습니다."
    else:
        grade = "bad"
        summary = f"바른 자세 유지율이 {round(r*100)}%로 낮은 편입니다."
    highlights = []
    if s["worst_hour"]:
        highlights.append(
            f"{s['worst_hour']['hour']}시 유지율이 {round(s['worst_hour']['good_ratio']*100)}%로 가장 낮았습니다"
        )
    if s["best_hour"]:
        highlights.append(
            f"{s['best_hour']['hour']}시 유지율이 {round(s['best_hour']['good_ratio']*100)}%로 가장 높았습니다"
        )
    if s["total_alerts"]:
        highlights.append(f"자세 경고가 총 {s['total_alerts']}회 발생했습니다")
    advice = ["50분마다 한 번씩 스트레칭으로 몸을 푸는 것을 권장합니다"]
    if s["stretch_suggested"] and s["stretch_done"] < s["stretch_suggested"]:
        advice.append(
            f"제안된 스트레칭 {s['stretch_suggested']}회 중 {s['stretch_done']}회를 수행했습니다"
        )
    return {
        "summary": summary,
        "grade": grade,
        "highlights": highlights[:4],
        "advice": advice[:3],
        # "avatar_state": state,  # 아바타 상태 — 기획 보류
    }


def analyze_daily(daily: dict, cache_key: str = None, cooldown_sec: float = None) -> dict:
    """일일 리포트 데이터 → 분석 결과. LLM 우선, 실패 시 규칙 기반.

    cache_key를 주면 분석 코멘트에 쿨다운이 걸린다: 마지막 분석 후
    cooldown_sec(기본 5분) 안의 재호출은 LLM을 다시 부르지 않고 기존
    코멘트를 재사용한다. **stats는 항상 새로 계산**하므로 일일 레포트
    수치는 연타해도 갱신된다.

    응답 메타: analysis_cached(재사용 여부), analysis_age_sec,
    cooldown_remaining_sec(다음 LLM 갱신까지 남은 시간).
    """
    stats = _stats(daily)
    cooldown = REPORT_LLM_COOLDOWN_SEC if cooldown_sec is None else cooldown_sec

    def _fresh() -> dict:
        result = _llm_analysis(daily, stats)
        if result is None:
            result = _fallback_analysis(daily)
            result["source"] = "rule_based"
        else:
            result["source"] = "llm"
        return result

    if cache_key is None:
        result = _fresh()
        result["stats"] = stats
        result["analysis_cached"] = False
        result["analysis_age_sec"] = 0.0
        result["cooldown_remaining_sec"] = 0.0
        return result

    # 키별 락으로 동시 연타를 직렬화 → 쿨다운 안에서 LLM은 최대 1회
    with _lock_for(cache_key):
        now = time.time()
        entry = _analysis_cache.get(cache_key)
        if entry is not None and now - entry["at"] < cooldown:
            age = now - entry["at"]
            result = dict(entry["analysis"])
            result["stats"] = stats  # 통계는 항상 최신
            result["analysis_cached"] = True
            result["analysis_age_sec"] = round(age, 1)
            result["cooldown_remaining_sec"] = round(cooldown - age, 1)
            return result

        result = _fresh()
        # 실패(rule_based 폴백)도 쿨다운을 시작한다 — 목적이 API 남용 방지이므로
        _analysis_cache[cache_key] = {"analysis": dict(result), "at": now}
        result["stats"] = stats
        result["analysis_cached"] = False
        result["analysis_age_sec"] = 0.0
        result["cooldown_remaining_sec"] = round(cooldown, 1)
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
            # 사고(thinking) 토큰도 max_tokens에 포함되므로 JSON이 잘리지 않게 여유를 둔다
            max_tokens=8192,
            output_config={
                "effort": "low",  # 짧은 요약 작업 — 지연시간 우선
                "format": {"type": "json_schema", "schema": _REPORT_SCHEMA},
            },
            system=(
                "당신은 자세 교정 서비스의 데이터 분석가로서 사용자의 일일 자세 데이터를 분석합니다. "
                "hourly는 시간대별 바른 자세 유지율(good_ratio 0~1), 모니터링 시간(분), 경고 횟수입니다. "
                "짚을만한 추이와 주목할 데이터를 근거 숫자와 함께 담백하고 사실 위주로 서술하세요. "
                "과장·감탄·이모지 없이 평서문으로, 모든 출력은 한국어로 작성합니다."
                # 아바타 말투 버전(기획 보류): "당신은 자세 교정 서비스의 아바타 캐릭터로서 ... "
                # "친근하되 과장 없이 말하세요."
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

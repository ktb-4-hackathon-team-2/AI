import os

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# 종료 버튼 연타로 LLM 리포트 분석이 과다 호출되는 것을 막는 쿨다운(초).
# 쿨다운 안에는 기존 코멘트를 재사용하고 통계(stats)만 새로 계산한다.
REPORT_LLM_COOLDOWN_SEC = float(os.environ.get("REPORT_LLM_COOLDOWN_SEC", "300"))

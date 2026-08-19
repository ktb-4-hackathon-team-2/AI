"""자세 진단 리포트 분석 (일일 레포트 → LLM 해석, 실패 시 규칙 기반 폴백)."""

from fastapi import APIRouter

from app.core import report
from app.schemas import DailyReportRequest

router = APIRouter()


@router.post("/report/daily/analyze")
def analyze_daily(req: DailyReportRequest):
    """backend가 집계한 일일 데이터를 보내면 요약·하이라이트·조언을 돌려준다.

    - 응답의 source가 "llm"이면 Claude 분석, "rule_based"면 폴백 결과.
    - 종료 버튼 연타 보호: 같은 (user_id, date)로 5분 안에 다시 호출하면
      LLM을 부르지 않고 기존 코멘트를 재사용(analysis_cached=true)하되,
      stats(일일 레포트 수치)는 항상 새로 계산해 돌려준다.
    """
    cache_key = f"{req.user_id or 'anon'}:{req.date}"
    return report.analyze_daily(req.model_dump(), cache_key=cache_key)

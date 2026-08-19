"""자세 진단 리포트 분석 (일일 레포트 → LLM 해석, 실패 시 규칙 기반 폴백)."""

from fastapi import APIRouter

from app.core import report
from app.schemas import DailyReportRequest

router = APIRouter()


@router.post("/report/daily/analyze")
def analyze_daily(req: DailyReportRequest):
    """backend가 집계한 일일 데이터를 보내면 요약·하이라이트·조언·아바타 상태를 돌려준다.

    응답의 source가 "llm"이면 Claude 분석, "rule_based"면 폴백 결과.
    """
    return report.analyze_daily(req.model_dump())

from typing import List, Optional

from pydantic import BaseModel, Field


class HourlyBucket(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    good_ratio: float = Field(..., ge=0, le=1, description="해당 시간대 바른 자세 유지율")
    monitored_min: float = Field(0, description="해당 시간대 모니터링 시간(분)")
    alerts: int = Field(0, description="해당 시간대 경고 횟수")


class DailyReportRequest(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    hourly: List[HourlyBucket]
    stretch_suggested: int = 0
    stretch_done: int = 0
    user_id: Optional[str] = Field(
        None,
        description="LLM 쿨다운 구분용 유저 id (권장 — 없으면 전체 공유 키로 쿨다운)",
    )
    user_name: Optional[str] = Field(None, description="아바타가 부를 이름 (선택, 기획 보류)")

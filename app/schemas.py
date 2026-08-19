from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ImageRequest(BaseModel):
    image: str = Field(..., description="JPEG/PNG base64 (data URL 허용)")


class AlignRequest(ImageRequest):
    view: str = Field(..., description="front | left_diagonal | right_diagonal | stretch")


class CalibrationRequest(ImageRequest):
    user_id: str = Field(..., description="유저 식별자 (backend가 관리하는 id)")
    view: str = Field(..., description="front | left_diagonal | right_diagonal")


class MonitorFrameRequest(ImageRequest):
    baseline_id: str
    session_id: Optional[str] = Field(
        None, description="경고 지속시간 추적용 클라이언트 세션 id. 없으면 baseline_id로 대체"
    )
    strictness: Literal["low", "medium", "high"] = Field("medium", description="경고 엄격도")
    warn_after_sec: Optional[float] = Field(None, ge=0, description="이 시간 이상 나쁜 자세 지속 시 팝업 경고")
    alarm_after_sec: Optional[float] = Field(None, ge=0, description="이 시간 이상 지속 시 강한 경고")


class MonitorResetRequest(BaseModel):
    session_id: str = Field(..., description="리셋할 모니터링 세션 (baseline_id로 대체했다면 그 값)")


class StretchRecommendRequest(BaseModel):
    issue_codes: List[str] = Field(
        default_factory=list,
        description="모니터링 응답의 issues[].code 목록. 비우면 기본 추천",
    )


class StretchStartRequest(BaseModel):
    exercise_id: str


class StretchFrameRequest(ImageRequest):
    pass


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
    user_name: Optional[str] = Field(None, description="아바타가 부를 이름 (선택)")

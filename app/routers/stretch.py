"""스트레칭 카탈로그 · 추천 · 실시간 따라하기 감지 세션."""

from fastapi import APIRouter, HTTPException

from app.core import stretch
from app.core.pose_engine import landmarks_from_image_b64
from app.schemas import StretchFrameRequest, StretchRecommendRequest, StretchStartRequest
from app.store import stretch_sessions

router = APIRouter()


@router.get("/stretch/exercises")
def list_exercises():
    """앉아서 하는 상반신 스트레칭 전체 목록."""
    return {"exercises": [stretch.public_exercise(e) for e in stretch.EXERCISES]}


@router.post("/stretch/recommend")
def recommend(req: StretchRecommendRequest):
    """모니터링에서 감지된 문제(issue_codes) 기반 스트레칭 추천 (관련도 순)."""
    return {"exercises": stretch.recommend(req.issue_codes)}


@router.post("/stretch/session")
def start_session(req: StretchStartRequest):
    """따라하기 세션 시작. 이후 프레임을 보내면 유지 시간을 누적한다."""
    exercise = stretch.get_exercise(req.exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="해당 스트레칭을 찾을 수 없습니다")
    session = stretch_sessions.start(req.exercise_id, exercise["hold_sec"])
    return {**session, "exercise": stretch.public_exercise(exercise)}


@router.post("/stretch/session/{session_id}/frame")
def session_frame(session_id: str, req: StretchFrameRequest):
    """한 프레임 판정: 동작 중인지 + 누적 유지 시간 + 완료 여부."""
    session = stretch_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")

    landmarks = landmarks_from_image_b64(req.image)
    if landmarks is None:
        session = stretch_sessions.update(session_id, in_pose=False)
        return {
            "detected": False,
            "in_pose": False,
            "feedback": ["화면에서 사람이 감지되지 않았어요"],
            "held_sec": round(session["held_sec"], 1),
            "hold_target_sec": session["hold_target_sec"],
            "completed": session["completed"],
        }

    check = stretch.check_frame(session["exercise_id"], landmarks)
    session = stretch_sessions.update(session_id, in_pose=check["in_pose"])
    return {
        "detected": True,
        "landmarks": landmarks,
        **check,
        "held_sec": round(session["held_sec"], 1),
        "hold_target_sec": session["hold_target_sec"],
        "completed": session["completed"],
    }

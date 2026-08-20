"""자세 가이드 오버레이 · 실시간 정합 판정 · 초기 자세 캘리브레이션."""

from fastapi import APIRouter, HTTPException

from app.core import guides, posture
from app.core.pose_engine import landmarks_from_image_b64
from app.schemas import AlignRequest, CalibrationRequest
from app.store import baselines

router = APIRouter()


def _check_view(view: str, allowed):
    if view not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"view는 {allowed} 중 하나여야 합니다 (받은 값: {view})",
        )


@router.get("/guide")
def list_guides():
    """선택 가능한 카메라 뷰 목록 (초기 진입 화면용)."""
    return {
        "views": [
            {"view": v, "label": guides.get_guide(v)["label"]}
            for v in guides.ALL_VIEWS
        ],
        "calibration_views": guides.VIEWS,
    }


@router.get("/guide/{view}")
def get_guide(view: str):
    """뷰별 오버레이 가이드 (앵커 + 실루엣 폴리곤, 정규화 좌표 0~1)."""
    _check_view(view, guides.ALL_VIEWS)
    return guides.get_guide(view)


@router.post("/align")
def check_alignment(req: AlignRequest):
    """실시간 프레임이 가이드 실루엣에 맞는지 판정. 캘리브레이션 전 위치 잡기용."""
    _check_view(req.view, guides.ALL_VIEWS)
    landmarks = landmarks_from_image_b64(req.image)
    if landmarks is None:
        return {
            "detected": False,
            "aligned": False,
            "offsets": {},
            "messages": ["화면에서 사람이 감지되지 않았어요. 카메라 앞에 앉아 주세요"],
        }
    result = guides.check_alignment(landmarks, req.view)
    return {"detected": True, "landmarks": landmarks, **result}


@router.post("/calibrate")
def calibrate(req: CalibrationRequest):
    """바른 자세 한 컷 촬영 → 스켈레톤 좌표만 저장, baseline_id 반환."""
    _check_view(req.view, guides.VIEWS)
    landmarks = landmarks_from_image_b64(req.image)
    if landmarks is None:
        return {"ok": False, "reason": "person_not_detected",
                "messages": ["사람이 감지되지 않았어요. 카메라 앞에 앉아 주세요"]}
    if not posture.visibility_ok(landmarks):
        return {"ok": False, "reason": "upper_body_not_visible",
                "messages": ["얼굴과 양쪽 어깨가 모두 화면에 나오게 해 주세요"]}

    alignment = guides.check_alignment(landmarks, req.view)
    metrics = posture.compute_metrics(landmarks)
    record = baselines.create(req.user_id, req.view, metrics, landmarks)
    return {
        "ok": True,
        "baseline_id": record["baseline_id"],
        "view": req.view,
        "aligned": alignment["aligned"],
        "alignment_messages": alignment["messages"],
        "metrics": metrics,
        "landmarks": landmarks,
    }


@router.get("/baseline/{baseline_id}")
def get_baseline(baseline_id: str):
    record = baselines.get(baseline_id)
    if record is None:
        raise HTTPException(status_code=404, detail="baseline을 찾을 수 없습니다")
    return record


@router.get("/users/{user_id}/baseline")
def latest_baseline(user_id: str):
    """해당 유저의 가장 최근 baseline (재접속 시 재캘리브레이션 생략용)."""
    record = baselines.latest_for_user(user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="저장된 baseline이 없습니다")
    return record

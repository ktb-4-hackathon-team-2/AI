"""실시간 자세 모니터링: baseline 대비 판정 + 지속시간 기반 경고 알람.

REST(/monitor/frame)와 WebSocket(/monitor/ws) 두 가지로 제공한다.
프레임 주기는 프론트가 정한다 (1~2초에 1프레임 권장 — pose 추론은 CPU에서 수십 ms).
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.config import DEFAULT_ALARM_AFTER_SEC, DEFAULT_WARN_AFTER_SEC
from app.core import posture
from app.core.pose_engine import ImageDecodeError, landmarks_from_image_b64
from app.schemas import MonitorFrameRequest, MonitorResetRequest
from app.store import baselines, monitor_sessions

logger = logging.getLogger(__name__)
router = APIRouter()


def _process_frame(req: MonitorFrameRequest, fallback_session_key: str = None) -> dict:
    record = baselines.get(req.baseline_id)
    if record is None:
        raise HTTPException(status_code=404, detail="baseline을 찾을 수 없습니다")

    warn_after = req.warn_after_sec if req.warn_after_sec is not None else DEFAULT_WARN_AFTER_SEC
    alarm_after = req.alarm_after_sec if req.alarm_after_sec is not None else DEFAULT_ALARM_AFTER_SEC
    if warn_after > alarm_after:
        raise HTTPException(
            status_code=422,
            detail="warn_after_sec는 alarm_after_sec보다 클 수 없습니다",
        )
    session_key = req.session_id or fallback_session_key or req.baseline_id
    tracker = monitor_sessions.tracker(session_key, warn_after, alarm_after)

    landmarks = landmarks_from_image_b64(req.image)
    if landmarks is None or not posture.visibility_ok(landmarks):
        # 자리 비움/가림은 나쁜 자세로 치지 않는다 (지속시간 카운트도 멈춤)
        tracker.note_absence()
        return {
            "detected": False,
            "posture_ok": None,
            "score": None,
            "issues": [],
            "deviations": {},
            "alert_level": 0,
            "alarm": False,
            "bad_duration_sec": 0.0,
            "messages": ["화면에서 사람이 감지되지 않았어요"],
        }

    metrics = posture.compute_metrics(landmarks)
    evaluation = posture.evaluate_against_baseline(
        metrics, record["metrics"], req.strictness
    )
    alert = tracker.update(evaluation["posture_ok"])
    return {
        "detected": True,
        "landmarks": landmarks,
        "issue_codes": [i["code"] for i in evaluation["issues"]],
        **evaluation,
        **alert,
    }


@router.post("/monitor/frame")
def monitor_frame(req: MonitorFrameRequest):
    """한 프레임 판정. alert_level 0=정상, 1=팝업 경고, 2=강한 경고(알람)."""
    return _process_frame(req)


@router.post("/monitor/reset")
def monitor_reset(req: MonitorResetRequest):
    """일시정지/모니터링 재시작 시 경고 지속시간 상태 초기화."""
    monitor_sessions.reset(req.session_id)
    return {"ok": True}


@router.websocket("/monitor/ws")
async def monitor_ws(ws: WebSocket):
    """프레임 스트리밍용 WebSocket.

    클라이언트 → 서버: /monitor/frame과 같은 JSON.
    서버 → 클라이언트: /monitor/frame과 같은 응답 JSON (에러는 {"error": ...}).
    session_id를 안 보내면 연결 단위로 경고 상태를 추적한다.
    """
    await ws.accept()
    # session_id 없이 여러 클라이언트가 같은 baseline을 볼 때 AlertTracker를
    # 공유하지 않도록 연결마다 고유 fallback 키를 쓴다
    conn_key = "ws-" + uuid.uuid4().hex[:12]
    try:
        while True:
            try:
                payload = await ws.receive_json()
                req = MonitorFrameRequest.model_validate(payload)
                result = await run_in_threadpool(_process_frame, req, conn_key)
            except WebSocketDisconnect:
                raise
            except ValidationError as e:
                result = {"error": "invalid_request", "detail": e.errors()}
            except ImageDecodeError as e:
                result = {"error": "image_decode_failed", "detail": str(e)}
            except HTTPException as e:
                result = {"error": "request_rejected", "status": e.status_code, "detail": e.detail}
            except (ValueError, KeyError) as e:  # 비JSON 텍스트/바이너리 프레임
                result = {"error": "invalid_json", "detail": str(e)}
            await ws.send_json(result)
    except WebSocketDisconnect:
        pass
    except Exception:  # 연결별 루프라 어떤 예외든 로그만 남기고 연결 종료
        logger.exception("monitor websocket error")
    finally:
        monitor_sessions.reset(conn_key)

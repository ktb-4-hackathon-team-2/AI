"""간단한 저장소: baseline은 JSON 파일로 영속화, 세션은 인메모리."""

import json
import threading
import time
import uuid

from app.config import BASELINE_FILE
from app.core.posture import AlertTracker

_lock = threading.Lock()


class BaselineStore:
    def __init__(self):
        self._data = {}
        self._load()

    def _load(self):
        if BASELINE_FILE.exists():
            try:
                self._data = json.loads(BASELINE_FILE.read_text())
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def _save(self):
        BASELINE_FILE.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))

    def create(self, user_id: str, view: str, metrics: dict, landmarks: list) -> dict:
        with _lock:
            baseline_id = uuid.uuid4().hex[:12]
            record = {
                "baseline_id": baseline_id,
                "user_id": user_id,
                "view": view,
                "metrics": metrics,
                "landmarks": landmarks,
                "created_at": time.time(),
            }
            self._data[baseline_id] = record
            self._save()
            return record

    def get(self, baseline_id: str):
        return self._data.get(baseline_id)

    def latest_for_user(self, user_id: str):
        records = [r for r in self._data.values() if r["user_id"] == user_id]
        return max(records, key=lambda r: r["created_at"]) if records else None


class MonitorSessions:
    """baseline_id + client 세션별 경고 상태 추적."""

    def __init__(self):
        self._sessions = {}

    def tracker(self, session_key: str, warn_after: float, alarm_after: float) -> AlertTracker:
        with _lock:
            t = self._sessions.get(session_key)
            if t is None:
                t = AlertTracker(warn_after=warn_after, alarm_after=alarm_after)
                self._sessions[session_key] = t
            else:
                t.warn_after = warn_after
                t.alarm_after = alarm_after
            return t

    def reset(self, session_key: str):
        with _lock:
            self._sessions.pop(session_key, None)


class StretchSessions:
    def __init__(self):
        self._sessions = {}

    def start(self, exercise_id: str, hold_sec: float) -> dict:
        with _lock:
            session_id = uuid.uuid4().hex[:12]
            s = {
                "session_id": session_id,
                "exercise_id": exercise_id,
                "hold_target_sec": hold_sec,
                "held_sec": 0.0,
                "last_frame_ts": None,
                "completed": False,
            }
            self._sessions[session_id] = s
            return s

    def get(self, session_id: str):
        return self._sessions.get(session_id)

    def update(self, session_id: str, in_pose: bool, now: float = None) -> dict:
        now = now if now is not None else time.time()
        with _lock:
            s = self._sessions[session_id]
            if in_pose:
                if s["last_frame_ts"] is not None:
                    gap = now - s["last_frame_ts"]
                    if gap <= 2.0:  # 프레임 간격이 정상 범위일 때만 누적
                        s["held_sec"] += gap
                s["last_frame_ts"] = now
            else:
                # 동작이 풀리면 구간을 끊어서, 다시 잡은 첫 프레임이
                # 밖에 있던 시간을 유지 시간으로 계산하지 않게 한다
                s["last_frame_ts"] = None
            if s["held_sec"] >= s["hold_target_sec"]:
                s["completed"] = True
            return s


baselines = BaselineStore()
monitor_sessions = MonitorSessions()
stretch_sessions = StretchSessions()

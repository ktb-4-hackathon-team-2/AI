"""자세 지표 계산 · baseline 대비 편차 판정 · 경고 단계 상태머신."""

import math
import time

from app.config import (
    DEFAULT_ALARM_AFTER_SEC,
    DEFAULT_WARN_AFTER_SEC,
    STRICTNESS_SCALE,
    THRESHOLDS,
)
from app.core import pose_engine as pe

# 자세 판정에 반드시 보여야 하는 랜드마크
REQUIRED_IDS = [pe.NOSE, pe.LEFT_EAR, pe.RIGHT_EAR, pe.LEFT_SHOULDER, pe.RIGHT_SHOULDER]
MIN_VISIBILITY = 0.5


def _pt(lm):
    return lm["x"], lm["y"]


def _mid(a, b):
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def visibility_ok(landmarks) -> bool:
    return all(landmarks[i]["visibility"] >= MIN_VISIBILITY for i in REQUIRED_IDS)


def compute_metrics(landmarks) -> dict:
    """정규화 좌표(x: 0~1, y: 0~1, 아래로 증가) 기반 자세 지표.

    거리(어깨 너비)로 나눠 카메라 거리와 무관하게 만든 값들.
    """
    ls = _pt(landmarks[pe.LEFT_SHOULDER])
    rs = _pt(landmarks[pe.RIGHT_SHOULDER])
    le = _pt(landmarks[pe.LEFT_EAR])
    re_ = _pt(landmarks[pe.RIGHT_EAR])
    nose = _pt(landmarks[pe.NOSE])

    sw = math.dist(ls, rs) or 1e-6          # 어깨 너비 = 거리 프록시
    sc = _mid(ls, rs)                        # 어깨 중심
    ec = _mid(le, re_)                       # 귀 중심 (머리 위치)

    # 어깨선이 수평에서 얼마나 기울었는지 (도)
    shoulder_tilt = math.degrees(math.atan2(rs[1] - ls[1], rs[0] - ls[0]))
    shoulder_tilt = ((shoulder_tilt + 90) % 180) - 90  # -90~90로 정규화

    # 귀 중심→어깨 중심 벡터가 수직에서 기운 각도 (거북목/목 기울기)
    neck_dx = ec[0] - sc[0]
    neck_dy = sc[1] - ec[1]  # 위쪽이 양수
    neck_tilt = math.degrees(math.atan2(neck_dx, neck_dy)) if neck_dy != 0 else 0.0

    # 귀선 기울기 (머리 좌우로 갸웃한 정도)
    head_roll = math.degrees(math.atan2(re_[1] - le[1], re_[0] - le[0]))
    head_roll = ((head_roll + 90) % 180) - 90

    return {
        "shoulder_width": sw,
        "shoulder_tilt_deg": shoulder_tilt,
        "neck_tilt_deg": neck_tilt,
        "head_roll_deg": head_roll,
        "head_down": (sc[1] - nose[1]) / sw,   # 작아질수록 머리를 숙인 것
        "head_forward": neck_dx / sw,          # 대각선 뷰에서 앞뒤 이동이 드러남
        "center_x": sc[0],
        "center_y": sc[1],
    }


def evaluate_against_baseline(metrics: dict, baseline_metrics: dict, strictness: str = "medium") -> dict:
    """현재 지표를 baseline과 비교해 문제 목록과 종합 점수를 낸다.

    Returns:
        {"posture_ok": bool, "score": float(0=완벽), "issues": [{code, message, severity}], "deviations": {...}}
    """
    scale = STRICTNESS_SCALE.get(strictness, 1.0)
    b = baseline_metrics
    issues = []
    deviations = {}

    def check(code, value, threshold, message):
        limit = threshold * scale
        ratio = abs(value) / limit if limit else 0.0
        deviations[code] = round(ratio, 3)
        if ratio >= 1.0:
            issues.append({
                "code": code,
                "message": message,
                "severity": min(ratio, 3.0),
            })
        return ratio

    check(
        "neck_tilt", metrics["neck_tilt_deg"] - b["neck_tilt_deg"],
        THRESHOLDS["neck_tilt_deg"], "목이 기울거나 앞으로 나왔어요 (거북목 주의)",
    )
    check(
        "shoulder_tilt", metrics["shoulder_tilt_deg"] - b["shoulder_tilt_deg"],
        THRESHOLDS["shoulder_tilt_deg"], "어깨가 한쪽으로 기울었어요",
    )
    # head_down은 '감소'만 문제 (머리를 숙임)
    drop = (b["head_down"] - metrics["head_down"]) / max(abs(b["head_down"]), 1e-6)
    check(
        "head_down", max(drop, 0.0),
        THRESHOLDS["head_down_drop"], "고개를 숙이고 있어요",
    )
    lean = metrics["shoulder_width"] / max(b["shoulder_width"], 1e-6) - 1.0
    if lean > 0:
        check("lean_in", lean, THRESHOLDS["lean_ratio"], "화면에 너무 가까워요 (앞으로 기울었어요)")
        deviations.setdefault("lean_out", 0.0)
    else:
        check("lean_out", lean, THRESHOLDS["lean_ratio"], "기준 자세보다 뒤로 처져 있어요")
        deviations.setdefault("lean_in", 0.0)
    check(
        "shift_x", metrics["center_x"] - b["center_x"],
        THRESHOLDS["shift_x"], "기준 위치에서 좌우로 벗어났어요",
    )

    score = round(max(deviations.values(), default=0.0), 3)
    return {
        "posture_ok": len(issues) == 0,
        "score": score,
        "issues": issues,
        "deviations": deviations,
    }


class AlertTracker:
    """나쁜 자세 지속 시간에 따라 경고 단계를 올리는 세션별 상태머신.

    level 0: 정상 / level 1: 팝업 경고 / level 2: 강한 경고(알람).
    """

    def __init__(self, warn_after: float = DEFAULT_WARN_AFTER_SEC,
                 alarm_after: float = DEFAULT_ALARM_AFTER_SEC):
        self.warn_after = warn_after
        self.alarm_after = alarm_after
        self.bad_since = None
        self.last_seen = None

    def update(self, posture_ok: bool, now: float = None) -> dict:
        now = now if now is not None else time.time()
        # 프레임 간격이 너무 길면(모니터링 중단 등) 지속시간 리셋
        if self.last_seen is not None and now - self.last_seen > 30.0:
            self.bad_since = None
        self.last_seen = now

        if posture_ok:
            self.bad_since = None
            return {"alert_level": 0, "bad_duration_sec": 0.0, "alarm": False}

        if self.bad_since is None:
            self.bad_since = now
        duration = now - self.bad_since
        if duration >= self.alarm_after:
            level = 2
        elif duration >= self.warn_after:
            level = 1
        else:
            level = 0
        return {
            "alert_level": level,
            "bad_duration_sec": round(duration, 1),
            "alarm": level >= 2,  # 강한 경고(알람)는 level 2부터
        }

    def note_absence(self, now: float = None):
        """자리 비움/미검출 프레임: 비운 시간은 나쁜 자세 지속시간에서 제외."""
        now = now if now is not None else time.time()
        if self.bad_since is not None and self.last_seen is not None:
            self.bad_since += now - self.last_seen
        self.last_seen = now

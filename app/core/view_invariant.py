"""월드 랜드마크(3D) 기반 뷰 불변 자세 특징.

카메라가 어디에 있든(정면/대각/자유 배치) 같은 값이 나오도록, 몸 내부
기준계(골반→어깨 = 위, 어깨선 = 좌우, 그 외적 = 앞)로만 정의한 특징들.
2장 촬영 캘리브레이션(정면 검증샷 A ↔ 실사용 위치샷 B)에서
"두 사진이 같은 자세인가"를 판정하는 데 쓴다.

수학적으로 카메라 회전·이동에 완전 불변이지만, MediaPipe 월드 랜드마크의
추정 오차(특히 깊이 방향)는 뷰에 따라 달라진다 — 허용 오차는
experiments/two_shot_test.py 의 몬테카를로로 산정했다.
"""

import math

from app.core import pose_engine as pe


def _v(a, b):
    return (b[0] - a[0], b[1] - a[1], b[2] - a[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a):
    n = math.sqrt(_dot(a, a)) or 1e-9
    return (a[0] / n, a[1] / n, a[2] / n)


def _pt(lms, i):
    lm = lms[i]
    return (lm["x"], lm["y"], lm["z"])


def compute_features(world_landmarks) -> dict:
    """몸 내부 기준계 기반 자세 특징 (전부 카메라 위치와 무관).

    Returns:
        neck_flexion_deg   목이 몸통 위 방향에서 앞으로 꺾인 각도 (거북목 +)
        head_forward_ratio 귀중심이 어깨중심보다 앞으로 나간 거리 / 어깨너비
        head_height_ratio  귀중심-어깨중심 세로 거리 / 어깨너비 (숙이면 감소)
        lateral_lean_deg   어깨선이 골반선 대비 좌우로 기운 각도
    """
    l_sh, r_sh = _pt(world_landmarks, pe.LEFT_SHOULDER), _pt(world_landmarks, pe.RIGHT_SHOULDER)
    l_hip, r_hip = _pt(world_landmarks, 23), _pt(world_landmarks, 24)
    l_ear, r_ear = _pt(world_landmarks, pe.LEFT_EAR), _pt(world_landmarks, pe.RIGHT_EAR)
    nose = _pt(world_landmarks, pe.NOSE)

    mid_sh = _mid(l_sh, r_sh)
    mid_hip = _mid(l_hip, r_hip)
    mid_ear = _mid(l_ear, r_ear)
    sw = math.sqrt(_dot(_v(r_sh, l_sh), _v(r_sh, l_sh))) or 1e-9

    up = _norm(_v(mid_hip, mid_sh))                      # 몸통 위
    right = _norm(_add(_v(r_sh, l_sh), _v(r_hip, l_hip)))  # 어깨+골반 좌우축 평균
    fwd = _norm(_cross(up, right))
    # 앞 방향 부호는 코가 몸 앞에 있다는 사실로 고정 (좌표계 손잡이 무관)
    if _dot(fwd, _v(mid_sh, nose)) < 0:
        fwd = (-fwd[0], -fwd[1], -fwd[2])

    neck = _v(mid_sh, mid_ear)
    neck_flexion = math.degrees(math.atan2(_dot(neck, fwd), _dot(neck, up)))

    # 어깨선-골반선 롤: 앞 방향에 수직인 평면에서 두 선의 각도 차
    def _roll(line):
        return math.atan2(_dot(line, up), _dot(line, right))
    lateral_lean = math.degrees(_roll(_v(r_sh, l_sh)) - _roll(_v(r_hip, l_hip)))
    lateral_lean = ((lateral_lean + 180) % 360) - 180

    return {
        "neck_flexion_deg": round(neck_flexion, 2),
        "head_forward_ratio": round(_dot(neck, fwd) / sw, 4),
        "head_height_ratio": round(_dot(neck, up) / sw, 4),
        "lateral_lean_deg": round(lateral_lean, 2),
    }


# 허용 오차: experiments/two_shot_test.py 몬테카를로에서 같은 자세를
# 다른 뷰(요 0~45도)에서 봤을 때 특징 차이의 97.5퍼센타일 + 10% 여유.
# 전제: 촬영당 약 20프레임(1~2초)의 특징을 평균한 값끼리 비교할 것 —
# 단일 프레임 비교는 깊이 노이즈 때문에 판별력이 없다 (실험 2 참고).
DEFAULT_TOLERANCES = {
    "neck_flexion_deg": 9.0,
    "head_forward_ratio": 0.075,
    "head_height_ratio": 0.032,
    "lateral_lean_deg": 4.0,
}


def compare_postures(features_a: dict, features_b: dict, tolerances: dict = None) -> dict:
    """두 프레임의 자세가 같은지 판정 (2장 캘리브레이션의 A↔B 교차 검증).

    Returns:
        {"same_posture": bool, "diffs": {...}, "exceeded": [feature, ...]}
    """
    tol = tolerances or DEFAULT_TOLERANCES
    diffs, exceeded = {}, []
    for key, limit in tol.items():
        d = abs(features_a[key] - features_b[key])
        diffs[key] = round(d, 4)
        if d > limit:
            exceeded.append(key)
    return {"same_posture": not exceeded, "diffs": diffs, "exceeded": exceeded}

"""스트레칭 카탈로그 · 자세 문제 기반 추천 · 실시간 따라하기 감지.

모든 스트레칭은 앉아서 하는 상반신 동작(정면 뷰 기준)이다.
감지는 랜드마크 기반 규칙으로, 프레임마다 "동작 중인지"를 판정하고
세션이 유지 시간(hold)을 누적해 완료 여부를 돌려준다.
"""

import math

from app.core import pose_engine as pe


def _pt(lms, i):
    return lms[i]["x"], lms[i]["y"]


def _shoulder_width(lms):
    return math.dist(_pt(lms, pe.LEFT_SHOULDER), _pt(lms, pe.RIGHT_SHOULDER)) or 1e-6


def _head_roll_deg(lms):
    """머리 좌우 기울기 (도). 해부학적 왼쪽으로 기울이면 양수가 되도록
    프레임 미러링 여부(어깨 라벨의 이미지상 순서)로 부호를 정규화한다."""
    le, re_ = _pt(lms, pe.LEFT_EAR), _pt(lms, pe.RIGHT_EAR)
    a = math.degrees(math.atan2(re_[1] - le[1], re_[0] - le[0]))
    roll = ((a + 90) % 180) - 90
    # raw 프레임: 해부학적 왼어깨가 이미지 오른쪽(x 큼) → 그대로.
    # 미러링 프레임: 왼어깨가 이미지 왼쪽 → 부호 반전.
    if lms[pe.LEFT_SHOULDER]["x"] < lms[pe.RIGHT_SHOULDER]["x"]:
        roll = -roll
    return roll


def _visible(lms, ids, th=0.5):
    return all(lms[i]["visibility"] >= th for i in ids)


# ---------------------------------------------------------------- 감지 규칙
# 각 함수는 (in_pose: bool, feedback: list[str]) 반환.
# 화면상 좌우는 카메라 원본 기준(유저의 오른쪽 = 화면 왼쪽 아님에 주의) —
# 정면 셀피 화면에서는 미러링되므로 문구는 "머리를 어깨 쪽으로" 식의 중립 표현 사용.

def _neck_side(lms, direction):
    if not _visible(lms, [pe.LEFT_EAR, pe.RIGHT_EAR, pe.LEFT_SHOULDER, pe.RIGHT_SHOULDER]):
        return False, ["얼굴과 어깨가 화면에 나오게 해 주세요"]
    roll = _head_roll_deg(lms)
    need = 13.0
    value = roll if direction == "left" else -roll
    if value >= need:
        return True, []
    if value > 4:
        return False, ["조금 더 깊게 머리를 어깨 쪽으로 기울여 주세요"]
    return False, ["머리를 어깨 쪽으로 천천히 기울여 주세요"]


def _chin_tuck(lms):
    if not _visible(lms, [pe.LEFT_EAR, pe.RIGHT_EAR, pe.LEFT_SHOULDER, pe.RIGHT_SHOULDER]):
        return False, ["얼굴과 어깨가 화면에 나오게 해 주세요"]
    sw = _shoulder_width(lms)
    # 정면 뷰에서 거북목(머리 전방 이동)은 x가 아니라 카메라 z축으로 드러난다.
    # z는 카메라에 가까울수록 작아지므로, 귀가 어깨보다 앞으로 나오면
    # forward = (어깨z - 귀z)/어깨너비 가 커진다. 턱을 당기면 작아진다.
    ez = (lms[pe.LEFT_EAR]["z"] + lms[pe.RIGHT_EAR]["z"]) / 2
    sz = (lms[pe.LEFT_SHOULDER]["z"] + lms[pe.RIGHT_SHOULDER]["z"]) / 2
    forward = (sz - ez) / sw
    if forward <= 0.35:
        return True, []
    return False, ["턱을 뒤로 당겨 귀가 어깨 위에 오도록 해 주세요"]


def _shoulder_shrug(lms):
    if not _visible(lms, [pe.LEFT_EAR, pe.RIGHT_EAR, pe.LEFT_SHOULDER, pe.RIGHT_SHOULDER]):
        return False, ["얼굴과 어깨가 화면에 나오게 해 주세요"]
    sw = _shoulder_width(lms)
    ls, rs = _pt(lms, pe.LEFT_SHOULDER), _pt(lms, pe.RIGHT_SHOULDER)
    le, re_ = _pt(lms, pe.LEFT_EAR), _pt(lms, pe.RIGHT_EAR)
    gap = ((ls[1] - le[1]) + (rs[1] - re_[1])) / 2 / sw  # 귀-어깨 세로 간격
    if gap <= 0.33:
        return True, []
    return False, ["어깨를 귀 쪽으로 끌어올려 주세요"]


def _chest_opener(lms):
    ids = [pe.LEFT_SHOULDER, pe.RIGHT_SHOULDER, pe.LEFT_WRIST, pe.RIGHT_WRIST]
    if not _visible(lms, ids, th=0.4):
        return False, ["양팔이 모두 화면에 나오게 해 주세요"]
    sw = _shoulder_width(lms)
    ls, rs = _pt(lms, pe.LEFT_SHOULDER), _pt(lms, pe.RIGHT_SHOULDER)
    lw, rw = _pt(lms, pe.LEFT_WRIST), _pt(lms, pe.RIGHT_WRIST)
    spread = abs(lw[0] - rw[0]) / sw
    at_level = abs(lw[1] - ls[1]) / sw < 0.6 and abs(rw[1] - rs[1]) / sw < 0.6
    if spread >= 1.7 and at_level:
        return True, []
    fb = []
    if spread < 1.7:
        fb.append("양팔을 옆으로 활짝 펴 주세요")
    if not at_level:
        fb.append("팔을 어깨 높이까지 올려 주세요")
    return False, fb


def _arms_up(lms):
    ids = [pe.NOSE, pe.LEFT_WRIST, pe.RIGHT_WRIST]
    if not _visible(lms, ids, th=0.4):
        return False, ["양손이 화면에 나오게 해 주세요"]
    nose = _pt(lms, pe.NOSE)
    lw, rw = _pt(lms, pe.LEFT_WRIST), _pt(lms, pe.RIGHT_WRIST)
    if lw[1] < nose[1] and rw[1] < nose[1]:
        return True, []
    return False, ["양손을 머리 위로 쭉 뻗어 주세요"]


# ---------------------------------------------------------------- 카탈로그
EXERCISES = [
    {
        "id": "neck_side_left",
        "name": "목 옆 늘리기 (왼쪽)",
        "targets": ["neck_tilt", "shoulder_tilt"],
        "hold_sec": 10,
        "description": "머리를 한쪽 어깨 쪽으로 천천히 기울여 반대쪽 목 옆 근육을 늘립니다.",
        "checker": lambda lms: _neck_side(lms, "left"),
    },
    {
        "id": "neck_side_right",
        "name": "목 옆 늘리기 (오른쪽)",
        "targets": ["neck_tilt", "shoulder_tilt"],
        "hold_sec": 10,
        "description": "머리를 반대쪽 어깨 쪽으로 천천히 기울입니다.",
        "checker": lambda lms: _neck_side(lms, "right"),
    },
    {
        "id": "chin_tuck",
        "name": "턱 당기기",
        "targets": ["neck_tilt", "head_down", "lean_in"],
        "hold_sec": 8,
        "description": "턱을 뒤로 당겨 귀가 어깨 위에 오게 합니다. 거북목 교정의 기본 동작입니다.",
        "checker": _chin_tuck,
    },
    {
        "id": "shoulder_shrug",
        "name": "어깨 으쓱하기",
        "targets": ["shoulder_tilt"],
        "hold_sec": 6,
        "description": "어깨를 귀 쪽으로 끌어올렸다가 힘을 빼며 툭 떨어뜨립니다.",
        "checker": _shoulder_shrug,
    },
    {
        "id": "chest_opener",
        "name": "가슴 열기",
        "targets": ["lean_in", "head_down"],
        "hold_sec": 10,
        "description": "양팔을 어깨 높이로 활짝 펴서 말린 어깨와 가슴을 엽니다.",
        "checker": _chest_opener,
    },
    {
        "id": "arms_up",
        "name": "팔 위로 뻗기",
        "targets": ["head_down", "lean_in", "shift_x"],
        "hold_sec": 8,
        "description": "깍지를 끼고 양손을 머리 위로 쭉 뻗어 등과 어깨를 폅니다.",
        "checker": _arms_up,
    },
]

_BY_ID = {e["id"]: e for e in EXERCISES}


def get_exercise(exercise_id: str):
    return _BY_ID.get(exercise_id)


def public_exercise(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "checker"}


def recommend(issue_codes: list) -> list:
    """모니터링에서 감지된 문제 코드들로 스트레칭 추천 (관련도 순)."""
    if not issue_codes:
        return [public_exercise(e) for e in EXERCISES[:3]]
    scored = []
    for e in EXERCISES:
        overlap = len(set(e["targets"]) & set(issue_codes))
        if overlap:
            scored.append((overlap, e))
    scored.sort(key=lambda t: -t[0])
    result = [public_exercise(e) for _, e in scored]
    return result or [public_exercise(e) for e in EXERCISES[:3]]


def check_frame(exercise_id: str, landmarks):
    """한 프레임에 대해 해당 스트레칭 동작 중인지 판정."""
    e = _BY_ID[exercise_id]
    in_pose, feedback = e["checker"](landmarks)
    return {"in_pose": in_pose, "feedback": feedback}

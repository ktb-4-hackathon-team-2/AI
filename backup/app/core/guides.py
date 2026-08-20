"""화면 오버레이용 자세 가이드(하드코딩) + 가이드 정합(alignment) 판정.

가이드 좌표는 카메라 프레임 기준 정규화 좌표(0~1, 좌상단 원점)라서
프론트엔드가 캔버스 크기에 곱해 그대로 그리면 된다.
셀피 카메라를 미러링해서 보여주는 경우 x를 1-x로 뒤집어 그릴 것.

앵커 키의 left_/right_는 해부학이 아니라 "이미지 기준 좌/우" 위치를 뜻한다.
MediaPipe의 LEFT_*는 해부학적 왼쪽이라 raw 프레임에서는 이미지 오른쪽에
잡히므로, 정합 판정은 랜드마크를 이미지상 위치로 정렬해 비교한다
(프레임이 미러링돼 들어와도 동일하게 동작).
"""

import math

from app.core import pose_engine as pe

# 뷰별 목표 앵커(어깨/귀/코 위치). 유저가 이 위치에 맞춰 앉으면
# 모든 유저가 균일한 프레이밍으로 baseline을 잡게 된다.
_FRONT_ANCHORS = {
    "nose": (0.50, 0.30),
    "left_ear": (0.435, 0.30),
    "right_ear": (0.565, 0.30),
    "left_shoulder": (0.34, 0.52),
    "right_shoulder": (0.66, 0.52),
}
# 좌대각: 카메라가 유저의 왼쪽 앞에 위치 → 몸이 오른쪽으로 살짝 돌아가 보임
_LEFT_DIAG_ANCHORS = {
    "nose": (0.46, 0.30),
    "left_ear": (0.415, 0.30),
    "right_ear": (0.535, 0.305),
    "left_shoulder": (0.33, 0.52),
    "right_shoulder": (0.62, 0.53),
}
# 우대각: 좌대각의 좌우 대칭
_RIGHT_DIAG_ANCHORS = {
    "nose": (0.54, 0.30),
    "left_ear": (0.465, 0.305),
    "right_ear": (0.585, 0.30),
    "left_shoulder": (0.38, 0.53),
    "right_shoulder": (0.67, 0.52),
}
# 스트레칭용: 정면 기준, 팔 동작이 프레임에 들어오도록 상반신을 조금 작게/아래로
_STRETCH_ANCHORS = {
    "nose": (0.50, 0.26),
    "left_ear": (0.445, 0.26),
    "right_ear": (0.555, 0.26),
    "left_shoulder": (0.365, 0.44),
    "right_shoulder": (0.635, 0.44),
}

_VIEW_ANCHORS = {
    "front": _FRONT_ANCHORS,
    "left_diagonal": _LEFT_DIAG_ANCHORS,
    "right_diagonal": _RIGHT_DIAG_ANCHORS,
    "stretch": _STRETCH_ANCHORS,
}

_VIEW_LABELS = {
    "front": "정면",
    "left_diagonal": "좌대각",
    "right_diagonal": "우대각",
    "stretch": "스트레칭 (정면·상반신)",
}

VIEWS = ["front", "left_diagonal", "right_diagonal"]      # baseline 캘리브레이션 가능 뷰
ALL_VIEWS = list(_VIEW_ANCHORS)                            # stretch 포함 전체 뷰

# 앵커 허용 오차(정규화 거리). 이 안에 들어오면 "맞춰 앉음"으로 판정.
ANCHOR_TOLERANCE = 0.09


def _silhouette(anchors, expand=1.0):
    """앵커 기반 상반신 실루엣 폴리곤(머리 원 + 어깨/몸통 사다리꼴)."""
    ls = anchors["left_shoulder"]
    rs = anchors["right_shoulder"]
    nose = anchors["nose"]
    sw = (rs[0] - ls[0]) * expand
    head_r = sw * 0.30
    cx = nose[0]
    head_cy = nose[1]
    body_bottom = min(ls[1] + sw * 0.85, 0.99)
    # 머리를 위쪽 반원(오른쪽→왼쪽)으로 근사 + 몸통
    pts = []
    for i in range(12):
        a = math.pi * (1 - i / 11.0)
        pts.append((cx + head_r * math.cos(a + math.pi), head_cy + head_r * math.sin(a + math.pi)))
    # 머리 호가 이미지 왼쪽 끝점에서 끝나므로 몸통도 왼쪽부터 이어야
    # 폴리곤이 목에서 교차(나비넥타이)하지 않는다
    body = [
        (ls[0] - sw * 0.10, ls[1] - sw * 0.10),
        (ls[0] - sw * 0.14, body_bottom),
        (rs[0] + sw * 0.14, body_bottom),
        (rs[0] + sw * 0.10, rs[1] - sw * 0.10),
    ]
    poly = pts + body
    return [(round(x, 4), round(y, 4)) for x, y in poly]


def get_guide(view: str) -> dict:
    """뷰별 오버레이 가이드 데이터."""
    if view not in _VIEW_ANCHORS:
        raise KeyError(view)
    anchors = _VIEW_ANCHORS[view]
    return {
        "view": view,
        "label": _VIEW_LABELS[view],
        "anchors": {k: {"x": v[0], "y": v[1]} for k, v in anchors.items()},
        "silhouette": [{"x": x, "y": y} for x, y in _silhouette(anchors)],
        "tolerance": ANCHOR_TOLERANCE,
        "instructions": _instructions(view),
    }


def _instructions(view):
    common = [
        "화면의 실루엣에 몸을 맞춰 주세요",
        "허리를 펴고 어깨에 힘을 뺀 바른 자세를 잡아 주세요",
    ]
    per_view = {
        "front": ["카메라를 정면으로 바라봐 주세요"],
        "left_diagonal": ["카메라가 왼쪽 앞 45도에 오도록 배치해 주세요"],
        "right_diagonal": ["카메라가 오른쪽 앞 45도에 오도록 배치해 주세요"],
        "stretch": ["상반신 전체(머리~팔꿈치)가 화면에 나오도록 조금 뒤로 앉아 주세요"],
    }
    return per_view.get(view, []) + common


def check_alignment(landmarks, view: str) -> dict:
    """실시간 프레임이 가이드에 맞는지 판정하고 이동 안내 메시지를 준다."""
    anchors = _VIEW_ANCHORS[view]

    # 앵커 키는 "이미지 기준 좌/우"인데 MediaPipe 인덱스는 해부학 기준이라
    # (raw 프레임에서 해부학적 왼쪽 = 이미지 오른쪽) x좌표로 정렬해 매칭한다.
    # 프레임이 미러링돼 들어와도 똑같이 동작한다.
    ana_l_sh, ana_r_sh = landmarks[pe.LEFT_SHOULDER], landmarks[pe.RIGHT_SHOULDER]
    ana_l_ear, ana_r_ear = landmarks[pe.LEFT_EAR], landmarks[pe.RIGHT_EAR]
    img_l_sh, img_r_sh = sorted([ana_l_sh, ana_r_sh], key=lambda lm: lm["x"])
    img_l_ear, img_r_ear = sorted([ana_l_ear, ana_r_ear], key=lambda lm: lm["x"])
    lm_map = {
        "nose": landmarks[pe.NOSE],
        "left_ear": img_l_ear,
        "right_ear": img_r_ear,
        "left_shoulder": img_l_sh,
        "right_shoulder": img_r_sh,
    }
    messages = []

    low_vis = [k for k, lm in lm_map.items() if lm["visibility"] < 0.5]
    if low_vis:
        messages.append("상반신이 모두 화면에 나오도록 위치를 조정해 주세요")

    # 목표 대비 현재 어깨 중심/너비로 이동·거리 안내
    ls, rs = lm_map["left_shoulder"], lm_map["right_shoulder"]
    cur_cx = (ls["x"] + rs["x"]) / 2
    cur_cy = (ls["y"] + rs["y"]) / 2
    cur_w = abs(rs["x"] - ls["x"])
    tgt_ls, tgt_rs = anchors["left_shoulder"], anchors["right_shoulder"]
    tgt_cx = (tgt_ls[0] + tgt_rs[0]) / 2
    tgt_cy = (tgt_ls[1] + tgt_rs[1]) / 2
    tgt_w = abs(tgt_rs[0] - tgt_ls[0])

    dx = cur_cx - tgt_cx
    dy = cur_cy - tgt_cy
    dw = cur_w / tgt_w - 1.0

    # 안내 문구는 유저의 몸 기준 방향. raw 프레임에서 dx>0(이미지 오른쪽으로
    # 치우침)이면 유저는 자기 왼쪽으로 치우친 것 → 오른쪽으로 이동해야 한다.
    # 미러링된 셀피 화면에서도 이 문구가 화면상의 방향과 일치한다.
    if dx > ANCHOR_TOLERANCE:
        messages.append("오른쪽으로 조금 이동해 주세요")
    elif dx < -ANCHOR_TOLERANCE:
        messages.append("왼쪽으로 조금 이동해 주세요")
    if dy > ANCHOR_TOLERANCE:
        messages.append("조금 위로 (의자를 높이거나 카메라를 내려) 맞춰 주세요")
    elif dy < -ANCHOR_TOLERANCE:
        messages.append("조금 아래로 맞춰 주세요")
    if dw > 0.25:
        messages.append("카메라에서 조금 멀어져 주세요")
    elif dw < -0.25:
        messages.append("카메라에 조금 가까이 와 주세요")

    # 앵커별 거리 오차
    offsets = {}
    aligned_all = True
    for key, tgt in anchors.items():
        lm = lm_map[key]
        d = math.dist((lm["x"], lm["y"]), tgt)
        offsets[key] = round(d, 4)
        if d > ANCHOR_TOLERANCE:
            aligned_all = False

    aligned = aligned_all and not low_vis
    if aligned:
        messages = ["좋아요! 이 자세를 유지해 주세요"]
    return {
        "aligned": aligned,
        "offsets": offsets,
        # 프론트가 화살표 등을 직접 그릴 수 있게 원시 편차도 제공 (raw 프레임 기준)
        "dx": round(dx, 4),
        "dy": round(dy, 4),
        "scale": round(dw, 4),
        "messages": messages,
    }

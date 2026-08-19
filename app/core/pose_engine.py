"""MediaPipe Pose Landmarker 래퍼.

이미지(base64 → BGR ndarray)를 받아 33개 포즈 랜드마크를 돌려준다.
MediaPipe Tasks 그래프는 스레드 세이프하지 않으므로 락으로 직렬화한다.
"""

import base64
import binascii
import threading

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

from app.config import MODEL_PATH

# 랜드마크 인덱스 (MediaPipe Pose 33 landmarks)
NOSE = 0
LEFT_EYE = 2
RIGHT_EYE = 5
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24

UPPER_BODY_IDS = [
    NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST,
]

_lock = threading.Lock()
_landmarker = None


def _get_landmarker():
    global _landmarker
    if _landmarker is None:
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
        )
        _landmarker = vision.PoseLandmarker.create_from_options(options)
    return _landmarker


class ImageDecodeError(ValueError):
    pass


def decode_image(image_b64: str) -> np.ndarray:
    """base64(JPEG/PNG, data URL 허용) → BGR ndarray."""
    if "," in image_b64 and image_b64.strip().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_b64, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ImageDecodeError(f"base64 디코딩 실패: {e}")
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ImageDecodeError("이미지 디코딩 실패: JPEG/PNG base64인지 확인하세요")
    return img


def _to_dicts(lms):
    return [
        {
            "x": float(lm.x),
            "y": float(lm.y),
            "z": float(lm.z),
            "visibility": float(lm.visibility) if lm.visibility is not None else 0.0,
        }
        for lm in lms
    ]


def detect_landmarks(image_bgr: np.ndarray):
    """BGR 이미지에서 포즈 랜드마크 검출.

    Returns:
        list[dict] | None — 33개 랜드마크 [{x, y, z, visibility}] (정규화 좌표),
        사람이 감지되지 않으면 None.
    """
    full = detect_landmarks_full(image_bgr)
    return full["image"] if full else None


def detect_landmarks_full(image_bgr: np.ndarray):
    """이미지 좌표 랜드마크 + 월드(3D, 미터, 힙 원점) 랜드마크를 함께 반환.

    Returns:
        {"image": [...33...], "world": [...33...]} | None
        world는 힙 중심 원점의 카메라 방향 3D 좌표 — 뷰 불변 자세 특징
        계산(교차 뷰 캘리브레이션 검증)에 쓴다.
    """
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with _lock:
        result = _get_landmarker().detect(mp_image)
    if not result.pose_landmarks:
        return None
    return {
        "image": _to_dicts(result.pose_landmarks[0]),
        "world": _to_dicts(result.pose_world_landmarks[0]),
    }


def landmarks_from_image_b64(image_b64: str):
    return detect_landmarks(decode_image(image_b64))

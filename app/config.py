import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = os.environ.get(
    "POSE_MODEL_PATH", str(BASE_DIR / "models" / "pose_landmarker_lite.task")
)
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASELINE_FILE = DATA_DIR / "baselines.json"

# 모니터링 판정에 쓰는 기본 임계값 (strictness=medium 기준)
THRESHOLDS = {
    "neck_tilt_deg": 12.0,      # 목 기울기 변화 허용치 (도)
    "shoulder_tilt_deg": 7.0,   # 어깨 기울기 변화 허용치 (도)
    "head_down_drop": 0.18,     # 머리 숙임: baseline 대비 비율 감소 허용치
    "lean_ratio": 0.13,         # 어깨 너비 변화율(가까워짐/멀어짐) 허용치
    "shift_x": 0.12,            # 좌우 이동 허용치 (정규화 좌표)
}

# 환경설정의 "얼마나 엄격하게 경고할지" — 임계값에 곱해지는 배율
STRICTNESS_SCALE = {"low": 1.4, "medium": 1.0, "high": 0.7}

# 나쁜 자세가 지속됐을 때 경고 단계가 올라가는 시간(초)
DEFAULT_WARN_AFTER_SEC = 5.0    # level 1: 팝업 경고
DEFAULT_ALARM_AFTER_SEC = 15.0  # level 2: 강한 경고(개지랄 모드)

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# 종료 버튼 연타로 LLM 리포트 분석이 과다 호출되는 것을 막는 쿨다운(초).
# 쿨다운 안에는 기존 코멘트를 재사용하고 통계(stats)만 새로 계산한다.
REPORT_LLM_COOLDOWN_SEC = float(os.environ.get("REPORT_LLM_COOLDOWN_SEC", "300"))

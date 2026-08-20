"""2장 촬영 교차 뷰 캘리브레이션 실험.

방식: ① 정면에서 실루엣으로 강제한 바른 자세 사진 A → ② 실사용 카메라
위치에서 같은 바른 자세 사진 B. 두 스켈레톤의 뷰 불변(3D) 특징을 비교해
B가 정말 바른 자세인지 검증하고, B를 모니터링 baseline으로 쓴다.

실험 구성
  1) 2D 지표의 뷰 의존성: 현재 방식의 2D baseline이 다른 카메라 각도로
     이월될 수 없음을 수치로 확인 (→ 왜 교차 검증에 3D가 필요한가)
  2) 몬테카를로: 카메라 각도(요 0~45도, 피치 차이) + 추정 노이즈 하에서
     "같은 자세" 오탐/미탐률과 허용 오차 산정
  3) 실사진 파이프라인 점검: MediaPipe 월드 랜드마크 → 특징 추출이
     크롭/스케일 변화에 얼마나 안정적인지

팀 사용법 (자기 웹캠 사진으로 직접 확인):
    python experiments/two_shot_test.py --a front.jpg --b desk_position.jpg
"""

import argparse
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import posture, view_invariant
from app.core import pose_engine as pe

# ── 합성 3D 골격 (몸 기준계: x 왼쪽+, y 위+, z 앞+, 단위 m) ──────────────
GOOD = {
    23: (0.10, 0.0, 0.0), 24: (-0.10, 0.0, 0.0),          # hips
    11: (0.18, 0.45, -0.02), 12: (-0.18, 0.45, -0.02),    # shoulders
    7: (0.075, 0.62, 0.00), 8: (-0.075, 0.62, 0.00),      # ears
    0: (0.0, 0.60, 0.10),                                  # nose
}
MILD_SLOUCH = {  # 가벼운 거북목: 머리만 6cm 전방
    **GOOD,
    7: (0.075, 0.60, 0.06), 8: (-0.075, 0.60, 0.06),
    0: (0.0, 0.57, 0.17),
}
STRONG_SLOUCH = {  # 심한 거북목+말린 어깨
    23: (0.10, 0.0, 0.0), 24: (-0.10, 0.0, 0.0),
    11: (0.18, 0.42, 0.04), 12: (-0.18, 0.42, 0.04),
    7: (0.075, 0.57, 0.13), 8: (-0.075, 0.57, 0.13),
    0: (0.0, 0.54, 0.23),
}
LEAN_SIDE = {  # 옆으로 기운 자세 (어깨선 기움)
    **GOOD,
    11: (0.18, 0.48, -0.02), 12: (-0.18, 0.40, -0.02),
    7: (0.09, 0.64, 0.0), 8: (-0.06, 0.60, 0.0),
}

IDX = [0, 7, 8, 11, 12, 23, 24]


def rot_y(p, deg):
    a = math.radians(deg)
    return (p[0] * math.cos(a) + p[2] * math.sin(a), p[1],
            -p[0] * math.sin(a) + p[2] * math.cos(a))


def rot_x(p, deg):
    a = math.radians(deg)
    return (p[0], p[1] * math.cos(a) - p[2] * math.sin(a),
            p[1] * math.sin(a) + p[2] * math.cos(a))


def observe(skel, yaw, pitch, sigma_xy=0.0, sigma_z=0.0, rng=None):
    """카메라(요/피치 회전) 기준 월드 랜드마크 관측 시뮬레이션.

    노이즈는 카메라 기준계에서: 이미지 평면 방향 sigma_xy, 깊이 방향
    sigma_z (MediaPipe 월드 랜드마크는 깊이 오차가 수 배 큼).
    """
    out = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0} for _ in range(33)]
    for i in IDX:
        p = rot_x(rot_y(skel[i], yaw), pitch)
        if rng:
            p = (p[0] + rng.gauss(0, sigma_xy),
                 p[1] + rng.gauss(0, sigma_xy),
                 p[2] + rng.gauss(0, sigma_z))
        # 카메라 기준계 → mediapipe 월드와 같은 y-down 좌표로 (특징엔 영향 없음)
        out[i] = {"x": p[0], "y": -p[1], "z": -p[2], "visibility": 1.0}
    return out


def project_2d(skel, yaw, pitch, scale=0.55, cx=0.5, cy=0.42):
    """약원근 투영으로 정규화 이미지 좌표 생성 (현재 2D 지표 계산용)."""
    out = [{"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0} for _ in range(33)]
    for i in IDX:
        p = rot_x(rot_y(skel[i], yaw), pitch)
        out[i] = {"x": cx - p[0] * scale, "y": cy - p[1] * scale,
                  "z": 0.0, "visibility": 1.0}
    return out


def exp1_2d_view_dependence():
    print("=" * 72)
    print("[실험 1] 현재 2D 지표의 뷰 의존성 — 정면 baseline을 다른 각도에 적용하면?")
    print("=" * 72)
    base = posture.compute_metrics(project_2d(GOOD, 0, -5))
    print(f"{'카메라 요(도)':>10} | {'같은 자세 score':>14} | 판정")
    for yaw in [0, 10, 20, 30, 45]:
        m = posture.compute_metrics(project_2d(GOOD, yaw, -5))
        ev = posture.evaluate_against_baseline(m, base)
        verdict = "OK (바른 자세로 인식)" if ev["posture_ok"] else f"오경보! issues={[i['code'] for i in ev['issues']]}"
        print(f"{yaw:>10} | {ev['score']:>14.2f} | {verdict}")
    print("→ score>=1이면 임계치 초과. 2D baseline은 촬영한 그 카메라 각도에서만 유효,")
    print("  다른 각도로 이월 불가 → 교차 뷰 검증에는 3D(월드 랜드마크) 특징이 필요.\n")


def _avg_features(skel, yaw, pitch, k, sigma_xy, sigma_z, rng):
    """K프레임 캡처 후 특징 평균 (실전에서는 촬영 시 1~2초 프레임을 평균)."""
    acc = None
    for _ in range(k):
        f = view_invariant.compute_features(observe(skel, yaw, pitch, sigma_xy, sigma_z, rng))
        if acc is None:
            acc = dict(f)
        else:
            for key in acc:
                acc[key] += f[key]
    return {key: v / k for key, v in acc.items()}


def exp2_monte_carlo(n=2000, sigma_xy=0.010, sigma_z=0.030):
    print("=" * 72)
    print(f"[실험 2] 몬테카를로 (n={n}/조건, 프레임당 노이즈: 평면 {sigma_xy*100:.0f}cm / 깊이 {sigma_z*100:.0f}cm)")
    print("A = 정면(요0, 피치-5) 바른 자세  vs  B = 각 요 각도(피치-12)의 자세")
    print("=" * 72)
    feats = list(view_invariant.DEFAULT_TOLERANCES)
    final_tol = None

    for k_frames in [1, 20]:
        rng = random.Random(42)
        print(f"\n──── 촬영당 {k_frames}프레임 평균 ────")
        # 1단계: 같은 자세 diff 분포 → 허용 오차(97.5퍼센타일) 산정
        same_diffs = {k: [] for k in feats}
        for yaw in [0, 15, 30, 45]:
            for _ in range(n // 4):
                fa = _avg_features(GOOD, 0, -5, k_frames, sigma_xy, sigma_z, rng)
                fb = _avg_features(GOOD, yaw, -12, k_frames, sigma_xy, sigma_z, rng)
                for k in feats:
                    same_diffs[k].append(abs(fa[k] - fb[k]))
        tol = {}
        print("같은 자세 특징 차이 (뷰 0~45도 교차):")
        for k in feats:
            d = sorted(same_diffs[k])
            p50, p975 = d[len(d) // 2], d[int(len(d) * 0.975)]
            tol[k] = round(p975 * 1.1, 4)  # 97.5퍼센타일 + 10% 여유
            print(f"  {k:20s} 중앙값 {p50:7.3f}  97.5pct {p975:7.3f}  → 허용오차 {tol[k]}")

        # 2단계: 이 허용 오차로 오탐/미탐률
        def run(skel_b, label):
            results = {}
            for yaw in [0, 15, 30, 45]:
                rejected = 0
                for _ in range(n // 4):
                    fa = _avg_features(GOOD, 0, -5, k_frames, sigma_xy, sigma_z, rng)
                    fb = _avg_features(skel_b, yaw, -12, k_frames, sigma_xy, sigma_z, rng)
                    if not view_invariant.compare_postures(fa, fb, tol)["same_posture"]:
                        rejected += 1
                results[yaw] = rejected / (n // 4)
            print(f"  {label:32s} " + "  ".join(f"요{y}°:{r*100:5.1f}%" for y, r in results.items()))
            return results

        print("'다른 자세' 판정률 (같은 자세는 낮아야, 나쁜 자세는 높아야 함):")
        run(GOOD, "같은 바른 자세 (false reject ↓)")
        run(MILD_SLOUCH, "가벼운 거북목 6cm (detect ↑)")
        run(STRONG_SLOUCH, "심한 거북목+어깨 (detect ↑)")
        run(LEAN_SIDE, "옆으로 기운 자세 (detect ↑)")
        if k_frames == 20:
            final_tol = tol

    print(f"\n→ 결론: 단일 프레임으로는 판별력 부족, 촬영당 ~20프레임(1~2초) 평균 필수.")
    print(f"  20프레임 기준 허용 오차: {final_tol}")
    print("  (app/core/view_invariant.py DEFAULT_TOLERANCES에 반영)")
    print("  주의: 프레임 간 독립 노이즈만 모델링함 — MediaPipe의 뷰별 systematic")
    print("  bias는 합성으로 못 재므로 실제 웹캠 각도별 검증(CLI) 필요.\n")
    return final_tol


def exp3_real_photo(path):
    print("=" * 72)
    print("[실험 3] 실사진 파이프라인 점검 (MediaPipe 월드 랜드마크 안정성)")
    print("=" * 72)
    import cv2
    img = cv2.imread(path)
    if img is None:
        print(f"  사진 없음: {path} — 건너뜀\n")
        return
    full = pe.detect_landmarks_full(img)
    if full is None:
        print("  사람 미검출 — 건너뜀\n")
        return
    base = view_invariant.compute_features(full["world"])
    print(f"  원본 특징: {base}")
    h, w = img.shape[:2]
    variants = {
        "10% 크롭": img[int(h*0.1):, int(w*0.1):],
        "20% 크롭(반대)": img[:int(h*0.85), :int(w*0.85)],
        "0.7x 축소": cv2.resize(img, (int(w*0.7), int(h*0.7))),
        "1.3x 확대": cv2.resize(img, (int(w*1.3), int(h*1.3))),
    }
    worst = {k: 0.0 for k in base}
    for name, v in variants.items():
        f2 = pe.detect_landmarks_full(v)
        if f2 is None:
            continue
        feats = view_invariant.compute_features(f2["world"])
        for k in base:
            worst[k] = max(worst[k], abs(feats[k] - base[k]))
    print(f"  크롭/스케일 변형 4종에 대한 최대 특징 변화: {worst}")
    print("  → 허용 오차 대비 충분히 작으면 파이프라인 노이즈는 문제 없음.")
    print("  (한 장으로는 뷰 교차 오차를 못 재므로, 실제 각도별 검증은 아래 CLI로)\n")


def cli_compare(path_a, path_b):
    """팀원용: 정면 사진 A와 실사용 위치 사진 B를 직접 비교."""
    import cv2
    fa = pe.detect_landmarks_full(cv2.imread(path_a))
    fb = pe.detect_landmarks_full(cv2.imread(path_b))
    if fa is None or fb is None:
        print("사람 미검출:", path_a if fa is None else path_b)
        return
    A = view_invariant.compute_features(fa["world"])
    B = view_invariant.compute_features(fb["world"])
    result = view_invariant.compare_postures(A, B)
    print(f"A({path_a}): {A}")
    print(f"B({path_b}): {B}")
    print(f"차이: {result['diffs']}")
    print(f"같은 자세 판정: {result['same_posture']}"
          + (f" — 초과 항목: {result['exceeded']}" if result["exceeded"] else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", help="정면 검증샷 (실루엣 강제)")
    ap.add_argument("--b", help="실사용 위치샷")
    ap.add_argument("--photo", default=os.environ.get("TEST_PHOTO", ""),
                    help="실험 3용 사진 경로")
    args = ap.parse_args()

    if args.a and args.b:
        cli_compare(args.a, args.b)
    else:
        exp1_2d_view_dependence()
        exp2_monte_carlo()
        if args.photo:
            exp3_real_photo(args.photo)

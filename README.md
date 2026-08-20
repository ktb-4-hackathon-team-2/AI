# 반듯 AI

웹캠 자세교정 서비스 "반듯"의 AI 저장소.

실시간 자세 감지(MediaPipe)가 **프론트엔드 온디바이스로 이관**되면서,
이 저장소가 실제로 배포하는 것은 **일일 리포트 LLM 분석 서버 하나**다.

## 구조

| 경로 | 내용 |
|---|---|
| [`report-service/`](report-service/) | **EC2에 배포하는 것.** 일일 리포트 Claude 분석 FastAPI 서버 (자기완결 — 이 폴더만 가져가면 됨). 실행법·API 계약·Dockerfile은 폴더 안 README 참고 |
| [`backup/`](backup/) | 원본 풀서버 백업 — 자세 감지(가이드 정합·캘리브레이션·모니터링·스트레칭) + 리포트 분석이 함께 있던 코드. API 문서는 [`backup/README.md`](backup/README.md) (프론트 포팅의 원본 스펙) |
| `.github/workflows/` | CI(`test` 브랜치) + 수동 배포(ECR→EC2) |

## ⚠️ CI/CD 경로 수정 필요

워크플로우가 아직 저장소 루트(옛 풀서버) 기준이라 다음 수정이 필요하다:

- `deploy.yml`: 도커 빌드 `context: .` → `context: ./report-service`
- `ci.yml`: `pip install -r report-service/requirements.txt`,
  `python -m compileall report-service/app`, `cd report-service && python test_report.py`
  (OpenCV/MediaPipe 시스템 패키지 설치 스텝은 삭제 가능)

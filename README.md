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

## CI/CD

둘 다 `report-service/` 기준으로 동작한다.

- **CI** (`ci.yml`): `main`/`test` 브랜치 push·PR 시 자동 실행 — 린트 + 문법 검사 + `test_report.py`
- **배포** (`deploy.yml`): 자동 아님. GitHub **Actions 탭 → "Deploy AI Server to EC2" → Run workflow** 버튼으로 수동 실행
  → report-service 이미지를 ECR에 빌드·푸시 → EC2에서 컨테이너 교체 → 헬스체크 실패 시 이전 버전 자동 롤백
- 컨테이너 환경변수는 레포 시크릿에서 주입: `ANTHROPIC_API_KEY`(필수 — 없으면 규칙 기반 폴백), `ANTHROPIC_MODEL`(선택, 기본 `claude-sonnet-5`)

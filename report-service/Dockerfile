# 반듯 AI 리포트 서버 — 참고용 Dockerfile (배포 담당자가 자유롭게 수정/대체 가능)
# 순수 Python 서비스라 시스템 패키지 불필요 (mediapipe/opencv 없음)
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# ANTHROPIC_API_KEY는 런타임에 주입 (docker run -e / ECS task definition / EC2 env)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

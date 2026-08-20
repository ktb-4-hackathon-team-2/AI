FROM python:3.11-slim

LABEL maintainer="bandeut-ai"
LABEL description="반듯 AI 서버 - MediaPipe Pose + FastAPI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib/aarch64-linux-gnu:/usr/lib:$LD_LIBRARY_PATH"

WORKDIR /app

# OpenCV 및 MediaPipe 구동에 필요한 모든 그래픽/시스템 라이브러리 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libgles2 \
    libegl1 \
    curl \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

# libGLESv2 심볼릭 링크 안전망 생성
RUN if [ -f /usr/lib/x86_64-linux-gnu/libGLESv2.so.2 ]; then ln -sf /usr/lib/x86_64-linux-gnu/libGLESv2.so.2 /usr/lib/libGLESv2.so.2; fi && \
    if [ -f /usr/lib/aarch64-linux-gnu/libGLESv2.so.2 ]; then ln -sf /usr/lib/aarch64-linux-gnu/libGLESv2.so.2 /usr/lib/libGLESv2.so.2; fi

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY models ./models

RUN mkdir -p data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

"""반듯 AI 리포트 서버 — 일일 자세 리포트 분석(Claude) 단독 FastAPI 엔트리포인트.

자세 감지(MediaPipe)는 프론트엔드로 이관되어 이 서버에는 없다.
전체 기능이 있던 원본은 저장소 루트의 app/ 참고 (백업).

실행:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import report

app = FastAPI(
    title="반듯 AI 리포트",
    version="0.1.0",
    description=(
        "backend가 집계한 일일 자세 데이터를 받아 Claude로 요약·하이라이트·조언을 "
        "생성하는 리포트 분석 서버. API 키가 없거나 호출이 실패하면 규칙 기반으로 폴백."
    ),
)

# 해커톤용: 어디서든 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report.router, prefix="/api", tags=["report"])


@app.get("/health")
def health():
    return {"status": "ok"}

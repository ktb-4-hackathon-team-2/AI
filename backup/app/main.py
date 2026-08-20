"""반듯 AI 서버 — 자세 감지 + 자세 진단 리포트 분석 FastAPI 엔트리포인트.

실행:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.pose_engine import ImageDecodeError
from app.routers import guide, monitor, report, stretch

app = FastAPI(
    title="반듯 AI",
    version="0.1.0",
    description=(
        "웹캠 프레임(base64) 기반 자세 감지(MediaPipe Pose)와 "
        "일일 자세 리포트 분석(Claude)을 제공하는 AI 서버. "
        "모든 좌표는 프레임 기준 정규화 좌표(0~1, 좌상단 원점)."
    ),
)

# 해커톤용: 프론트 dev 서버 어디서든 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(guide.router, prefix="/api", tags=["guide & calibration"])
app.include_router(monitor.router, prefix="/api", tags=["monitoring"])
app.include_router(stretch.router, prefix="/api", tags=["stretch"])
app.include_router(report.router, prefix="/api", tags=["report"])


@app.exception_handler(ImageDecodeError)
async def image_decode_error_handler(request: Request, exc: ImageDecodeError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok"}

import json
from app.core import report
from app.routers.report import analyze_daily

sample_data = {
    "date": "2026-08-19",
    "user_id": "1",
    "stretch_suggested": 0,
    "stretch_done": 0,
    "hourly": [
        {
            "hour": 21,
            "good_ratio": 0.24,
            "monitored_min": 31.6,
            "alerts": 43
        }
    ]
}

print("=== 1. 직접 report.analyze_daily 호출 테스트 ===")
res1 = report.analyze_daily(sample_data, cache_key=None)
print("Result 1:")
print(json.dumps(res1, ensure_ascii=False, indent=2))

print("\n=== 2. 라우터 analyze_daily 호출 테스트 ===")
res2 = analyze_daily(sample_data)
print("Result 2:")
print(json.dumps(res2, ensure_ascii=False, indent=2))

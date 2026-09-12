"""
==============================================================================
MODULE 5: END-TO-END AUTOMATED INTEGRATION TEST
Kiểm thử liên thông toàn bộ các dịch vụ: Backend API -> Forecast -> Threshold Update
==============================================================================
"""

import sys
from datetime import datetime, timezone
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:8000"


def run_e2e_tests():
    print("\n=======================================================")
    print("BAT DAU KIEM THU TICH HOP TOAN HE THONG (END-TO-END)")
    print("=======================================================")

    results = []

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # Step 1: Health check
        try:
            r = client.get("/api/health")
            if r.status_code == 200 and r.json().get("status") == "online":
                results.append(("1. Backend Health Check", True, "Online"))
            else:
                results.append(("1. Backend Health Check", False, f"Status code: {r.status_code}"))
        except Exception as e:
            results.append(("1. Backend Health Check", False, f"Connection error: {e}"))

        # Step 2: GET /api/weather/current
        try:
            r = client.get("/api/weather/current")
            if r.status_code == 200 and "temperature" in r.json():
                data = r.json()
                results.append(("2. API Current Weather", True, f"T={data['temperature']}°C, H={data['humidity']}%"))
            else:
                results.append(("2. API Current Weather", False, f"Status: {r.status_code}"))
        except Exception as e:
            results.append(("2. API Current Weather", False, str(e)))

        # Step 3: GET /api/weather/forecast
        try:
            r = client.get("/api/weather/forecast")
            if r.status_code == 200:
                data = r.json()
                p30 = data["plus_30m"]["rain_probability"]
                t30 = data["plus_30m"]["temperature_c"]
                results.append(("3. AI Inference API (/forecast)", True, f"+30m Forecast: {t30}°C, Rain: {int(p30*100)}%"))
            else:
                results.append(("3. AI Inference API (/forecast)", False, f"Status: {r.status_code}"))
        except Exception as e:
            results.append(("3. AI Inference API (/forecast)", False, str(e)))

        # Step 4: POST /api/weather/alerts/threshold (2-way control)
        try:
            r = client.post("/api/weather/alerts/threshold", json={"threshold": 0.65})
            if r.status_code == 200 and r.json().get("new_threshold") == 0.65:
                results.append(("4. Closed-loop Threshold Update", True, "Updated to 65% successfully"))
            else:
                results.append(("4. Closed-loop Threshold Update", False, f"Status: {r.status_code}"))
        except Exception as e:
            results.append(("4. Closed-loop Threshold Update", False, str(e)))

    # In bang tong ket
    print("\n" + "-"*65)
    print(f"{'Hang muc kiem thu':<35}{'Ket qua':<12}{'Chi tiet'}")
    print("-"*65)
    all_passed = True
    for name, passed, detail in results:
        status_str = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f"{name:<35}{status_str:<12}{detail}")
    print("-"*65)

    if all_passed:
        print("\n>>> TAT CA BAI KIEM THU LIEN THONG DEU DAT YEU CAU! <<<")
    else:
        print("\n>>> CO BAI KIEM THU CHUA DAT. Vui long kiem tra lai service. <<<")


if __name__ == "__main__":
    run_e2e_tests()


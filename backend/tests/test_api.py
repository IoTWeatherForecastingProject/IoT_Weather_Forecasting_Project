from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "service" in data


def test_get_current_weather_fallback():
    # Khi DB rỗng hoặc test cục bộ, API vẫn trả về đối tượng hợp lệ
    response = client.get("/api/weather/current")
    assert response.status_code == 200
    data = response.json()
    assert "temperature" in data
    assert "humidity" in data
    assert "pressure" in data


def test_get_forecast():
    response = client.get("/api/weather/forecast")
    assert response.status_code == 200
    data = response.json()
    assert "plus_10m" in data
    assert "plus_30m" in data
    assert "plus_60m" in data
    assert "temperature_c" in data["plus_10m"]
    assert "rain_probability" in data["plus_10m"]


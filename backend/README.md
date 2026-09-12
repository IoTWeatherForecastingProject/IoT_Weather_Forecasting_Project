# MODULE 2: DATA INGESTION, STORAGE & BACKEND API SERVER
## Máy Chủ Thu Thập Dữ Liệu, CSDL Chuỗi Thời Gian & REST/WebSocket API

> **Phụ trách chính:** 👤 **Thành viên 1 (IoT + Backend Engineer)**  
> **Phối hợp:** TV2 (kết nối DB lấy dữ liệu huấn luyện), TV3 (kết nối WebSocket và API lên Dashboard).  
> **Các Task liên quan:** `BE-01`, `BE-02`, `BE-03`, `BE-04`, `BE-05`, `BE-06` (Xem chi tiết tại [TASK.md](../TASK.md)).

---

## 1. Mục tiêu Kỹ thuật

Xây dựng hạ tầng Backend hiệu năng cao, chịu lỗi và có khả năng phục vụ theo thời gian thực:
1. **MQTT Data Ingestion Worker:** Chạy nền lắng nghe liên tục stream dữ liệu cảm biến từ topic `weather/+/data`, xác thực định dạng và lưu vào PostgreSQL.
2. **Time-Series Database:** Tối ưu hóa bảng CSDL `weather_measurements` với Composite Index `(device_id, timestamp DESC)` để các truy vấn cửa sổ trượt (Sliding Window) chạy dưới **10ms**.
3. **Hệ thống REST API (FastAPI):** Cung cấp các endpoint truy vấn thời tiết hiện tại, dữ liệu lịch sử phân trang và dữ liệu dự báo.
4. **Kênh WebSocket Thời gian thực:** Đẩy tức thời (Push notification) mỗi bản ghi thời tiết mới nhận được xuống Dashboard SCADA mà không cần client phải polling liên tục.
5. **Vòng lặp Cảnh báo Phản hồi 2 Chiều (Closed-loop Engine):** Khi mô hình AI dự báo xác suất mưa $\ge 70\%$, Backend tự động:
   - Bắn lệnh MQTT xuống trạm IoT (topic `weather/station01/alert`) để kích hoạt còi hú và đèn chớp.
   - Gửi tin nhắn cảnh báo có định dạng qua Telegram Bot đến người dùng.

---

## 2. Cấu trúc Thư mục Backend

```text
backend/
├── README.md               # Tài liệu hướng dẫn cài đặt và vận hành Backend
├── requirements.txt        # Danh sách thư viện Python cần thiết
├── Dockerfile              # File cấu hình đóng gói Docker image
├── .env.example            # Tệp mẫu biến môi trường (Database, MQTT, Telegram)
├── migrations/
│   └── 001_init_schema.sql # Script SQL khởi tạo bảng và chỉ mục tối ưu
├── app/
│   ├── main.py             # Entry point FastAPI, quản lý Lifespan & WebSocket
│   ├── config.py           # Cấu hình Pydantic BaseSettings đọc từ .env
│   ├── db/
│   │   ├── session.py      # Quản lý Database Connection Pool (Async/Sync)
│   │   └── models.py       # SQLAlchemy Models (weather_measurements, alert_logs)
│   ├── schemas/
│   │   └── weather.py      # Pydantic Schemas validate dữ liệu vào/ra
│   ├── ingestion/
│   │   └── mqtt_worker.py  # Thread/Daemon lắng nghe MQTT và ghi vào DB
│   ├── services/
│   │   ├── alert_service.py # Xử lý vòng lặp phản hồi 2 chiều & Telegram Bot
│   │   └── forecast_client.py # Tích hợp gọi hàm suy luận từ ai_engine/
│   └── api/
│       └── endpoints.py    # REST API routes (/current, /history, /forecast...)
└── tests/
    └── test_api.py         # Kiểm thử tự động API endpoints
```

---

## 3. Thiết kế CSDL Chuỗi Thời Gian (Database Schema)

Bảng `weather_measurements`:
```sql
CREATE TABLE IF NOT EXISTS weather_measurements (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temperature NUMERIC(5, 2) NOT NULL,
    humidity NUMERIC(5, 2) NOT NULL,
    pressure NUMERIC(6, 2) NOT NULL,
    rain_raw INTEGER,
    rain_detected SMALLINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Composite Index cực kỳ quan trọng cho truy vấn cửa sổ trượt
CREATE INDEX idx_weather_device_timestamp 
ON weather_measurements (device_id, timestamp DESC);
```

---

## 4. Danh sách REST API Endpoints

| Phương thức | Endpoint | Mô tả | Đầu ra mẫu |
|---|---|---|---|
| `GET` | `/api/weather/current` | Lấy bản ghi thời tiết mới nhất của trạm | `{ "temperature": 31.2, "humidity": 78, "pressure": 1005.8 }` |
| `GET` | `/api/weather/history?limit=100` | Lấy dữ liệu lịch sử để vẽ biểu đồ | Mảng JSON các điểm dữ liệu gần nhất |
| `GET` | `/api/weather/forecast` | Trả về kết quả dự báo (+10m, +30m, +60m) | `{ "temperature_forecast": {...}, "rain_probability": {...} }` |
| `POST` | `/api/weather/alerts/threshold` | Cập nhật ngưỡng cảnh báo mưa 2 chiều | `{ "threshold": 0.65, "status": "updated" }` |
| `GET` | `/api/health` | Kiểm tra trạng thái Database & MQTT | `{ "database": "connected", "mqtt": "online" }` |
| `WebSocket`| `/ws/weather/live` | Stream đẩy dữ liệu realtime mỗi 5s | Đẩy payload JSON ngay khi nhận từ MQTT |

---

## 5. Hướng dẫn Cài đặt & Khởi chạy Cục bộ

### Bước 1: Chuẩn bị Môi trường Ảo
```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### Bước 2: Thiết lập Biến Môi trường
Sao chép `.env.example` thành `.env`:
```bash
cp .env.example .env
```
Chỉnh sửa thông số trong `.env` cho phù hợp:
```ini
DATABASE_URL=postgresql://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
RAIN_ALERT_THRESHOLD=0.70
```

### Bước 3: Chạy Database Migration
Đảm bảo container PostgreSQL đang chạy (`docker-compose up -d` ở thư mục gốc), sau đó chạy script khởi tạo:
```bash
# Sử dụng psql hoặc DBeaver chạy file:
migrations/001_init_schema.sql
```

### Bước 4: Khởi chạy FastAPI Server & Ingestion
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Mở tài liệu API tự động (Swagger UI): `http://localhost:8000/docs`
- Kiểm tra kênh WebSocket: kết nối tới `ws://localhost:8000/ws/weather/live`

---

## 6. Tiêu chí Hoàn thành (Definition of Done)

- [ ] Ingestion Worker nhận message từ MQTT và ghi vào PostgreSQL mà không rò rỉ kết nối (Connection leak).
- [ ] API `/api/weather/current` và `/api/weather/history` phản hồi dưới 50ms.
- [ ] Kênh WebSocket tự động đẩy dữ liệu cho nhiều client cùng lúc (Broadcast).
- [ ] Khi giả lập dữ liệu xác suất mưa cao $\ge 70\%$, Backend tự động bắn lệnh MQTT xuống `weather/station01/alert` và gửi thông báo Telegram trong vòng < 2 giây.
- [ ] Vượt qua toàn bộ unit test trong `tests/test_api.py`.


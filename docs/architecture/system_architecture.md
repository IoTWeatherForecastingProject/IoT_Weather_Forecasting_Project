# KIẾN TRÚC HỆ THỐNG TOÀN DIỆN (SYSTEM ARCHITECTURE SPECIFICATION)
## IoT Local Weather Monitoring & Short-Term Forecasting System

---

## 1. Sơ đồ Luồng Dữ liệu Tuần tự (Sequence Diagram)

Sơ đồ dưới đây mô tả luồng dữ liệu 2 chiều khép kín từ lúc cảm biến đọc tín hiệu đến khi Dashboard hiển thị và kích hoạt cảnh báo:

```mermaid
sequenceDiagram
    autonumber
    participant Sensor as BME280 & Rain Sensor
    participant ESP as ESP32 Station (TV1)
    participant MQTT as Mosquitto Broker (TV1)
    participant Worker as Ingestion Worker (TV1)
    participant DB as PostgreSQL DB (TV1)
    participant AI as Unified AI Engine (TV2 & TV3)
    participant API as FastAPI Backend (TV1)
    participant UI as SCADA Dashboard (TV3)

    loop Định kỳ mỗi 5s - 10s
        Sensor->>ESP: Đọc Nhiệt độ, Độ ẩm, Khí áp, Mưa thô
        ESP->>ESP: Lọc trung bình trượt (Moving Average)
        ESP->>MQTT: Publish JSON payload (weather/station01/data)
        MQTT->>Worker: Forward message
        par Ghi CSDL
            Worker->>DB: Insert weather_measurements (timestamptz)
        and Broadcast Live
            Worker->>API: Gửi callback
            API->>UI: Push WebSocket live (/ws/weather/live)
            UI->>UI: Cập nhật thẻ chỉ số & ApexCharts realtime
        end
    end

    loop Định kỳ mỗi 15s - 30s
        UI->>API: GET /api/weather/forecast
        API->>DB: Truy vấn 30 bản ghi gần nhất (Sliding Window)
        DB-->>API: Trả về cửa sổ dữ liệu
        API->>AI: predict_forecast(recent_data)
        AI->>AI: Trích xuất lag features, Delta P, Delta H
        AI->>AI: Suy luận Model 1 (Nhiệt độ) + Model 2 (Xác suất mưa)
        AI-->>API: Kết quả (+10m, +30m, +60m: Temp & Calibrated Rain Prob)
        API-->>UI: Trả về JSON Forecast

        opt Nếu Xác suất mưa >= Ngưỡng cấu hình (ví dụ: >= 70%)
            API->>MQTT: Publish lệnh cảnh báo (weather/station01/alert)
            MQTT->>ESP: Forward alert payload
            ESP->>ESP: Kêu còi Buzzer, nháy LED đỏ, hiện OLED
            API->>API: Gửi tin nhắn tức thời qua Telegram Bot
            UI->>UI: Hiển thị banner cảnh báo đỏ nổi bật
        end
    end

    opt Khi người dùng đổi ngưỡng trên Web
        UI->>API: POST /api/weather/alerts/threshold { threshold: 0.60 }
        API->>DB: Cập nhật bảng system_config
        API-->>UI: 200 OK (Cập nhật thành công)
    end
```

---

## 2. Thiết kế Cấu trúc CSDL (Database Schema & Indexes)

```mermaid
erDiagram
    weather_measurements {
        bigserial id PK
        varchar(50) device_id
        timestamptz timestamp
        numeric(5,2) temperature
        numeric(5,2) humidity
        numeric(6,2) pressure
        integer rain_raw
        smallint rain_detected
        timestamptz created_at
    }

    alert_logs {
        bigserial id PK
        varchar(50) device_id
        timestamptz timestamp
        varchar(50) alert_type
        numeric(5,4) rain_probability
        numeric(5,4) threshold
        boolean mqtt_sent
        boolean telegram_sent
        text notes
    }

    system_config {
        varchar(100) config_key PK
        varchar(255) config_value
        timestamptz updated_at
    }

    weather_measurements ||--o{ alert_logs : "triggers"
```

- **Composite Index:** `CREATE INDEX idx_weather_device_timestamp ON weather_measurements (device_id, timestamp DESC);`
  - Đảm bảo các truy vấn lấy bản ghi mới nhất hoặc cửa sổ trượt 30 điểm gần nhất đạt độ trễ $< 5$ms.

---

## 3. Máy Trạng thái Phản hồi Cảnh báo trên ESP (Firmware State Machine)

```mermaid
stateDiagram-v2
    [*] --> IDLE : Khởi động & Kết nối thành công

    state IDLE {
        [*] --> Measuring
        Measuring --> Publishing : Sau mỗi 5s
        Publishing --> Measuring : Hoàn tất gửi MQTT
    }

    IDLE --> ALERT_ACTIVE : Nhận payload weather/station01/alert

    state ALERT_ACTIVE {
        [*] --> BuzzingAndBlinking
        BuzzingAndBlinking --> BeepOn : 250ms
        BeepOn --> BeepOff : 250ms
        BeepOff --> BeepOn : Chu kỳ lặp
    }

    ALERT_ACTIVE --> IDLE : Hết thời gian cảnh báo (10s) hoặc nhận lệnh hủy
```


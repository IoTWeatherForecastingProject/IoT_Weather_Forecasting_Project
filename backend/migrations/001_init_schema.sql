-- ==============================================================================
-- DATABASE SCHEMA INITIALIZATION: IOT LOCAL WEATHER MONITORING
-- Database: PostgreSQL 15+ (Hỗ trợ TimescaleDB extension nếu có)
-- ==============================================================================

-- 1. Bảng lưu trữ số liệu đo từ trạm IoT (Multivariate Time Series)
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

-- Chỉ mục kết hợp (Composite Index) phục vụ truy vấn cửa sổ trượt (Sliding Window) nhanh dưới 10ms
CREATE INDEX IF NOT EXISTS idx_weather_device_timestamp 
ON weather_measurements (device_id, timestamp DESC);

-- 2. Bảng lưu trữ lịch sử cảnh báo 2 chiều (Closed-loop Alert Logs)
CREATE TABLE IF NOT EXISTS alert_logs (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    alert_type VARCHAR(50) NOT NULL,
    rain_probability NUMERIC(5, 4) NOT NULL,
    threshold NUMERIC(5, 4) NOT NULL,
    mqtt_sent BOOLEAN DEFAULT FALSE,
    telegram_sent BOOLEAN DEFAULT FALSE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_logs_timestamp 
ON alert_logs (timestamp DESC);

-- 3. Bảng cấu hình hệ thống thời gian thực
CREATE TABLE IF NOT EXISTS system_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Chèn cấu hình mặc định ban đầu
INSERT INTO system_config (config_key, config_value) 
VALUES ('rain_alert_threshold', '0.70')
ON CONFLICT (config_key) DO NOTHING;


-- ==============================================================================
-- REFERENCE WEATHER: DỮ LIỆU THỜI TIẾT THAM CHIẾU ĐỂ ĐỐI CHUẨN CẢM BIẾN
-- Database: PostgreSQL 15+; có thể chạy lại migration nhiều lần
-- ==============================================================================

-- Timestamp là thời điểm dữ liệu từ nguồn; fetched_at là thời điểm lưu vào DB.
CREATE TABLE IF NOT EXISTS reference_weather (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(30) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    lat NUMERIC(8, 5) NOT NULL,
    lon NUMERIC(8, 5) NOT NULL,
    temperature NUMERIC(5, 2),
    humidity NUMERIC(5, 2),
    pressure NUMERIC(6, 2),
    precipitation NUMERIC(6, 2),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_reference_source_ts UNIQUE (source, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_reference_source_ts
ON reference_weather (source, timestamp DESC);

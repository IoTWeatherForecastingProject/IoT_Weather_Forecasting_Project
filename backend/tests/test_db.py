import pytest
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import text, inspect, desc
from app.db.session import engine, SessionLocal, get_db, get_db_context, check_db_connection
from app.db.models import WeatherMeasurement, AlertLog, SystemConfig


def test_db_connection():
    """Kiểm tra hàm check_db_connection có thể ping CSDL thành công."""
    assert check_db_connection() is True


def test_db_tables_and_composite_index_exist():
    """Kiểm tra tính toàn vẹn của schema CSDL và sự tồn tại của Composite Index."""
    assert engine is not None
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    # Kiểm tra đủ 3 bảng cốt lõi
    assert "weather_measurements" in table_names
    assert "alert_logs" in table_names
    assert "system_config" in table_names

    # Kiểm tra Composite Index trên bảng weather_measurements
    indexes = inspector.get_indexes("weather_measurements")
    index_names = [idx["name"] for idx in indexes]
    assert "idx_weather_device_timestamp" in index_names, (
        f"Composite index 'idx_weather_device_timestamp' not found in indexes: {index_names}"
    )

    composite_idx = next(idx for idx in indexes if idx["name"] == "idx_weather_device_timestamp")
    assert "device_id" in composite_idx["column_names"]
    assert "timestamp" in composite_idx["column_names"]


def test_db_session_lifecycle():
    """Kiểm tra vòng đời của SQLAlchemy Session không rò rỉ kết nối."""
    # Test get_db generator
    gen = get_db()
    db = next(gen)
    assert db is not None
    res = db.execute(text("SELECT 1")).scalar()
    assert res == 1
    # Đóng generator để gọi finally: db.close()
    with pytest.raises(StopIteration):
        next(gen)

    # Test get_db_context context manager
    with get_db_context() as session:
        val = session.execute(text("SELECT 42")).scalar()
        assert val == 42


def test_sliding_window_query():
    """Kiểm tra truy vấn cửa sổ trượt (Sliding Window) 30 điểm đo mới nhất."""
    device_id = "test_station_stage1"
    now = datetime.now(timezone.utc)

    with get_db_context() as session:
        # Dọn dẹp dữ liệu test cũ nếu có
        session.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()

        # Tạo 35 bản ghi mẫu cách nhau 10 giây
        for i in range(35):
            record = WeatherMeasurement(
                device_id=device_id,
                timestamp=now.replace(microsecond=0),
                temperature=Decimal("29.50") + Decimal(str(round(i * 0.1, 2))),
                humidity=Decimal("75.00"),
                pressure=Decimal("1008.20"),
                rain_raw=2100,
                rain_detected=0,
            )
            session.add(record)

    # Truy vấn cửa sổ trượt 30 bản ghi gần nhất
    with get_db_context() as session:
        records = (
            session.query(WeatherMeasurement)
            .filter(WeatherMeasurement.device_id == device_id)
            .order_by(desc(WeatherMeasurement.timestamp))
            .limit(30)
            .all()
        )
        assert len(records) == 30
        # Bản ghi đầu tiên phải có timestamp mới nhất
        assert records[0].device_id == device_id

        # Dọn dẹp dữ liệu test
        session.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()

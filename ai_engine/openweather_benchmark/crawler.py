"""Thu thập thời tiết tham chiếu và lưu dữ liệu UTC để đối chuẩn cảm biến."""

import argparse
import csv
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
FIELDS = (
    "source", "timestamp", "lat", "lon", "temperature", "humidity",
    "pressure", "precipitation",
)
METEO_VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "surface_pressure",
    "precipitation",
)
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / "backend" / ".env"
# Open-Meteo: "current" là giá trị 15 phút, "hourly" là giá trị theo giờ.
# Tách source để hai độ phân giải không đụng UNIQUE(source, timestamp).
SOURCE_METEO_HOURLY = "open-meteo"
SOURCE_METEO_15MIN = "open-meteo-15min"
RETRY_DELAYS_S = (2, 4, 8)
HTTP_TIMEOUT_S = 10
DB_CONNECT_TIMEOUT_S = 10


class CrawlerError(Exception):
    """Lỗi một lượt thu thập, thông điệp đã an toàn để ghi log."""


@dataclass(frozen=True)
class ReferenceRecord:
    """Một bản ghi tham chiếu, dùng thời điểm dữ liệu do nguồn cung cấp."""

    source: str
    timestamp: datetime
    lat: float
    lon: float
    temperature: float | None
    humidity: float | None
    pressure: float | None
    precipitation: float | None

    def __post_init__(self):
        if self.timestamp.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(UTC))


def _parse_timestamp(value: str) -> datetime:
    """Đọc ISO-8601; thời gian Open-Meteo không có offset được hiểu là UTC."""
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _number(value) -> float | None:
    """Chuyển số đo sang float, giữ nguyên giá trị null hợp lệ."""
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Measurement must be finite")
    return result


class WeatherBenchmarkCrawler:
    """Lấy dữ liệu hai nguồn với tọa độ mặc định tại TP. Hồ Chí Minh."""

    def __init__(self, lat=10.762622, lon=106.660172, api_key=None,
                 sleep: Callable | None = None, now: Callable | None = None):
        self.lat = lat
        self.lon = lon
        self.api_key = (
            os.getenv("OPENWEATHER_API_KEY") if api_key is None else api_key
        )
        self.sleep = sleep if sleep is not None else time.sleep
        self.now = now if now is not None else lambda: datetime.now(UTC)

    def _fetch(self, url, params, parse, source) -> list[ReferenceRecord]:
        """
        Tổng cộng 4 lần thử (1 lần đầu + 3 lần retry), chờ 2/4/8 giây giữa
        các lần, không chờ sau lần cuối. Lỗi 4xx (trừ 429) dừng ngay vì
        retry không giúp được (sai key, sai tham số).
        """
        attempts = len(RETRY_DELAYS_S) + 1
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(url, params=params,
                                        timeout=HTTP_TIMEOUT_S)
                response.raise_for_status()
                return parse(response.json())
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if (isinstance(status, int) and 400 <= status < 500
                        and status != 429):
                    logger.warning("%s request rejected (HTTP %d)",
                                   source, status)
                    return []
                self._log_attempt(source, attempt, attempts, exc)
            except (requests.RequestException, ValueError, KeyError, TypeError,
                    IndexError, AttributeError, OverflowError) as exc:
                self._log_attempt(source, attempt, attempts, exc)
            if attempt < attempts:
                self.sleep(RETRY_DELAYS_S[attempt - 1])
        return []

    @staticmethod
    def _log_attempt(source, attempt, attempts, exc):
        # Không log URL hoặc nội dung exception có thể chứa API key.
        logger.warning("%s attempt %d/%d failed (%s)",
                       source, attempt, attempts, type(exc).__name__)

    def _meteo_record(self, source, timestamp, values):
        """Chuẩn hóa bốn đại lượng Open-Meteo theo thứ tự schema."""
        return ReferenceRecord(
            source, _parse_timestamp(timestamp), self.lat, self.lon,
            *(_number(value) for value in values),
        )

    def fetch_open_meteo_current(self) -> list[ReferenceRecord]:
        """Lấy thời tiết hiện tại với timestamp từ current.time."""
        def parse(payload):
            current = payload["current"]
            return [self._meteo_record(
                SOURCE_METEO_15MIN, current["time"],
                [current[key] for key in METEO_VARIABLES],
            )]

        return self._fetch(
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": self.lat, "longitude": self.lon,
             "current": ",".join(METEO_VARIABLES), "timezone": "UTC"},
            parse, SOURCE_METEO_15MIN,
        )

    def fetch_open_meteo_history(
        self, past_days: int,
    ) -> list[ReferenceRecord]:
        """Lấy lịch sử theo giờ, bỏ giờ tương lai và mốc thiếu cả ba số đo."""
        if not 1 <= past_days <= 92:
            raise ValueError("past_days must be between 1 and 92")

        def parse(payload):
            hourly = payload["hourly"]
            timestamps = hourly["time"]
            columns = [hourly[key] for key in METEO_VARIABLES]
            if any(len(column) != len(timestamps) for column in columns):
                raise ValueError("Hourly arrays have different lengths")
            now = self.now().astimezone(UTC)
            records = []
            for index, timestamp in enumerate(timestamps):
                values = [column[index] for column in columns]
                if all(value is None for value in values[:3]):
                    continue
                record = self._meteo_record(SOURCE_METEO_HOURLY, timestamp,
                                            values)
                if record.timestamp <= now:
                    records.append(record)
            return records

        return self._fetch(
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": self.lat, "longitude": self.lon,
             "hourly": ",".join(METEO_VARIABLES), "past_days": past_days,
             "forecast_days": 1, "timezone": "UTC"},
            parse, SOURCE_METEO_HOURLY,
        )

    def fetch_openweather_current(self) -> list[ReferenceRecord]:
        """Lấy OpenWeather khi có key, ưu tiên áp suất tại mặt đất."""
        if not self.api_key:
            logger.info("OPENWEATHER_API_KEY missing; skipping openweather")
            return []

        def parse(payload):
            main = payload["main"]
            pressure = (
                main["grnd_level"] if main.get("grnd_level") is not None
                else main["pressure"]
            )
            return [ReferenceRecord(
                "openweather", datetime.fromtimestamp(payload["dt"], UTC),
                self.lat, self.lon, _number(main["temp"]),
                _number(main["humidity"]), _number(pressure),
                _number(payload.get("rain", {}).get("1h", 0.0)),
            )]

        return self._fetch(
            "https://api.openweathermap.org/data/2.5/weather",
            {"lat": self.lat, "lon": self.lon, "appid": self.api_key,
             "units": "metric"}, parse, "openweather",
        )

    def fetch_open_meteo(self) -> dict:
        """Giữ giao diện dictionary cũ cho các bên gọi hiện có."""
        records = self.fetch_open_meteo_current()
        if not records:
            return {"status": "failed", "source": "Open-Meteo"}
        return {**asdict(records[0]), "source": "Open-Meteo",
                "status": "success"}

    @staticmethod
    def calculate_sensor_bias(
        iot_data: dict[str, float], benchmark_data: dict[str, float],
    ) -> dict[str, float]:
        """
        Tính toán độ lệch (Bias) giữa cảm biến IoT giá rẻ và trạm chuẩn:
        Bias = IoT_value - Benchmark_value
        """
        bias = {}
        if "temperature" in iot_data and "temperature" in benchmark_data:
            bias["temp_bias_c"] = round(
                float(iot_data["temperature"])
                - float(benchmark_data["temperature"]), 2,
            )
        if "humidity" in iot_data and "humidity" in benchmark_data:
            bias["hum_bias_percent"] = round(
                float(iot_data["humidity"])
                - float(benchmark_data["humidity"]), 2,
            )
        if "pressure" in iot_data and "pressure" in benchmark_data:
            bias["press_bias_hpa"] = round(
                float(iot_data["pressure"])
                - float(benchmark_data["pressure"]), 2,
            )
        return bias


def save_to_csv(records: list[ReferenceRecord], path) -> int:
    """Nối CSV theo schema, khử trùng nguồn và thời điểm kể cả trong một lô."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    has_header = path.exists() and path.stat().st_size > 0
    if has_header:
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                seen.add((row["source"], _parse_timestamp(row["timestamp"])))
    inserted = 0
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if not has_header:
            writer.writeheader()
        for record in records:
            key = (record.source, record.timestamp)
            if key in seen:
                continue
            row = asdict(record)
            row["timestamp"] = record.timestamp.isoformat()
            writer.writerow(row)
            seen.add(key)
            inserted += 1
    return inserted


def normalize_database_url(database_url: str) -> str:
    """Chọn psycopg 3 cho URL PostgreSQL dạng mặc định."""
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://"):]
    return database_url


def get_database_url(env_path=DEFAULT_ENV_PATH) -> str:
    """Ưu tiên biến môi trường, sau đó đọc KEY=VALUE từ backend/.env."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url and Path(env_path).exists():
        contents = Path(env_path).read_text(encoding="utf-8-sig")
        for line in contents.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != "DATABASE_URL":
                continue
            value = value.strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                database_url = value[1:end] if end >= 1 else ""
            else:
                database_url = value.split(" #", 1)[0].strip()
    if not database_url:
        raise ValueError("DATABASE_URL missing; set it or use --csv PATH")
    return normalize_database_url(database_url)


def _url_password(database_url: str) -> str | None:
    try:
        from sqlalchemy.engine import make_url
        return make_url(database_url).password
    except Exception:  # noqa: BLE001 - URL hỏng thì không có gì để ẩn
        return None


def mask_database_url(database_url: str) -> str:
    """Ẩn mật khẩu trong URL trước khi ghi log."""
    try:
        from sqlalchemy.engine import make_url
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - URL hỏng vẫn không được lộ ra log
        return "<invalid database url>"


def describe_db_error(exc: Exception, database_url: str) -> str:
    """Thông điệp lỗi DB có thể xử lý được, không chứa mật khẩu."""
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) == "42P01":
        return ("Table reference_weather missing - run "
                "backend/migrations/002_reference_weather.sql")
    if type(exc).__name__ == "OperationalError":
        return f"Cannot connect to database {mask_database_url(database_url)}"
    lines = str(orig if orig is not None else exc).splitlines()
    message = f"{type(exc).__name__}: {lines[0] if lines else ''}"
    password = _url_password(database_url)
    return message.replace(password, "***") if password else message


def save_to_db(records: list[ReferenceRecord], database_url: str) -> int:
    """Chèn PostgreSQL bằng Core; chỉ đếm các dòng RETURNING thực sự chèn."""
    if not records:
        return 0
    from sqlalchemy import (
        Column,
        DateTime,
        MetaData,
        Numeric,
        String,
        Table,
        create_engine,
        literal_column,
    )
    from sqlalchemy.dialects.postgresql import insert

    table = Table(
        "reference_weather", MetaData(),
        Column("source", String(30)),
        Column("timestamp", DateTime(timezone=True)),
        *(Column(name, Numeric()) for name in FIELDS[2:]),
    )
    # connect_timeout: thiếu nó thì DB không phản hồi làm crawler treo vô hạn
    engine = create_engine(
        normalize_database_url(database_url),
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_S},
        pool_pre_ping=True,
    )
    inserted = 0
    try:
        with engine.begin() as connection:
            for start in range(0, len(records), 1000):
                statement = insert(table).values([
                    asdict(record) for record in records[start:start + 1000]
                ]).on_conflict_do_nothing(
                    index_elements=["source", "timestamp"],
                ).returning(literal_column("1"))
                inserted += len(connection.execute(statement).fetchall())
    finally:
        engine.dispose()
    return inserted


def parse_args(argv=None):
    """Kiểm tra chế độ CLI và các giới hạn tham số trước khi gọi mạng."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--backfill-days", type=int, choices=range(1, 93),
                      metavar="N")
    parser.add_argument("--interval", type=float)
    parser.add_argument(
        "--source", choices=("open-meteo", "openweather", "all"), default="all",
    )
    parser.add_argument("--lat", type=float, default=10.762622)
    parser.add_argument("--lon", type=float, default=106.660172)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    if args.interval is not None and not args.loop:
        parser.error("--interval requires --loop")
    args.interval = 900 if args.interval is None else args.interval
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and positive")
    if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180:
        parser.error("Invalid latitude or longitude")
    return args


def run_cycle(args, crawler) -> tuple[int, int]:
    """
    Thu thập một lượt rồi lưu. Ném CrawlerError khi mọi nguồn được bật đều
    không trả dữ liệu hoặc khi lưu thất bại (thông điệp đã an toàn để log).
    """
    records = []
    if args.source in ("open-meteo", "all"):
        if args.backfill_days:
            records.extend(crawler.fetch_open_meteo_history(args.backfill_days))
        else:
            records.extend(crawler.fetch_open_meteo_current())
    if args.source in ("openweather", "all"):
        if args.backfill_days:
            logger.info("Skipping openweather: endpoint has no history")
        else:
            records.extend(crawler.fetch_openweather_current())
    if not records:
        raise CrawlerError("No records fetched from enabled sources")

    database_url = None
    try:
        if args.csv is not None:
            inserted = save_to_csv(records, args.csv)
        else:
            database_url = get_database_url()
            inserted = save_to_db(records, database_url)
    except Exception as exc:  # phân loại lỗi rồi ném lại CrawlerError
        if database_url is None:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = describe_db_error(exc, database_url)
        raise CrawlerError(
            f"Fetched {len(records)} records; save failed - {reason}",
        ) from exc
    logger.info("Fetched %d records; inserted %d new records",
                len(records), inserted)
    return len(records), inserted


def main(argv=None) -> int:
    """Chạy một lần, bù lịch sử hoặc lặp; Ctrl+C kết thúc sạch."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    crawler = WeatherBenchmarkCrawler(args.lat, args.lon)
    try:
        while True:
            try:
                run_cycle(args, crawler)
            except CrawlerError as exc:
                logger.error("Crawler cycle failed: %s", exc)
                if not args.loop:
                    return 1
            # Một vòng lỗi vẫn phải tiếp tục; không log exception chứa secret.
            except Exception as exc:  # noqa: BLE001
                logger.error("Crawler cycle failed (%s)", type(exc).__name__)
                if not args.loop:
                    return 1
            if not args.loop:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Crawler stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

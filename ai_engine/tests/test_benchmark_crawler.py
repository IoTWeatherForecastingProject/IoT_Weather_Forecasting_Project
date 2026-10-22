"""Kiểm thử crawler offline: không gọi API thật và không cần PostgreSQL."""

import builtins
import csv
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, call

import pytest
import requests

from openweather_benchmark import crawler as module
from openweather_benchmark.crawler import (
    FIELDS,
    UTC,
    ReferenceRecord,
    WeatherBenchmarkCrawler,
    get_database_url,
    main,
    normalize_database_url,
    parse_args,
    run_cycle,
    save_to_csv,
    save_to_db,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Chặn mọi HTTP thật và xóa cấu hình môi trường của máy chạy test."""
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get = Mock(side_effect=AssertionError("Real HTTP is forbidden in tests"))
    monkeypatch.setattr(module.requests, "get", get)
    return get


@pytest.fixture
def current_payload():
    return {"current": {
        "time": "2026-10-16T06:15", "temperature_2m": 30.2,
        "relative_humidity_2m": 78, "surface_pressure": 1004.8,
        "precipitation": 0.4,
    }}


@pytest.fixture
def record():
    return ReferenceRecord(
        "open-meteo", datetime(2026, 10, 16, 6, tzinfo=UTC),
        10.762622, 106.660172, 30.2, 78, 1004.8, None,
    )


def respond(get, payload):
    """Cấu hình phản hồi HTTP thành công cho mock đã chặn mạng."""
    response = Mock()
    response.json.return_value = payload
    get.side_effect = None
    get.return_value = response
    return response


def test_meteo_current_values_timestamp_and_params(offline, current_payload):
    respond(offline, current_payload)
    item, = WeatherBenchmarkCrawler().fetch_open_meteo_current()
    assert item.source == "open-meteo-15min"
    assert item.timestamp == datetime(2026, 10, 16, 6, 15, tzinfo=UTC)
    assert item.timestamp.tzinfo is UTC
    assert (item.temperature, item.humidity, item.pressure,
            item.precipitation) == (30.2, 78, 1004.8, 0.4)
    assert (item.lat, item.lon) == (10.762622, 106.660172)
    offline.assert_called_once_with(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": 10.762622, "longitude": 106.660172,
                "current": "temperature_2m,relative_humidity_2m,"
                           "surface_pressure,precipitation",
                "timezone": "UTC"},
        timeout=10,
    )


def test_history_filters_future_and_null_rows(offline):
    respond(offline, {"hourly": {
        "time": ["2026-10-16T04:00", "2026-10-16T05:00",
                 "2026-10-16T06:00", "2026-10-16T07:00"],
        "temperature_2m": [None, None, 30, 31],
        "relative_humidity_2m": [None, 80, 75, 70],
        "surface_pressure": [None, None, 1005, 1004],
        "precipitation": [1.0, None, 0.0, 0.0],
    }})
    crawler = WeatherBenchmarkCrawler(
        now=lambda: datetime(2026, 10, 16, 6, tzinfo=UTC),
    )
    records = crawler.fetch_open_meteo_history(2)
    assert [item.timestamp.hour for item in records] == [5, 6]
    assert records[0].temperature is None
    assert records[0].humidity == 80
    params = offline.call_args.kwargs["params"]
    assert params == {
        "latitude": 10.762622, "longitude": 106.660172,
        "hourly": ",".join(module.METEO_VARIABLES), "past_days": 2,
        "forecast_days": 1, "timezone": "UTC",
    }


@pytest.mark.parametrize("days", [0, -1, 93])
def test_history_rejects_out_of_range(offline, days):
    with pytest.raises(ValueError):
        WeatherBenchmarkCrawler().fetch_open_meteo_history(days)
    offline.assert_not_called()


@pytest.mark.parametrize("ground,rain,expected", [
    (1001, None, 0.0), (None, {"1h": 1.2}, 1.2),
])
def test_openweather_pressure_rain_and_epoch(
        offline, monkeypatch, ground, rain, expected):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key")
    payload = {"dt": 1792130400,
               "main": {"temp": 30, "humidity": 80, "pressure": 1010}}
    if ground is not None:
        payload["main"]["grnd_level"] = ground
    if rain is not None:
        payload["rain"] = rain
    respond(offline, payload)
    item, = WeatherBenchmarkCrawler().fetch_openweather_current()
    assert item.source == "openweather"
    assert (item.temperature, item.humidity) == (30, 80)
    assert item.pressure == (ground if ground is not None else 1010)
    assert item.precipitation == expected
    assert item.timestamp == datetime.fromtimestamp(payload["dt"], UTC)
    assert item.timestamp.tzinfo is UTC
    assert offline.call_args.kwargs == {
        "params": {"lat": 10.762622, "lon": 106.660172,
                   "appid": "test-key", "units": "metric"}, "timeout": 10,
    }


def test_openweather_without_key_skips_http(offline, caplog):
    with caplog.at_level(logging.INFO):
        assert WeatherBenchmarkCrawler().fetch_openweather_current() == []
    offline.assert_not_called()
    assert "OPENWEATHER_API_KEY missing" in caplog.text


@pytest.mark.parametrize("failure", ["500", "timeout", "json", "missing"])
def test_http_failure_exactly_four_attempts(
        offline, current_payload, caplog, failure):
    response = respond(offline, current_payload)
    if failure == "500":
        response.raise_for_status.side_effect = requests.HTTPError("500")
    elif failure == "timeout":
        offline.side_effect = requests.Timeout("Timeout")
    elif failure == "json":
        response.json.side_effect = ValueError("Invalid JSON")
    else:
        response.json.return_value = {"current": {"time": "invalid"}}
    sleep = Mock()
    crawler = WeatherBenchmarkCrawler(sleep=sleep)
    assert crawler.fetch_open_meteo_current() == []
    assert offline.call_count == 4
    assert sleep.call_args_list == [call(2), call(4), call(8)]
    assert sum(record.levelno == logging.WARNING
               for record in caplog.records) == 4


def test_retry_can_recover(offline, current_payload):
    response = respond(offline, current_payload)
    offline.side_effect = [requests.Timeout(), response]
    sleep = Mock()
    assert len(WeatherBenchmarkCrawler(
        sleep=sleep,
    ).fetch_open_meteo_current()) == 1
    assert offline.call_count == 2
    sleep.assert_called_once_with(2)


def test_csv_appends_and_deduplicates_source_and_utc_time(tmp_path, record):
    path = tmp_path / "nested" / "reference.csv"
    assert save_to_csv([record, record], path) == 1
    assert save_to_csv([record], path) == 0
    next_record = replace(
        record, timestamp=record.timestamp + timedelta(hours=1),
    )
    other_source = replace(record, source="openweather")
    assert save_to_csv([record, next_record, other_source], path) == 2
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(FIELDS)
        rows = list(reader)
    assert len(rows) == 3
    assert [row["source"] for row in rows] == [
        "open-meteo", "open-meteo", "openweather",
    ]
    assert rows[0]["timestamp"].endswith("+00:00")
    assert rows[0]["precipitation"] == ""
    path.write_text(path.read_text().replace("+00:00", "Z"), encoding="utf-8")
    assert save_to_csv([record], path) == 0


def test_record_normalizes_timezone_and_rejects_naive(record):
    offset = timezone(timedelta(hours=7))
    local = record.timestamp.astimezone(offset)
    assert replace(record, timestamp=local).timestamp.tzinfo is UTC
    with pytest.raises(ValueError):
        replace(record, timestamp=record.timestamp.replace(tzinfo=None))


@pytest.mark.parametrize("value", [
    "postgresql://user:password@localhost/db # comment",
    '"postgresql://user:password@localhost/db" # comment',
    "'postgresql://user:password@localhost/db'",
])
def test_env_parser_comments_blanks_and_quotes(tmp_path, value):
    path = tmp_path / ".env"
    path.write_text(
        "\n # comment\nINVALID\nOTHER=value\n DATABASE_URL = " + value + "\n",
        encoding="utf-8",
    )
    assert get_database_url(path) == (
        "postgresql+psycopg://user:password@localhost/db"
    )


def test_environment_has_priority(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgresql://file/db", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment/db")
    assert get_database_url(path) == "postgresql+psycopg://environment/db"


def test_missing_database_config(tmp_path):
    with pytest.raises(ValueError, match="DATABASE_URL missing"):
        get_database_url(tmp_path / "missing.env")


@pytest.mark.parametrize("url,expected", [
    ("postgresql://host/db", "postgresql+psycopg://host/db"),
    ("postgresql+psycopg://host/db", "postgresql+psycopg://host/db"),
])
def test_database_url_normalization(url, expected):
    assert normalize_database_url(url) == expected


def test_csv_and_empty_db_do_not_import_sqlalchemy(
        monkeypatch, tmp_path, record):
    original_import = builtins.__import__

    def without_sqlalchemy(name, *args, **kwargs):
        if name.split(".")[0] == "sqlalchemy":
            raise AssertionError("SQLAlchemy must be imported lazily")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sqlalchemy)
    assert save_to_csv([record], tmp_path / "reference.csv") == 1
    assert save_to_db([], "postgresql://unused/db") == 0


def test_db_core_conflict_and_actual_insert_count(monkeypatch, record):
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from sqlalchemy.dialects import postgresql

    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.fetchall.return_value = [(1,)]
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    assert save_to_db([record, record], "postgresql://host/db") == 1
    create_engine.assert_called_once_with(
        "postgresql+psycopg://host/db",
        connect_args={"connect_timeout": module.DB_CONNECT_TIMEOUT_S},
        pool_pre_ping=True,
    )
    statement = connection.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (source, timestamp) DO NOTHING" in sql
    assert "RETURNING 1" in sql
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("argv", [
    [], ["--once", "--loop"], ["--once", "--backfill-days", "2"],
    ["--once", "--interval", "900"], ["--backfill-days", "93"],
    ["--loop", "--interval", "0"], ["--loop", "--interval", "nan"],
    ["--once", "--lat", "91"],
])
def test_cli_rejects_invalid_arguments(argv):
    with pytest.raises(SystemExit) as error:
        parse_args(argv)
    assert error.value.code == 2


def test_cli_defaults():
    args = parse_args(["--loop"])
    assert args.interval == 900
    assert args.source == "all"
    assert (args.lat, args.lon) == (10.762622, 106.660172)


def test_backfill_skips_current_openweather(tmp_path, record, caplog):
    args = parse_args(["--backfill-days", "2", "--csv",
                       str(tmp_path / "reference.csv")])
    crawler = Mock()
    crawler.fetch_open_meteo_history.return_value = [record]
    with caplog.at_level(logging.INFO):
        assert run_cycle(args, crawler) == (1, 1)
        assert run_cycle(args, crawler) == (1, 0)
    crawler.fetch_openweather_current.assert_not_called()
    assert "Fetched 1 records; inserted 0 new records" in caplog.text


def test_loop_recovers_and_ctrl_c_exits_cleanly(monkeypatch, caplog):
    cycle = Mock(side_effect=[RuntimeError("Failure"), (0, 0)])
    sleep = Mock(side_effect=[None, KeyboardInterrupt()])
    monkeypatch.setattr(module, "run_cycle", cycle)
    monkeypatch.setattr(module.time, "sleep", sleep)
    with caplog.at_level(logging.INFO):
        assert main(["--loop", "--interval", "1"]) == 0
    assert cycle.call_count == 2
    assert sleep.call_args_list == [call(1), call(1)]
    assert "Crawler cycle failed (RuntimeError)" in caplog.text
    assert "Crawler stopped" in caplog.text


def test_bias_legacy_behavior():
    assert WeatherBenchmarkCrawler.calculate_sensor_bias(
        {"temperature": 31.234, "humidity": 75, "pressure": 1000},
        {"temperature": 30, "humidity": 80, "pressure": 1002},
    ) == {
        "temp_bias_c": 1.23, "hum_bias_percent": -5.0, "press_bias_hpa": -2.0,
    }
    assert WeatherBenchmarkCrawler.calculate_sensor_bias({}, {}) == {}


# --- Các lỗi phát hiện khi review T1 -----------------------------------------

def test_history_uses_hourly_source(offline):
    respond(offline, {"hourly": {
        "time": ["2026-10-16T05:00"], "temperature_2m": [30],
        "relative_humidity_2m": [75], "surface_pressure": [1005],
        "precipitation": [0.0],
    }})
    crawler = WeatherBenchmarkCrawler(
        now=lambda: datetime(2026, 10, 16, 6, tzinfo=UTC),
    )
    item, = crawler.fetch_open_meteo_history(1)
    assert item.source == module.SOURCE_METEO_HOURLY == "open-meteo"


def http_error(status):
    response = Mock(status_code=status)
    return requests.HTTPError(f"HTTP {status}", response=response)


def test_client_error_fails_fast_without_retry(offline, monkeypatch, caplog):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "secret-key")
    response = respond(offline, {})
    response.raise_for_status.side_effect = http_error(401)
    sleep = Mock()
    with caplog.at_level(logging.WARNING):
        assert WeatherBenchmarkCrawler(
            sleep=sleep,
        ).fetch_openweather_current() == []
    assert offline.call_count == 1
    sleep.assert_not_called()
    assert "request rejected (HTTP 401)" in caplog.text
    assert "secret-key" not in caplog.text


def test_rate_limit_is_retried(offline, current_payload):
    response = respond(offline, current_payload)
    response.raise_for_status.side_effect = [http_error(429), None]
    sleep = Mock()
    assert len(WeatherBenchmarkCrawler(
        sleep=sleep,
    ).fetch_open_meteo_current()) == 1
    assert offline.call_count == 2
    sleep.assert_called_once_with(2)


class FakeOrig(Exception):
    def __init__(self, message, sqlstate=None):
        super().__init__(message)
        self.sqlstate = sqlstate


def db_error(name, message, sqlstate=None):
    error_type = type(name, (Exception,), {})
    error = error_type(message)
    error.orig = FakeOrig(message, sqlstate)
    return error


URL = "postgresql://weather_admin:s3cretPass@db.local:5432/weather_db"


def test_describe_missing_table():
    error = db_error("ProgrammingError", 'relation "reference_weather"', "42P01")
    message = module.describe_db_error(error, URL)
    assert "002_reference_weather.sql" in message


def test_describe_connection_error_hides_password():
    message = module.describe_db_error(
        db_error("OperationalError", "timeout"), URL,
    )
    assert "Cannot connect to database" in message
    assert "db.local" in message
    assert "s3cretPass" not in message


def test_describe_other_error_redacts_password():
    message = module.describe_db_error(
        db_error("IntegrityError", "bad value for s3cretPass\nDETAIL: x"), URL,
    )
    assert message == "IntegrityError: bad value for ***"


def make_args(tmp_path=None, source="all", once=True):
    argv = ["--once", "--source", source]
    if tmp_path is not None:
        argv += ["--csv", str(tmp_path / "reference.csv")]
    return parse_args(argv)


def test_cycle_without_records_is_failure(tmp_path):
    crawler = Mock()
    crawler.fetch_open_meteo_current.return_value = []
    crawler.fetch_openweather_current.return_value = []
    with pytest.raises(module.CrawlerError, match="No records"):
        run_cycle(make_args(tmp_path), crawler)
    assert not (tmp_path / "reference.csv").exists()


def test_all_sources_succeeds_without_openweather_key(tmp_path, record):
    crawler = Mock()
    crawler.fetch_open_meteo_current.return_value = [record]
    crawler.fetch_openweather_current.return_value = []
    assert run_cycle(make_args(tmp_path), crawler) == (1, 1)


def test_db_save_failure_logs_actionable_message(monkeypatch, record, caplog):
    monkeypatch.setenv("DATABASE_URL", URL)

    def fail(records, database_url):
        raise db_error("ProgrammingError", "relation missing", "42P01")

    monkeypatch.setattr(module, "save_to_db", fail)
    crawler = Mock()
    crawler.fetch_open_meteo_current.return_value = [record]
    crawler.fetch_openweather_current.return_value = []
    monkeypatch.setattr(module, "WeatherBenchmarkCrawler",
                        Mock(return_value=crawler))
    with caplog.at_level(logging.INFO):
        assert main(["--once"]) == 1
    assert "save failed - Table reference_weather missing" in caplog.text
    assert "inserted" not in caplog.text
    assert "s3cretPass" not in caplog.text


def test_once_exits_nonzero_when_nothing_fetched(monkeypatch, caplog):
    crawler = Mock()
    crawler.fetch_open_meteo_current.return_value = []
    crawler.fetch_openweather_current.return_value = []
    monkeypatch.setattr(module, "WeatherBenchmarkCrawler",
                        Mock(return_value=crawler))
    with caplog.at_level(logging.ERROR):
        assert main(["--once"]) == 1
    assert "No records fetched" in caplog.text


def test_loop_continues_when_nothing_fetched(monkeypatch):
    crawler = Mock()
    crawler.fetch_open_meteo_current.return_value = []
    crawler.fetch_openweather_current.return_value = []
    monkeypatch.setattr(module, "WeatherBenchmarkCrawler",
                        Mock(return_value=crawler))
    monkeypatch.setattr(module.time, "sleep",
                        Mock(side_effect=[None, KeyboardInterrupt()]))
    assert main(["--loop", "--interval", "1"]) == 0
    assert crawler.fetch_open_meteo_current.call_count == 2

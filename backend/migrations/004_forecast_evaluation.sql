CREATE TABLE IF NOT EXISTS forecast_snapshots (
    device_id VARCHAR(50) NOT NULL,
    slot_at TIMESTAMPTZ NOT NULL,
    horizon_minutes SMALLINT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    reference_at TIMESTAMPTZ NOT NULL,
    valid_at TIMESTAMPTZ NOT NULL,
    temperature_c NUMERIC(5, 2),
    baseline_temperature_c NUMERIC(5, 2) NOT NULL,
    rain_probability NUMERIC(5, 4),
    rain_threshold NUMERIC(5, 4) NOT NULL,
    PRIMARY KEY (device_id, slot_at, horizon_minutes)
);

CREATE TABLE IF NOT EXISTS forecast_test_periods (
    device_id VARCHAR(50) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    CHECK (ends_at > starts_at),
    PRIMARY KEY (device_id, starts_at, ends_at)
);

-- Existing rows remain unchanged; nullable identities avoid deleting historical duplicates.
ALTER TABLE weather_measurements ADD COLUMN IF NOT EXISTS message_key VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_weather_message_key ON weather_measurements (message_key);

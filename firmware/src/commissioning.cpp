/** DHT11 D5, rain DO D7, BMP280 and OLED on D1/D2, relay D0.
 * Diagnostics, optional weather telemetry, and local rain relay control.
 */
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <Wire.h>
#include <DHT.h>
#include <Adafruit_SH110X.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include "board_wiring.h"
#include "bmp_quality.h"
#include "bmp280_sample.h"
#include "forecast_buzzer.h"
#include "rain_relay.h"
#if __has_include("weather_config.h")
#include "weather_config.h"
#else
#include "config.h.example"
#endif

#ifndef TOPIC_WEATHER_FORECAST
#define TOPIC_WEATHER_FORECAST "weather/" STATION_DEVICE_ID "/forecast"
#endif

namespace {
constexpr uint8_t relayPin = ESP8266_RELAY_GPIO, rainPin = 13, dhtPin = 14;
constexpr uint8_t rgbRedPin = 15, rgbGreenPin = 1, rgbBluePin = 2; // D8, TX, D4.
constexpr uint32_t sampleInterval = 5000, retryInterval = 5000;
constexpr uint32_t forecastTimeout = 90000;
#if defined(COMMISSIONING_RAIN_RELAY) && COMMISSIONING_RAIN_RELAY
constexpr bool actuationEnabled = true;
#else
constexpr bool actuationEnabled = false;
#endif
#if defined(COMMISSIONING_PUBLISH_WEATHER) && COMMISSIONING_PUBLISH_WEATHER
constexpr bool publishWeatherEnabled = true;
#else
constexpr bool publishWeatherEnabled = false;
#endif
station::RainRelay rainRelay;
station::ForecastBuzzer forecastBuzzer;
constexpr bool forecastAlertsEnabled = publishWeatherEnabled && actuationEnabled;
bool relayOn = false;
uint8_t bmpAddress = 0;
uint8_t bmpCalibration[24];
DHT dht(dhtPin, DHT11);
Adafruit_SH1106G display(128, 64, &Wire, -1);
WiFiClient network;
PubSubClient mqtt(network);
bool oledReady = false;
bool forecastReceived = false;
bool forecastThresholdReached = false;
uint32_t forecastReceivedAt = 0;
uint8_t forecastHorizon = 0, forecastPercent = 0;
uint32_t lastSample = 0, lastRetry = 0, sequence = 0;
char sampleTopic[128], statusTopic[128], commandTopic[128], replyTopic[128];
char clientId[64];
bool topicsReady = false;

bool readBmp(uint8_t address, uint8_t reg, uint8_t *data, uint8_t length) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0 ||
        Wire.requestFrom(address, length) != length) return false;
    for (uint8_t i = 0; i < length; ++i) data[i] = Wire.read();
    return true;
}

bool writeBmp(uint8_t address, uint8_t reg, uint8_t value) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

void initializeBmp() {
    for (uint8_t address : {uint8_t(0x76), uint8_t(0x77)}) {
        uint8_t id = 0, status = 0, calibrationCheck[24];
        if (!readBmp(address, 0xD0, &id, 1) || id != 0x58 ||
            !readBmp(address, 0xF3, &status, 1) || (status & 1) ||
            !readBmp(address, 0x88, bmpCalibration, sizeof(bmpCalibration)) ||
            !readBmp(address, 0x88, calibrationCheck, sizeof(calibrationCheck)) ||
            memcmp(bmpCalibration, calibrationCheck, sizeof(bmpCalibration)) != 0) continue;
        // Enter sleep before setting the filter and standby time. Normal
        // sampling then uses temperature x2 and pressure x16.
        if (!writeBmp(address, 0xF4, 0x00)) continue;
        delay(50); // Allow an in-flight measurement to finish.
        if (!writeBmp(address, 0xF5, 0x88) || !writeBmp(address, 0xF4, 0x57)) continue;
        bmpAddress = address;
        return;
    }
}

const char *readPressure(float &pressure) {
    if (!bmpAddress) {
        initializeBmp();
        return bmpAddress ? "starting" : "not_ready";
    }
    uint8_t control = 0, raw[6] = {};
    const bool readOk = readBmp(bmpAddress, 0xF4, &control, 1) &&
                        readBmp(bmpAddress, 0xF7, raw, sizeof(raw));
    const uint32_t adcPressure = (uint32_t(raw[0]) << 12) | (uint32_t(raw[1]) << 4) | (raw[2] >> 4);
    const uint32_t adcTemperature = (uint32_t(raw[3]) << 12) | (uint32_t(raw[4]) << 4) | (raw[5] >> 4);
    const char *issue = station::bmpRawIssue(readOk, adcTemperature, adcPressure, control);
    if (issue || control != 0x57) {
        bmpAddress = 0;
        return issue ? issue : "bmp_configuration_changed";
    }
    if (!station::compensateBmp280(bmpCalibration, adcTemperature, adcPressure, pressure)) {
        bmpAddress = 0;
        return "bmp_compensation_invalid";
    }
    return "valid";
}

void updateRelay() {
    if (!actuationEnabled) return;
    const uint32_t now = millis();
    const bool wet = digitalRead(rainPin) == LOW;
    const bool rainOn = rainRelay.update(wet, now);
    if (wet || rainOn) forecastBuzzer.cancel();
    const bool next = rainOn || forecastBuzzer.buzzerOn(now);
    if (next == relayOn) return;
    relayOn = next;
    digitalWrite(relayPin, relayOn ? RELAY_ACTIVE_LEVEL : !RELAY_ACTIVE_LEVEL);
}

void updateIndicators() {
    const bool wet = digitalRead(rainPin) == LOW;
    const bool freshForecast = mqtt.connected() && forecastReceived &&
        millis() - forecastReceivedAt < forecastTimeout;
    digitalWrite(rgbRedPin, wet ? HIGH : LOW);
    digitalWrite(rgbBluePin, !wet && freshForecast && forecastThresholdReached ? HIGH : LOW);
    digitalWrite(rgbGreenPin, !wet && freshForecast && !forecastThresholdReached ? HIGH : LOW);
}

bool makeTopic(char *target, size_t size, const char *suffix) {
    const int length = snprintf(target, size, "commissioning/%s/%s", STATION_DEVICE_ID, suffix);
    return length > 0 && static_cast<size_t>(length) < size;
}

void receiveForecastAlert(const byte *payload, unsigned int length) {
    StaticJsonDocument<384> message;
    if (deserializeJson(message, payload, length)) return;
    if (strcmp(message["type"] | "", "rain_warning") != 0 ||
        strcmp(message["device_id"] | "", STATION_DEVICE_ID) != 0 ||
        !message["action"]["buzzer"].is<bool>() ||
        !message["action"]["buzzer"].as<bool>()) return;
    if (relayOn || digitalRead(rainPin) == LOW) return;
    forecastBuzzer.start(millis());
}

void receiveForecast(const byte *payload, unsigned int length) {
    StaticJsonDocument<192> message;
    if (deserializeJson(message, payload, length) ||
        strcmp(message["type"] | "", "rain_forecast") != 0 ||
        strcmp(message["device_id"] | "", STATION_DEVICE_ID) != 0 ||
        !message["horizon_minutes"].is<int>() ||
        !message["probability_pct"].is<int>() ||
        !message["threshold_reached"].is<bool>()) return;
    const int horizon = message["horizon_minutes"].as<int>();
    const int percent = message["probability_pct"].as<int>();
    if ((horizon != 10 && horizon != 30 && horizon != 60) || percent < 0 || percent > 100) return;
    forecastHorizon = horizon;
    forecastPercent = percent;
    forecastThresholdReached = message["threshold_reached"].as<bool>();
    forecastReceivedAt = millis();
    forecastReceived = true;
}

void command(char *topic, byte *payload, unsigned int length) {
    if (publishWeatherEnabled && strcmp(topic, TOPIC_WEATHER_FORECAST) == 0) {
        receiveForecast(payload, length);
        return;
    }
    if (forecastAlertsEnabled && strcmp(topic, TOPIC_WEATHER_ALERT) == 0) {
        receiveForecastAlert(payload, length);
        return;
    }
    if (strcmp(topic, commandTopic) != 0) return;
    StaticJsonDocument<256> request;
    if (deserializeJson(request, static_cast<const byte *>(payload), length)) return;
    // The commissioning command topic is used only for ping.
    if (!request["command"].is<const char *>() ||
        strcmp(request["command"].as<const char *>(), "ping") != 0 ||
        !request["request_id"].is<const char *>()) return;
    const char *id = request["request_id"];
    if (!*id || strlen(id) > 48) return;
    StaticJsonDocument<256> reply;
    reply["device_id"] = STATION_DEVICE_ID;
    reply["request_id"] = id;
    reply["event"] = "pong";
    reply["uptime_ms"] = millis();
    reply["actuation_enabled"] = actuationEnabled;
    char buffer[384];
    serializeJson(reply, buffer, sizeof(buffer));
    mqtt.publish(replyTopic, buffer, false);
}

void connect() {
    if (!topicsReady || WiFi.status() != WL_CONNECTED) return;
    if (!mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD, statusTopic, 1, true, "offline")) {
        return;
    }
    if (!mqtt.subscribe(commandTopic, 1) ||
        (forecastAlertsEnabled && !mqtt.subscribe(TOPIC_WEATHER_ALERT, 1)) ||
        (publishWeatherEnabled && !mqtt.subscribe(TOPIC_WEATHER_FORECAST, 0))) {
        mqtt.disconnect();
        return;
    }
    mqtt.publish(statusTopic, "online", true);
}

void publishWeather(float temperature, float humidity, float pressure, bool raining) {
    StaticJsonDocument<256> message;
    message["device_id"] = STATION_DEVICE_ID;
    message["temperature"] = temperature;
    message["humidity"] = humidity;
    message["pressure"] = pressure;
    message["rain_detected"] = raining ? 1 : 0;
    // The optional rain_raw field is reserved for a measured analog value.
    char buffer[256];
    if (message.overflowed() || measureJson(message) >= sizeof(buffer)) return;
    serializeJson(message, buffer, sizeof(buffer));
    mqtt.publish(TOPIC_WEATHER_DATA, buffer, false);
}

void sample() {
    const float temperature = dht.readTemperature();
    const float humidity = dht.readHumidity();
    const bool dhtOk = isfinite(temperature) && isfinite(humidity) &&
        temperature >= -40 && temperature <= 85 && humidity >= 0 && humidity <= 100;
    const int rainLevel = digitalRead(rainPin);
    float pressureHpa = NAN;
    const char *pressureStatus = readPressure(pressureHpa);
    const bool pressureValid = isfinite(pressureHpa);
    StaticJsonDocument<768> doc;
    doc["schema"] = "commissioning.v1";
    doc["device_id"] = STATION_DEVICE_ID;
    doc["sequence"] = ++sequence;
    doc["uptime_ms"] = millis();
    doc["temperature_source"] = "DHT11";
    doc["humidity_source"] = "DHT11";
    doc["dht_valid"] = dhtOk;
    doc["temperature_c"] = nullptr;
    doc["humidity_pct"] = nullptr;
    if (dhtOk) {
        doc["temperature_c"] = temperature;
        doc["humidity_pct"] = humidity;
    }
    doc["pressure_hpa"] = nullptr;
    if (pressureValid) doc["pressure_hpa"] = pressureHpa;
    doc["pressure_source"] = "BMP280";
    doc["pressure_status"] = pressureStatus;
    doc["rain_source"] = "DO";
    doc["rain_do_level"] = rainLevel;
    doc["rain_detected"] = rainLevel == LOW;
    // DO is a logic level, not a measured ADC value. No rain_raw field.
    doc["actuation_enabled"] = actuationEnabled;
    doc["relay_command"] = relayOn ? "on" : "off";
    doc["wifi_connected"] = WiFi.status() == WL_CONNECTED;
    doc["mqtt_connected"] = mqtt.connected();
    char buffer[896];
    if (!doc.overflowed() && measureJson(doc) < sizeof(buffer)) {
        serializeJson(doc, buffer, sizeof(buffer));
        if (mqtt.connected()) mqtt.publish(sampleTopic, buffer, false);
    }
    if (publishWeatherEnabled && mqtt.connected() && dhtOk && pressureValid)
        publishWeather(temperature, humidity, pressureHpa, rainLevel == LOW);
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextWrap(false);
    display.setTextSize(1);
    display.fillRect(0, 0, 128, 12, SH110X_WHITE);
    display.setTextColor(SH110X_BLACK);
    display.setCursor(4, 2);
    display.print("LOCAL WEATHER");
    display.setCursor(mqtt.connected() ? 91 : 85, 2);
    display.print(mqtt.connected() ? "ONLINE" : "OFFLINE");

    display.setTextColor(SH110X_WHITE);
    display.setTextSize(2);
    display.setCursor(2, 18);
    if (dhtOk) display.printf("%.1fC", temperature);
    else display.print("--.-C");

    display.setTextSize(1);
    display.setCursor(78, 18);
    if (dhtOk) display.printf("RH %.0f%%", humidity);
    else display.print("RH --%");
    display.setCursor(78, 30);
    if (pressureValid) display.printf("P %.1f", pressureHpa);
    else display.print("P ----");

    display.drawFastHLine(0, 42, 128, SH110X_WHITE);
    if (rainLevel == LOW) {
        display.fillRect(0, 45, 128, 10, SH110X_WHITE);
        display.setTextColor(SH110X_BLACK);
    }
    display.setCursor(35, 46);
    display.print(rainLevel == LOW ? "RAIN: WET" : "RAIN: DRY");
    display.setTextColor(SH110X_WHITE);

    display.setCursor(3, 56);
    if (mqtt.connected() && forecastReceived &&
        millis() - forecastReceivedAt < forecastTimeout)
        display.printf("RAIN FCST +%uM: %u%%", forecastHorizon, forecastPercent);
    else display.print("RAIN FCST: WAITING");
    display.display();
}
} // namespace

void setup() {
    digitalWrite(rgbRedPin, LOW);
    pinMode(rgbRedPin, OUTPUT);
    digitalWrite(rgbGreenPin, LOW);
    pinMode(rgbGreenPin, OUTPUT);
    digitalWrite(rgbBluePin, LOW);
    pinMode(rgbBluePin, OUTPUT);
    digitalWrite(relayPin, !RELAY_ACTIVE_LEVEL);
    pinMode(relayPin, OUTPUT);
    pinMode(rainPin, INPUT); // D7 is never a status LED in this environment.
    dht.begin();
    Wire.begin(4, 5);
    Wire.setClock(100000);
    for (uint8_t address : {uint8_t(0x3C), uint8_t(0x3D)}) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0 && display.begin(address, true)) {
            oledReady = true;
            break;
        }
    }
    topicsReady = makeTopic(sampleTopic, sizeof(sampleTopic), "sample") &&
        makeTopic(statusTopic, sizeof(statusTopic), "status") &&
        makeTopic(commandTopic, sizeof(commandTopic), "command") &&
        makeTopic(replyTopic, sizeof(replyTopic), "reply");
    snprintf(clientId, sizeof(clientId), "commission-%06x", ESP.getChipId());
    mqtt.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqtt.setCallback(command);
    mqtt.setSocketTimeout(1);
    if (!mqtt.setBufferSize(1024)) topicsReady = false;
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
    updateRelay();
    updateIndicators();
    // Defer synchronous I/O during both the pulses and their short gaps.
    if (relayOn || forecastBuzzer.active(millis())) {
        yield();
        return;
    }
    if (mqtt.connected()) mqtt.loop();
    else if (millis() - lastRetry >= retryInterval) {
        lastRetry = millis();
        connect();
    }
    // MQTT can start a pattern in its callback.
    if (forecastBuzzer.active(millis())) return;
    if (millis() - lastSample >= sampleInterval) {
        lastSample = millis();
        sample();
    }
    yield();
}

/** Weather station: NodeMCU + BMP280 + DHT11 + rain AO + SH1106. */
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <PubSubClient.h>
#if defined(ESP8266)
#include <ESP8266WiFi.h>
#else
#include <WiFi.h>
#endif

#if __has_include("weather_config.h")
#include "weather_config.h"
#else
#include "config.h.example"
#endif
#include "station_logic.h"
#include "bmp_quality.h"

static_assert(SAMPLING_INTERVAL_MS >= 2000, "DHT11 requires a slow sample interval");
static_assert(RELAY_ON_TIME_MS <= ALERT_DURATION_MS, "Relay duration exceeds alert duration");
static_assert(LED_BLINK_INTERVAL_MS > 0, "LED blink interval must be positive");

Adafruit_SH1106G display(128, 64, &Wire, -1);
Adafruit_BMP280 bmp;
DHT dht(PIN_DHT, DHT11);
WiFiClient espClient;
PubSubClient mqttClient(espClient);
station::MovingAverage<SENSOR_FILTER_WINDOW> sensorFilter;
station::Reading latestReading;
station::AlertState alert;
bool bmpReady = false;
uint8_t activeBmpAddress = 0;
bool displayReady = false;
bool sensorDataReady = false;
unsigned long lastSampleTime = 0;
unsigned long lastMqttRetryTime = 0;
char alertMessage[64] = "CANH BAO MUA!";

bool i2cPresent(uint8_t address) {
    Wire.beginTransmission(address);
    return Wire.endTransmission() == 0;
}

bool initializeBMP() {
    const uint8_t addresses[] = {BMP_I2C_ADDRESS, BMP_I2C_FALLBACK_ADDRESS};
    for (uint8_t address : addresses) {
        if (i2cPresent(address) && bmp.begin(address)) {
            activeBmpAddress = address;
            Serial.printf("[BMP280] I2C 0x%02X OK\n", address);
            return true;
        }
    }
    Serial.println("[BMP280] Khong tim thay; thu lai o chu ky do tiep theo.");
    return false;
}

bool readBmpBlock(uint8_t reg, uint8_t *data, uint8_t length) {
    Wire.beginTransmission(activeBmpAddress);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(activeBmpAddress, length) != length) return false;
    for (uint8_t i = 0; i < length; ++i) data[i] = Wire.read();
    return true;
}

const char *bmpRawProblem() {
    uint8_t raw[6] = {}, ctrl = 0;
    const bool ok = readBmpBlock(0xF7, raw, sizeof(raw)) && readBmpBlock(0xF4, &ctrl, 1);
    const uint32_t pressureAdc = (uint32_t(raw[0]) << 12) | (uint32_t(raw[1]) << 4) | (raw[2] >> 4);
    const uint32_t temperatureAdc = (uint32_t(raw[3]) << 12) | (uint32_t(raw[4]) << 4) | (raw[5] >> 4);
    return station::bmpRawIssue(ok, temperatureAdc, pressureAdc, ctrl);
}

void updateOLED() {
    // begin() may fail to allocate its framebuffer when the station is low on RAM.
    if (!displayReady) return;
    display.clearDisplay();
    display.setCursor(0, 0);
    display.setTextSize(1);
    display.setTextColor(SH110X_WHITE);
    display.println(STATION_DEVICE_ID);
    display.drawLine(0, 10, 128, 10, SH110X_WHITE);
    display.setCursor(0, 15);
    if (sensorDataReady) {
        display.printf("Temp: %.1f C\n", latestReading.temperature);
        display.printf("Hum : %.1f %%\n", latestReading.humidity);
        display.printf("Pres: %.1f hPa\n", latestReading.pressure);
    } else {
        display.println("Cho/loi cam bien");
        display.printf("Rain AO: %d\n", latestReading.rainRaw);
    }
    display.setCursor(0, 45);
    if (alert.active()) {
        display.println(alertMessage);
    } else if (!sensorDataReady) {
        display.println("Kiem tra BMP/DHT");
    } else {
        display.println(mqttClient.connected() ? "MQTT: online" : "MQTT: offline");
    }
    display.display();
}

void handleAlertSignals() {
    const bool wasActive = alert.active();
    const uint32_t now = millis();
    alert.update(now, ALERT_DURATION_MS);
    digitalWrite(PIN_BUZZER, alert.buzzerOn(now, RELAY_ON_TIME_MS)
        ? RELAY_ACTIVE_LEVEL : !RELAY_ACTIVE_LEVEL);
    digitalWrite(PIN_STATUS_LED, alert.ledOn(now, LED_BLINK_INTERVAL_MS) ? HIGH : LOW);
    if (wasActive && !alert.active()) {
        Serial.println("[ALERT] Ket thuc chu ky canh bao.");
        updateOLED();
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    if (strcmp(topic, TOPIC_WEATHER_ALERT) != 0) return;
    StaticJsonDocument<384> doc;
    // Parse with an explicit length; no variable-sized stack buffer.
    if (deserializeJson(doc, static_cast<const byte*>(payload), length)) {
        Serial.println("[MQTT] Canh bao JSON khong hop le.");
        return;
    }
    const char* type = doc["type"] | "";
    const char* device = doc["device_id"] | STATION_DEVICE_ID;
    if (strcmp(type, "rain_warning") != 0 || strcmp(device, STATION_DEVICE_ID) != 0) return;
    const float probability = doc["probability"] | 0.0f;
    if (!isfinite(probability) || probability < 0 || probability > 1) return;
    if (alert.start(millis(), doc["action"]["buzzer"] | true,
                    doc["action"]["led_blink"] | true)) {
        snprintf(alertMessage, sizeof(alertMessage), "%s",
            doc["action"]["oled_message"] | "CANH BAO MUA!");
        handleAlertSignals();
        updateOLED();
        Serial.printf("[ALERT] Xac suat mua: %.1f%%\n", probability * 100);
    }
}

void connectMQTT() {
    if (WiFi.status() != WL_CONNECTED) return;
    if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD,
                           TOPIC_WEATHER_STATUS, 1, true, "offline")) {
        mqttClient.publish(TOPIC_WEATHER_STATUS, "online", true);
        if (!mqttClient.subscribe(TOPIC_WEATHER_ALERT, 1)) {
            Serial.println("[MQTT] Subscribe that bai; thu ket noi lai.");
            mqttClient.disconnect();
        }
    } else {
        Serial.printf("[MQTT] Ket noi that bai, rc=%d\n", mqttClient.state());
    }
}

void sampleAndPublish() {
    if (!bmpReady) bmpReady = initializeBMP();
    const char *bmpIssue = bmpReady ? bmpRawProblem() : "bmp_not_ready";
    if (bmpIssue) Serial.printf("[BMP280] Mau khong hop le: %s\n", bmpIssue);
    station::Reading raw;
    raw.temperature = !bmpIssue ? bmp.readTemperature() : NAN;
    raw.pressure = !bmpIssue ? bmp.readPressure() / 100.0f : NAN;
    raw.humidity = dht.readHumidity();
    raw.rainRaw = analogRead(PIN_RAIN_ANALOG);
    Serial.printf("[SENSOR] T=%.2f H=%.2f P=%.2f AO=%d\n",
        raw.temperature, raw.humidity, raw.pressure, raw.rainRaw);
    if (!isfinite(raw.temperature) || !isfinite(raw.pressure)) bmpReady = false;
    sensorDataReady = sensorFilter.add(raw, latestReading);
    if (!sensorDataReady) {
        Serial.println("[SENSOR] Mau loi; xoa bo loc, khong gui du lieu cu.");
        updateOLED();
        return;
    }
    if (mqttClient.connected()) {
        StaticJsonDocument<384> doc;
        doc["device_id"] = STATION_DEVICE_ID;
        // Uptime is diagnostic only. Backend supplies the UTC receive timestamp.
        doc["timestamp_ms"] = millis();
        doc["temperature"] = latestReading.temperature;
        doc["humidity"] = latestReading.humidity;
        doc["pressure"] = latestReading.pressure;
        doc["rain_raw"] = latestReading.rainRaw;
        doc["rain_detected"] = station::rainDetected(latestReading.rainRaw,
            RAIN_ANALOG_THRESHOLD, RAIN_WET_IS_LOW) ? 1 : 0;
        char jsonBuffer[MQTT_BUFFER_SIZE];
        if (doc.overflowed() || measureJson(doc) >= sizeof(jsonBuffer)) {
            Serial.println("[MQTT] Payload qua lon; bo qua.");
        } else {
            serializeJson(doc, jsonBuffer, sizeof(jsonBuffer));
            // PubSubClient publishes at QoS 0. Do not replay telemetry on resubscribe.
            if (mqttClient.publish(TOPIC_WEATHER_DATA, jsonBuffer, false)) {
                Serial.printf("[MQTT PUB] %s\n", jsonBuffer);
            } else {
                Serial.println("[MQTT] Publish that bai.");
            }
        }
    }
    updateOLED();
}

void setup() {
    Serial.begin(SERIAL_BAUD_RATE);
    // Set the inactive level before enabling output, especially for LOW-trigger relays.
    digitalWrite(PIN_BUZZER, !RELAY_ACTIVE_LEVEL);
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);
    pinMode(PIN_STATUS_LED, OUTPUT);
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    Wire.setClock(I2C_CLOCK_HZ);
    const uint8_t oledAddresses[] = {OLED_I2C_ADDRESS, OLED_I2C_FALLBACK_ADDRESS};
    for (uint8_t address : oledAddresses) {
        if (i2cPresent(address) && display.begin(address, true)) {
            displayReady = true;
            Serial.printf("[OLED] SH1106 I2C 0x%02X OK\n", address);
            break;
        }
    }
    if (!displayReady) Serial.println("[OLED] Khong khoi tao duoc; tram van tiep tuc do.");
    dht.begin();
    bmpReady = initializeBMP();
    updateOLED();
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    mqttClient.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setSocketTimeout(MQTT_SOCKET_TIMEOUT_S);
    if (!mqttClient.setBufferSize(MQTT_BUFFER_SIZE)) {
        Serial.println("[MQTT] Khong du RAM cho MQTT buffer.");
    }
}

void loop() {
    handleAlertSignals();
    if (mqttClient.connected()) {
        mqttClient.loop();
    } else if (!alert.active() && millis() - lastMqttRetryTime >= MQTT_RETRY_INTERVAL_MS) {
        // A broker reconnect can block; defer it until the relay/LED alert has ended.
        lastMqttRetryTime = millis();
        connectMQTT();
    }
    handleAlertSignals();
    if (millis() - lastSampleTime >= SAMPLING_INTERVAL_MS) {
        lastSampleTime = millis();
        sampleAndPublish();
    }
    handleAlertSignals();
    yield();
}

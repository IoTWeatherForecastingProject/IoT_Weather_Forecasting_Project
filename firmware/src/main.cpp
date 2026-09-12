/**
 * ==============================================================================
 * DỰ ÁN: IOT LOCAL WEATHER MONITORING & SHORT-TERM FORECASTING
 * MODULE 1: FIRMWARE TRẠM ĐO IOT (ESP32 / ESP8266)
 * 
 * Phụ trách: TV1 (IoT + Backend Engineer)
 * Các tính năng:
 * - Đọc BME280 (Nhiệt độ, Độ ẩm, Áp suất) qua I2C
 * - Đọc Rain Sensor (Analog & Digital)
 * - Bộ lọc trung bình trượt (Moving Average Filter) 5 mẫu
 * - Non-blocking WiFi & MQTT Client Auto-reconnect
 * - Subscribe lệnh cảnh báo 2 chiều (bật còi Buzzer, nháy LED, OLED SSD1306)
 * ==============================================================================
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

#if defined(ESP8266)
  #include <ESP8266WiFi.h>
#else
  #include <WiFi.h>
#endif
#include <PubSubClient.h>

// Nạp cấu hình nội bộ nếu có, nếu chưa có thì dùng giá trị mặc định để biên dịch
#if __has_include("config.h")
  #include "config.h"
#else
  #include "config.h.example"
#endif

// --- Định nghĩa OLED Display ---
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// --- Khởi tạo Đối tượng ---
Adafruit_BME280 bme;
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// --- Cấu trúc Bộ lọc Trung bình trượt (Moving Average) ---
#define FILTER_WINDOW_SIZE 5
struct SensorBuffer {
    float temp[FILTER_WINDOW_SIZE];
    float hum[FILTER_WINDOW_SIZE];
    float press[FILTER_WINDOW_SIZE];
    int rain[FILTER_WINDOW_SIZE];
    int index = 0;
    int count = 0;
} sensorBuffer;

// --- Biến điều khiển thời gian Non-blocking ---
unsigned long lastSampleTime = 0;
unsigned long lastMqttRetryTime = 0;
unsigned long alertStartTime = 0;
bool isAlertActive = false;
int alertBlinkState = LOW;
unsigned long lastBlinkTime = 0;

// --- Khai báo nguyên mẫu hàm ---
void setupWiFi();
void connectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void readAndFilterSensors(float &outTemp, float &outHum, float &outPress, int &outRain);
void updateOLED(float temp, float hum, float press, const char* statusMsg);
void handleAlertSignals();

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[IoT Station] Dang khoi dong tram do thoi tiet...");

    // Cấu hình chân GPIO ngoại vi
    pinMode(PIN_BUZZER, OUTPUT);
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);
    digitalWrite(PIN_STATUS_LED, LOW);

    // Khởi tạo I2C
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

    // Khởi tạo màn hình OLED
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        Serial.println("[OLED] Khong tim thay man hinh SSD1306!");
    } else {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0, 10);
        display.println("IoT Weather Station");
        display.println("Connecting WiFi...");
        display.display();
    }

    // Khởi tạo cảm biến BME280
    if (!bme.begin(0x76, &Wire) && !bme.begin(0x77, &Wire)) {
        Serial.println("[BME280] Khong tim thay cam bien BME280! Kiem tra day I2C.");
    } else {
        Serial.println("[BME280] Cam bien khoi tao thanh cong.");
    }

    // Khởi tạo WiFi & MQTT
    setupWiFi();
    mqttClient.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqttClient.setCallback(mqttCallback);
}

void loop() {
    unsigned long currentMillis = millis();

    // Duy trì kết nối MQTT không chặn
    if (!mqttClient.connected()) {
        if (currentMillis - lastMqttRetryTime > 5000) {
            lastMqttRetryTime = currentMillis;
            connectMQTT();
        }
    } else {
        mqttClient.loop();
    }

    // Xử lý còi và đèn cảnh báo nếu có lệnh từ backend
    handleAlertSignals();

    // Chu kỳ đọc cảm biến và gửi MQTT (Non-blocking)
    if (currentMillis - lastSampleTime >= SAMPLING_INTERVAL_MS) {
        lastSampleTime = currentMillis;

        float temp = 0.0, hum = 0.0, press = 0.0;
        int rainRaw = 0;
        readAndFilterSensors(temp, hum, press, rainRaw);

        int rainDetected = (rainRaw < RAIN_ANALOG_THRESHOLD) ? 1 : 0;

        // Đóng gói JSON Payload
        StaticJsonDocument<256> doc;
        doc["device_id"] = MQTT_CLIENT_ID;
        doc["timestamp_ms"] = currentMillis;
        doc["temperature"] = serialized(String(temp, 2));
        doc["humidity"] = serialized(String(hum, 2));
        doc["pressure"] = serialized(String(press, 2));
        doc["rain_raw"] = rainRaw;
        doc["rain_detected"] = rainDetected;

        char jsonBuffer[256];
        serializeJson(doc, jsonBuffer);

        if (mqttClient.connected()) {
            mqttClient.publish(TOPIC_WEATHER_DATA, jsonBuffer, true);
            Serial.printf("[MQTT PUB] %s -> %s\n", TOPIC_WEATHER_DATA, jsonBuffer);
        }

        // Cập nhật OLED
        updateOLED(temp, hum, press, isAlertActive ? "CANH BAO MUA!" : "Hoat dong on dinh");
    }
}

void setupWiFi() {
    Serial.printf("[WiFi] Dang ket noi toi SSID: %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void connectMQTT() {
    if (WiFi.status() != WL_CONNECTED) {
        return;
    }
    Serial.println("[MQTT] Dang thu ket noi toi Broker...");
    if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD, TOPIC_WEATHER_STATUS, 1, true, "offline")) {
        Serial.println("[MQTT] Ket noi Broker thanh cong!");
        mqttClient.publish(TOPIC_WEATHER_STATUS, "online", true);
        mqttClient.subscribe(TOPIC_WEATHER_ALERT, 1);
        Serial.printf("[MQTT SUB] Da subscribe topic: %s\n", TOPIC_WEATHER_ALERT);
    } else {
        Serial.printf("[MQTT] That bai, rc=%d. Thu lai sau 5s.\n", mqttClient.state());
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    char message[length + 1];
    memcpy(message, payload, length);
    message[length] = '\0';
    Serial.printf("[MQTT RECV] Topic [%s]: %s\n", topic, message);

    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, message);
    if (error) {
        Serial.println("[MQTT RECV] Loi parse JSON canh bao!");
        return;
    }

    const char* type = doc["type"];
    if (type && strcmp(type, "rain_warning") == 0) {
        float prob = doc["probability"] | 0.0;
        Serial.printf("[ALERT] Kich hoat canh bao mua! Xac suat: %.2f%%\n", prob * 100.0);
        isAlertActive = true;
        alertStartTime = millis();
    }
}

void readAndFilterSensors(float &outTemp, float &outHum, float &outPress, int &outRain) {
    float rawTemp = bme.readTemperature();
    float rawHum = bme.readHumidity();
    float rawPress = bme.readPressure() / 100.0F; // Pa to hPa
    int rawRain = analogRead(PIN_RAIN_ANALOG);

    // Lưu vào bộ đệm trượt
    int idx = sensorBuffer.index;
    sensorBuffer.temp[idx] = rawTemp;
    sensorBuffer.hum[idx] = rawHum;
    sensorBuffer.press[idx] = rawPress;
    sensorBuffer.rain[idx] = rawRain;

    sensorBuffer.index = (idx + 1) % FILTER_WINDOW_SIZE;
    if (sensorBuffer.count < FILTER_WINDOW_SIZE) sensorBuffer.count++;

    // Tính trung bình
    float sumT = 0, sumH = 0, sumP = 0;
    long sumR = 0;
    for (int i = 0; i < sensorBuffer.count; i++) {
        sumT += sensorBuffer.temp[i];
        sumH += sensorBuffer.hum[i];
        sumP += sensorBuffer.press[i];
        sumR += sensorBuffer.rain[i];
    }
    outTemp = sumT / sensorBuffer.count;
    outHum = sumH / sensorBuffer.count;
    outPress = sumP / sensorBuffer.count;
    outRain = sumR / sensorBuffer.count;
}

void updateOLED(float temp, float hum, float press, const char* statusMsg) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.setTextSize(1);
    display.println("WEATHER STATION - S01");
    display.drawLine(0, 10, 128, 10, SSD1306_WHITE);

    display.setCursor(0, 15);
    display.printf("Temp: %.1f C\n", temp);
    display.printf("Hum : %.1f %%\n", hum);
    display.printf("Pres: %.1f hPa\n", press);

    display.setCursor(0, 48);
    display.println(statusMsg);
    display.display();
}

void handleAlertSignals() {
    if (!isAlertActive) {
        digitalWrite(PIN_BUZZER, LOW);
        digitalWrite(PIN_STATUS_LED, LOW);
        return;
    }

    unsigned long currentMillis = millis();

    // Cảnh báo kêu ngắt quãng trong 10 giây rồi tự tắt
    if (currentMillis - alertStartTime > 10000) {
        isAlertActive = false;
        digitalWrite(PIN_BUZZER, LOW);
        digitalWrite(PIN_STATUS_LED, LOW);
        Serial.println("[ALERT] Ket thuc chu ky canh bao.");
        return;
    }

    // Nháy đèn và kêu bíp ngắt quãng mỗi 250ms
    if (currentMillis - lastBlinkTime >= 250) {
        lastBlinkTime = currentMillis;
        alertBlinkState = !alertBlinkState;
        digitalWrite(PIN_STATUS_LED, alertBlinkState);
        digitalWrite(PIN_BUZZER, alertBlinkState);
    }
}


/** DHT11 ambient temperature/humidity plus I2C BMP280 pressure diagnosis.
 * OLED shares SDA=D2/GPIO4 and SCL=D1/GPIO5. Configured relay stays LOW.
 * CSB=3V3, SDO=GND select I2C address 0x76 on the Bosch device.
 * No WiFi/MQTT, rain AO read, or automatic actuation.
 */
#include <Arduino.h>
#include "board_wiring.h"
#include "bmp_quality.h"
#include <Wire.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <DHT.h>
#include <math.h>

namespace {
Adafruit_SH1106G display(128, 64, &Wire, -1);
Adafruit_BMP280 bmp;
DHT dht(14, DHT11); // D5; ambient temperature/humidity source.
bool oledReady = false;
bool bmpReady = false;
uint8_t pressureAddress = 0;
uint8_t chipId = 0;
uint32_t lastSample = 0;
struct RawSnapshot {
    bool ok = false;
    uint32_t temperatureAdc = 0;
    uint32_t pressureAdc = 0;
    uint8_t ctrlMeas = 0;
};

bool plausible(float temperature, float pressure) {
    return isfinite(temperature) && isfinite(pressure) && temperature >= -40 &&
           temperature <= 85 && pressure >= 300 && pressure <= 1100;
}

bool readBlock(uint8_t address, uint8_t reg, uint8_t *data, uint8_t length) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(address, length) != length) return false;
    for (uint8_t i = 0; i < length; ++i) data[i] = Wire.read();
    return true;
}

RawSnapshot reportRegisters(const char *phase) {
    uint8_t calibration[24] = {}, raw[6] = {}, control[3] = {};
    const bool calibrationOk = readBlock(pressureAddress, 0x88, calibration, sizeof(calibration));
    const bool rawOk = readBlock(pressureAddress, 0xF7, raw, sizeof(raw));
    const bool controlOk = readBlock(pressureAddress, 0xF3, control, sizeof(control));
    char calibrationHex[49] = {}, rawHex[13] = {};
    for (uint8_t i = 0; i < sizeof(calibration); ++i) snprintf(calibrationHex + i * 2, 3, "%02X", calibration[i]);
    for (uint8_t i = 0; i < sizeof(raw); ++i) snprintf(rawHex + i * 2, 3, "%02X", raw[i]);
    Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"registers\",\"phase\":\"%s\",\"calibration_ok\":%s,\"calibration_hex\":\"%s\",\"raw_ok\":%s,\"raw_hex\":\"%s\",\"control_ok\":%s,\"status\":%u,\"ctrl_meas\":%u,\"config\":%u}\n",
                  phase, calibrationOk ? "true" : "false", calibrationHex,
                  rawOk ? "true" : "false", rawHex, controlOk ? "true" : "false",
                  control[0], control[1], control[2]);
    RawSnapshot result;
    result.ok = calibrationOk && rawOk && controlOk;
    result.pressureAdc = (uint32_t(raw[0]) << 12) | (uint32_t(raw[1]) << 4) | (raw[2] >> 4);
    result.temperatureAdc = (uint32_t(raw[3]) << 12) | (uint32_t(raw[4]) << 4) | (raw[5] >> 4);
    result.ctrlMeas = control[1];
    return result;
}

bool readRegister(uint8_t address, uint8_t reg, uint8_t &value) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(address, static_cast<uint8_t>(1)) != 1) return false;
    value = Wire.read();
    return true;
}

bool writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

bool waitStatusClear(uint8_t mask, uint32_t timeoutMs) {
    const uint32_t started = millis();
    do {
        uint8_t status = 0;
        if (!readRegister(pressureAddress, 0xF3, status)) return false;
        if ((status & mask) == 0) return true;
        delay(2);
    } while (millis() - started < timeoutMs);
    return false;
}

void identifyPressureModule() {
    for (uint8_t address : {uint8_t(0x76), uint8_t(0x77)}) {
        uint8_t id = 0;
        if (!readRegister(address, 0xD0, id)) continue;
        pressureAddress = address;
        chipId = id;
        const char *kind = id == 0x58 ? "BMP280" : id == 0x60 ? "BME280" : "UNKNOWN";
        Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"identity\",\"address\":%u,\"chip_id\":%u,\"kind\":\"%s\",\"relay_level\":\"LOW\"}\n",
                      address, id, kind);
        if (id == 0x58) {
            reportRegisters("before_reset");
            const bool resetWritten = writeRegister(address, 0xE0, 0xB6);
            delay(5);
            const bool nvmReady = resetWritten && waitStatusClear(0x01, 100);
            Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"soft_reset\",\"write_ok\":%s,\"nvm_ready\":%s}\n",
                          resetWritten ? "true" : "false", nvmReady ? "true" : "false");
            if (!nvmReady) return;
            reportRegisters("after_reset");
            bmpReady = bmp.begin(address, 0x58);
            uint8_t directId = 0;
            const bool directReadOk = readRegister(address, 0xD0, directId);
            Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"bmp_init\",\"ok\":%s,\"address\":%u,\"library_chip_id\":%u,\"direct_read_ok\":%s,\"direct_chip_id\":%u}\n",
                          bmpReady ? "true" : "false", address, static_cast<unsigned>(bmp.sensorID()),
                          directReadOk ? "true" : "false", directId);
            if (bmpReady) {
                bmp.setSampling(Adafruit_BMP280::MODE_SLEEP, Adafruit_BMP280::SAMPLING_X1,
                                Adafruit_BMP280::SAMPLING_X1, Adafruit_BMP280::FILTER_OFF,
                                Adafruit_BMP280::STANDBY_MS_500);
                const bool slept = waitStatusClear(0x08, 200);
                bmp.setSampling(Adafruit_BMP280::MODE_FORCED, Adafruit_BMP280::SAMPLING_X1,
                                Adafruit_BMP280::SAMPLING_X1, Adafruit_BMP280::FILTER_OFF,
                                Adafruit_BMP280::STANDBY_MS_500);
                delay(20); // x1 temperature/pressure conversion maximum is 6.4 ms.
                const bool forcedComplete = waitStatusClear(0x08, 200);
                Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"mode_probe\",\"sleep_completed\":%s,\"forced_completed\":%s}\n",
                              slept ? "true" : "false", forcedComplete ? "true" : "false");
                reportRegisters("forced_x1");
                // Forced measurement returns to sleep; configure the next mode there.
                bmp.setSampling(Adafruit_BMP280::MODE_NORMAL, Adafruit_BMP280::SAMPLING_X2,
                                Adafruit_BMP280::SAMPLING_X16, Adafruit_BMP280::FILTER_X4,
                                Adafruit_BMP280::STANDBY_MS_500);
                delay(100);
                reportRegisters("normal_t2_p16");
            }
        }
        return;
    }
    Serial.println("{\"test\":\"PRESSURE\",\"event\":\"not_found\",\"relay_level\":\"LOW\"}");
}

void draw(float bmpTemperature, float pressure, float temperature, float humidity,
          bool rawReady, bool pressureOk) {
    if (!oledReady) return;
    display.clearDisplay();
    display.setTextColor(SH110X_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("TV1 SENSOR CHECK");
    if (isfinite(temperature) && isfinite(humidity)) {
        display.printf("DHT T: %.1f C\n", temperature);
        display.printf("DHT RH: %.1f %%\n", humidity);
    } else {
        display.println("DHT: NO READING");
    }
    if (pressureOk) {
        display.printf("BMP P: %.1f hPa\n", pressure);
    } else {
        display.println(bmpReady ? "BMP P: INVALID" : "BMP: NOT READY");
    }
    if (rawReady && isfinite(bmpTemperature)) display.printf("BMP int T: %.1f C\n", bmpTemperature);
    else display.println("BMP raw: INVALID");
    display.println("Relay cmd: OFF");
    display.display();
}
} // namespace

void setup() {
    digitalWrite(ESP8266_RELAY_GPIO, LOW);
    pinMode(ESP8266_RELAY_GPIO, OUTPUT);
    Serial.begin(115200);
    dht.begin();
    Wire.begin(4, 5);
    Wire.setClock(100000);
    delay(200);

    for (uint8_t address : {uint8_t(0x3C), uint8_t(0x3D)}) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0 && display.begin(address, true)) {
            oledReady = true;
            Serial.printf("{\"test\":\"PRESSURE\",\"event\":\"oled\",\"address\":%u,\"ok\":true}\n", address);
            break;
        }
    }
    Serial.printf("PRESSURE_CHECK: SDA=D2 SCL=D1 CSB=3V3 SDO=GND relay=GPIO%u/LOW\n", ESP8266_RELAY_GPIO);
    identifyPressureModule();
}

void loop() {
    const uint32_t now = millis();
    if (now - lastSample < 2500) {
        yield();
        return;
    }
    lastSample = now;
    // A transient init failure must not leave the diagnostic stuck until reboot.
    if (!bmpReady && (chipId == 0 || chipId == 0x58)) identifyPressureModule();
    const float temperature = dht.readTemperature();
    const float humidity = dht.readHumidity();
    float bmpTemperature = NAN;
    float pressure = NAN;
    RawSnapshot raw;
    if (bmpReady) {
        bmpTemperature = bmp.readTemperature();
        pressure = bmp.readPressure() / 100.0F;
        raw = reportRegisters("sample");
    }
    const char *rawIssue = station::bmpRawIssue(raw.ok, raw.temperatureAdc, raw.pressureAdc, raw.ctrlMeas);
    char temperatureJson[24] = "null";
    char humidityJson[24] = "null";
    char bmpTemperatureJson[24] = "null";
    char pressureJson[24] = "null";
    if (isfinite(temperature)) snprintf(temperatureJson, sizeof(temperatureJson), "%.2f", temperature);
    if (isfinite(humidity)) snprintf(humidityJson, sizeof(humidityJson), "%.2f", humidity);
    if (isfinite(bmpTemperature)) snprintf(bmpTemperatureJson, sizeof(bmpTemperatureJson), "%.2f", bmpTemperature);
    if (isfinite(pressure)) snprintf(pressureJson, sizeof(pressureJson), "%.2f", pressure);
    const bool dhtOk = isfinite(temperature) && isfinite(humidity) && humidity >= 0 && humidity <= 100;
    const bool pressureOk = bmpReady && !rawIssue && plausible(bmpTemperature, pressure);
    const char *pressureStatus = !bmpReady ? "bmp_not_ready" :
        rawIssue ? rawIssue :
        (!isfinite(bmpTemperature) || bmpTemperature < -40 || bmpTemperature > 85) ?
        "bmp_internal_temperature_invalid" : pressureOk ? "valid" : "bmp_pressure_invalid";
    draw(bmpTemperature, pressure, temperature, humidity, !rawIssue, pressureOk);
    Serial.printf("{\"test\":\"SENSORS\",\"event\":\"sample\",\"temperature_source\":\"DHT11\",\"humidity_source\":\"DHT11\",\"pressure_source\":\"BMP280\",\"address\":%u,\"chip_id\":%u,\"dht_read_ok\":%s,\"temperature_c\":%s,\"humidity_pct\":%s,\"bmp_ready\":%s,\"bmp_temperature_c\":%s,\"pressure_hpa\":%s,\"pressure_candidate_hpa\":%s,\"bmp_raw_ok\":%s,\"bmp_adc_temperature\":%lu,\"bmp_adc_pressure\":%lu,\"bmp_ctrl_meas\":%u,\"pressure_valid\":%s,\"pressure_status\":\"%s\",\"oled_ready\":%s,\"relay_level\":\"LOW\",\"relay_gpio\":%u,\"relay_observed_level\":\"%s\",\"uptime_ms\":%lu}\n",
                  pressureAddress, chipId, dhtOk ? "true" : "false", temperatureJson, humidityJson,
                  bmpReady ? "true" : "false", bmpTemperatureJson,
                  pressureOk ? pressureJson : "null", pressureJson,
                  raw.ok ? "true" : "false", static_cast<unsigned long>(raw.temperatureAdc),
                  static_cast<unsigned long>(raw.pressureAdc), raw.ctrlMeas,
                  pressureOk ? "true" : "false", pressureStatus,
                  oledReady ? "true" : "false", ESP8266_RELAY_GPIO,
                  digitalRead(ESP8266_RELAY_GPIO) ? "HIGH" : "LOW", static_cast<unsigned long>(now));
    yield();
}

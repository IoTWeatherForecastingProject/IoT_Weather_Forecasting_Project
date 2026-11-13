/** OLED-only UART diagnosis: SDA D2/GPIO4, SCL D1/GPIO5, power 3V3.
 * H-trigger relay uses board_wiring.h and is held LOW. No WiFi/MQTT.
 * I2C ACK/driver allocation do not identify the controller or prove visible output.
 */
#include <Arduino.h>
#include "board_wiring.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

Adafruit_SH1106G display(128, 64, &Wire, -1);
bool ready = false;
uint8_t address = 0;
uint32_t lastDraw = 0;
uint32_t frame = 0;

void setup() {
    digitalWrite(ESP8266_RELAY_GPIO, LOW);
    pinMode(ESP8266_RELAY_GPIO, OUTPUT);
    Serial.begin(115200);
    Wire.begin(4, 5);
    Wire.setClock(100000);
    delay(200);
    Serial.printf("OLED_CHECK: SDA=D2 SCL=D1 VCC=3V3 relay=GPIO%u/LOW driver=SH1106\n", ESP8266_RELAY_GPIO);
    for (uint8_t candidate = 1; candidate < 127; ++candidate) {
        Wire.beginTransmission(candidate);
        const uint8_t result = Wire.endTransmission();
        if (result == 0) {
            Serial.printf("{\"test\":\"OLED\",\"event\":\"i2c_ack\",\"address\":%u}\n", candidate);
            if (candidate == 0x3C || candidate == 0x3D) {
                if (!address) address = candidate;
            }
        }
        yield();
    }
    ready = address && display.begin(address, true);
    Wire.setClock(100000);
    Serial.printf("{\"test\":\"OLED\",\"event\":\"init\",\"driver_ready\":%s,\"address\":%u,\"relay_level\":\"LOW\"}\n",
                  ready ? "true" : "false", address);
}

void loop() {
    const uint32_t now = millis();
    if (now - lastDraw >= 1000) {
        lastDraw = now;
        if (ready) {
            display.clearDisplay();
            display.setTextColor(SH110X_WHITE);
            display.setTextSize(1);
            display.drawRect(0, 0, 128, 64, SH110X_WHITE);
            display.setCursor(8, 7);
            display.print("TV1 OLED TEST");
            display.setCursor(8, 21);
            display.printf("I2C: 0x%02X", address);
            display.setCursor(8, 35);
            display.printf("Count: %lu", static_cast<unsigned long>(++frame));
            display.drawLine(8, 52, 119, 52, SH110X_WHITE);
            display.fillRect(8 + (frame % 108), 55, 4, 4, SH110X_WHITE);
            display.display();
        }
        Serial.printf("{\"test\":\"OLED\",\"event\":\"frame\",\"driver_ready\":%s,\"frame\":%lu,\"uptime_ms\":%lu,\"relay_level\":\"LOW\"}\n",
                      ready ? "true" : "false", static_cast<unsigned long>(frame), static_cast<unsigned long>(now));
    }
    yield();
}

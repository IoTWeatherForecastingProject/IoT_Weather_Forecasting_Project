/** Rain comparator-only test: VCC=3V3, DO=D7/GPIO13; AO disconnected.
 * OLED SDA=D2 SCL=D1. Relay from board_wiring.h held LOW.
 */
#include <Arduino.h>
#include "board_wiring.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

Adafruit_SH1106G display(128, 64, &Wire, -1);
bool displayReady = false;
uint32_t lastSample = 0;
uint32_t transitions = 0;
int previousLevel = -1;

void setup() {
    digitalWrite(ESP8266_RELAY_GPIO, LOW);
    pinMode(ESP8266_RELAY_GPIO, OUTPUT);
    pinMode(13, INPUT); // Observe comparator output; do not drive the signal.
    Serial.begin(115200);
    Wire.begin(4, 5);
    Wire.setClock(100000);
    for (uint8_t address : {uint8_t(0x3C), uint8_t(0x3D)}) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0 && display.begin(address, true)) {
            displayReady = true;
            break;
        }
    }
    Serial.printf("RAIN_DO_CHECK: DO=D7, AO disconnected, power=3V3, relay GPIO%u LOW\n", ESP8266_RELAY_GPIO);
}

void loop() {
    const uint32_t now = millis();
    if (now - lastSample >= 250) {
        lastSample = now;
        const int level = digitalRead(13);
        if (previousLevel >= 0 && level != previousLevel) ++transitions;
        previousLevel = level;
        if (displayReady) {
            display.clearDisplay();
            display.setTextColor(SH110X_WHITE);
            display.setTextSize(1);
            display.setCursor(0, 0);
            display.println("TV1 RAIN DO TEST");
            display.printf("D7: %s\n", level ? "HIGH (1)" : "LOW (0)");
            display.printf("Changes: %lu\n", static_cast<unsigned long>(transitions));
            display.println("AO: DISCONNECTED");
            display.println("Relay: OFF");
            display.printf("Time: %lu s", static_cast<unsigned long>(now / 1000));
            display.display();
        }
        Serial.printf("{\"test\":\"RAIN_DO\",\"level\":%d,\"transitions\":%lu,\"oled_ready\":%s,\"relay_level\":\"LOW\",\"uptime_ms\":%lu}\n",
                      level, static_cast<unsigned long>(transitions), displayReady ? "true" : "false", static_cast<unsigned long>(now));
    }
    yield();
}

/** Standalone UART diagnosis: DHT11 DATA -> NodeMCU D5/GPIO14.
 * No MQTT or fabricated pressure/rain samples; holds configured relay LOW.
 */
#include <Arduino.h>
#include "board_wiring.h"
#include <DHT.h>

constexpr uint8_t DHT_PIN = 14;
constexpr uint32_t SAMPLE_MS = 2500;
DHT sensor(DHT_PIN, DHT11);
uint32_t lastSample = 0;

void setup() {
    digitalWrite(ESP8266_RELAY_GPIO, LOW);
    pinMode(ESP8266_RELAY_GPIO, OUTPUT);
    Serial.begin(115200);
    sensor.begin();
    Serial.println("DHT11_CHECK: DATA=D5/GPIO14, power=3V3, serial=115200");
}

void loop() {
    const uint32_t now = millis();
    if (now - lastSample >= SAMPLE_MS) {
        lastSample = now;
        const float temperature = sensor.readTemperature();
        const float humidity = sensor.readHumidity();
        if (!isfinite(temperature) || !isfinite(humidity)) {
            Serial.printf("{\"test\":\"DHT11\",\"status\":\"no_reading\",\"uptime_ms\":%lu}\n",
                          static_cast<unsigned long>(now));
        } else {
            Serial.printf("{\"test\":\"DHT11\",\"status\":\"ok\",\"temperature\":%.1f,\"humidity\":%.1f,\"uptime_ms\":%lu}\n",
                          temperature, humidity, static_cast<unsigned long>(now));
        }
    }
    yield();
}

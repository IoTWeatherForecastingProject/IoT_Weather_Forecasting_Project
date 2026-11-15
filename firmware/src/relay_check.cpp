/** UART-only relay check. NodeMCU D6/GPIO12 -> IN, jumper H.
 * Remove the IN-to-DC+ bridge before attaching D6. DHT11 remains on D5.
 * Starts LOW and requires RUN\n over UART; at most three pulses per boot.
 * RELAY_CHECK_SINGLE_PULSE limits the firmware to one pulse for buzzer trials.
 * Logged GPIO commands do not confirm physical coil/contact operation.
 */
#include <Arduino.h>
#include <DHT.h>
#include <string.h>

#ifndef RELAY_CHECK_GPIO
#define RELAY_CHECK_GPIO 12
#endif
constexpr uint8_t RELAY_PIN = RELAY_CHECK_GPIO;
static_assert(RELAY_PIN == 12 || RELAY_PIN == 16, "Diagnostic supports D6 or D0 only");
constexpr uint8_t DHT_PIN = 14;
constexpr uint32_t ON_MS = 3000;
constexpr uint32_t OFF_MS = 5000;
constexpr uint32_t SAMPLE_MS = 2500;
#ifdef RELAY_CHECK_SINGLE_PULSE
constexpr uint8_t PULSES = 1;
#else
constexpr uint8_t PULSES = 3;
#endif
DHT sensor(DHT_PIN, DHT11);
bool running = false;
bool used = false;
bool outputHigh = false;
uint8_t senseChecks = 0;
uint8_t cycle = 0;
uint32_t phaseStarted = 0;
uint32_t lastSample = 0;
char command[16];
uint8_t commandLength = 0;
bool commandOverflow = false;

void report(const char* event) {
    Serial.printf("{\"test\":\"RELAY\",\"event\":\"%s\",\"gpio\":%u,"
                  "\"commanded_level\":\"%s\",\"observed_level\":\"%s\",\"cycle\":%u,\"used\":%s,"
                  "\"running\":%s,\"uptime_ms\":%lu}\n",
                  event, RELAY_PIN, outputHigh ? "HIGH" : "LOW", digitalRead(RELAY_PIN) ? "HIGH" : "LOW", cycle,
                  used ? "true" : "false", running ? "true" : "false",
                  static_cast<unsigned long>(millis()));
}

void setOutput(bool high) {
    digitalWrite(RELAY_PIN, high ? HIGH : LOW);
    outputHigh = high;
    phaseStarted = millis();
    senseChecks = 0;
    report("gpio_command");
}

void handleCommand() {
    if (strcmp(command, "STOP") == 0) {
        running = false;
        used = true;
        setOutput(false);
        report("stopped");
    } else if (strcmp(command, "RUN") == 0) {
        if (used) {
            report("run_rejected");
            return;
        }
        used = true;
        running = true;
        cycle = 1;
        report("started");
        setOutput(true);
    } else if (strcmp(command, "STATUS") == 0) {
        report("status");
    } else {
        report("unknown_command");
    }
}

void setup() {
    // Keep the old relay route inactive while transitioning to the D0 trial.
    if (RELAY_PIN != 12) {
        digitalWrite(12, LOW);
        pinMode(12, OUTPUT);
    }
    digitalWrite(RELAY_PIN, LOW);
    pinMode(RELAY_PIN, OUTPUT);
    Serial.begin(115200);
    sensor.begin();
    report("ready");
}

void loop() {
    // Service the relay before the sensor: no delay() across either phase.
    const uint32_t now = millis();
    if (running && now - phaseStarted >= (outputHigh ? ON_MS : OFF_MS)) {
        if (outputHigh) {
            setOutput(false);
        } else if (cycle < PULSES) {
            ++cycle;
            setOutput(true);
        } else {
            running = false;
            report("complete");
        }
    }

    // Check the GPIO input register after settling and midway through the pulse.
    // Digital readback is not a voltage/current or relay-contact measurement.
    if (running && outputHigh && senseChecks < 2 &&
        static_cast<uint32_t>(millis() - phaseStarted) >= (senseChecks == 0 ? 100U : 1500U)) {
        ++senseChecks;
        report("pin_check");
    }

    // Bounded work per pass, even if a host sends excessive serial input.
    for (uint8_t count = 0; count < 32 && Serial.available(); ++count) {
        const char c = static_cast<char>(Serial.read());
        if (c == '\r') continue;
        if (c == '\n') {
            command[commandLength] = '\0';
            if (commandOverflow) report("invalid_command");
            else if (commandLength) handleCommand();
            commandLength = 0;
            commandOverflow = false;
        } else if (commandLength < sizeof(command) - 1) {
            command[commandLength++] = c;
        } else {
            commandOverflow = true;
        }
    }

    const uint32_t sampleTime = millis();
    if (sampleTime - lastSample >= SAMPLE_MS) {
        lastSample = sampleTime;
        const float temperature = sensor.readTemperature();
        const float humidity = sensor.readHumidity();
        if (!isfinite(temperature) || !isfinite(humidity)) {
            Serial.printf("{\"test\":\"DHT11\",\"status\":\"no_reading\",\"uptime_ms\":%lu}\n",
                          static_cast<unsigned long>(sampleTime));
        } else {
            Serial.printf("{\"test\":\"DHT11\",\"status\":\"ok\",\"temperature\":%.1f,"
                          "\"humidity\":%.1f,\"uptime_ms\":%lu}\n",
                          temperature, humidity, static_cast<unsigned long>(sampleTime));
        }
    }
    yield();
}

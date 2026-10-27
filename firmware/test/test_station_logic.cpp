#include <assert.h>
#include <stdio.h>
#include "station_logic.h"

station::Reading reading(float temperature, int rain = 900) {
    station::Reading result;
    result.temperature = temperature;
    result.humidity = 70;
    result.pressure = 1008;
    result.rainRaw = rain;
    return result;
}

void testMovingAverage() {
    station::MovingAverage<5> filter;
    station::Reading output;
    assert(filter.add(reading(20, 100), output));
    assert(output.temperature == 20 && output.rainRaw == 100);
    for (int i = 1; i <= 5; ++i) assert(filter.add(reading(20 + i, 100 + i * 10), output));
    // Sixth sample evicts the first: mean of 21..25, ADC mean 110..150.
    assert(output.temperature == 23 && output.rainRaw == 130);
    assert(output.humidity == 70 && output.pressure == 1008);
}

void testInvalidSampleAndRecovery() {
    station::MovingAverage<5> filter;
    station::Reading output;
    assert(filter.add(reading(20), output));
    station::Reading broken = reading(80);
    broken.humidity = NAN;
    assert(!filter.add(broken, output));
    assert(isnan(output.humidity));
    assert(filter.add(reading(30), output));
    assert(output.temperature == 30); // Old 20 C must not survive the failed sample.
    broken = reading(30);
    broken.pressure = INFINITY;
    assert(!filter.add(broken, output));
}

void testPhysicalLimits() {
    station::Reading value = reading(-40);
    assert(value.valid());
    value.temperature = 86;
    assert(!value.valid());
    value = reading(25);
    value.humidity = 101;
    assert(!value.valid());
    value.humidity = -1;
    assert(!value.valid());
    value = reading(25);
    value.pressure = 0;
    assert(!value.valid());
}

void testRainPolarity() {
    assert(station::rainDetected(200, 600, true));
    assert(!station::rainDetected(900, 600, true));
    assert(!station::rainDetected(600, 600, true));
    assert(station::rainDetected(900, 600, false));
    assert(!station::rainDetected(200, 600, false));
}

void testAlertTimingAndDuplicates() {
    station::AlertState alert;
    assert(!alert.buzzerOn(0, 3000));
    assert(alert.start(100, true, true));
    assert(alert.buzzerOn(3099, 3000));
    assert(!alert.start(3099, true, true));
    assert(!alert.buzzerOn(3100, 3000));
    assert(alert.ledOn(100, 250));
    assert(!alert.ledOn(350, 250));
    alert.update(10099, 10000);
    assert(alert.active());
    alert.update(10100, 10000);
    assert(!alert.active());
    assert(!alert.ledOn(10100, 250));
    assert(alert.start(10200, true, true));
}

void testDisabledActions() {
    station::AlertState alert;
    assert(alert.start(0, false, false));
    assert(alert.active()); // OLED-only alerts are supported.
    assert(!alert.buzzerOn(0, 3000));
    assert(!alert.ledOn(0, 250));
}

void testMillisWraparound() {
    station::AlertState alert;
    const uint32_t startedAt = UINT32_MAX - 1000;
    alert.start(startedAt, true, true);
    const uint32_t beforeOff = startedAt + uint32_t(2999);
    const uint32_t afterOff = startedAt + uint32_t(3000);
    assert(alert.buzzerOn(beforeOff, 3000));
    assert(!alert.buzzerOn(afterOff, 3000));
    alert.update(startedAt + uint32_t(10000), 10000);
    assert(!alert.active());
}

int main() {
    testMovingAverage();
    testInvalidSampleAndRecovery();
    testPhysicalLimits();
    testRainPolarity();
    testAlertTimingAndDuplicates();
    testDisabledActions();
    testMillisWraparound();
    puts("7 station logic tests passed");
}

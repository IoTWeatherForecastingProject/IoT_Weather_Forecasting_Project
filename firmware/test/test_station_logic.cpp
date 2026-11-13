#include <assert.h>
#include <stdio.h>
#include "station_logic.h"
#include "bmp_quality.h"
#include "bmp280_sample.h"
#include "rain_relay.h"
#include "forecast_buzzer.h"

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

void testBmpUnmeasuredRegression() {
    // Observed reset registers compensated into plausible-looking 23.36 C/680.21 hPa.
    station::Reading resetValue = reading(23.36f);
    resetValue.pressure = 680.21f;
    assert(resetValue.valid());
    assert(station::bmpRawIssue(true, 0x80000, 0x80000, 0x00));
    assert(station::bmpRawIssue(true, 0x80000, 415148, 0x57));
    assert(station::bmpRawIssue(true, 519888, 0x80000, 0x57));
    assert(station::bmpRawIssue(true, 0, 415148, 0x57));
    assert(station::bmpRawIssue(false, 519888, 415148, 0x57));
    // Completed forced measurements return to sleep with oversampling still enabled.
    assert(!station::bmpRawIssue(true, 519888, 415148, 0x24));
    assert(!station::bmpRawIssue(true, 519888, 415148, 0x57));
}

void testBmpCompensationFromCapturedSample() {
    // Calibration and paired ADC channels from the replacement module.
    const uint8_t calibration[] = {
        0x9B, 0x6E, 0x3C, 0x66, 0x32, 0x00, 0x96, 0x8F,
        0xEA, 0xD5, 0xD0, 0x0B, 0xFE, 0x1E, 0x98, 0xFF,
        0xF9, 0xFF, 0x8C, 0x3C, 0xF8, 0xC6, 0x70, 0x17
    };
    float pressure = 0;
    assert(station::compensateBmp280(calibration, 552832, 332509, pressure));
    assert(fabs(pressure - 1011.32f) < 0.05f);
    assert(!station::compensateBmp280(calibration, 0, 332509, pressure));
}

void testRainRelayPulseAndRearm() {
    station::RainRelay relay;
    assert(!relay.update(true, 0));
    assert(!relay.update(true, 1000)); // A wet probe at boot is not a new transition.
    assert(!relay.update(false, 2000));
    assert(!relay.update(false, 3000));
    assert(!relay.update(true, 3100));
    assert(!relay.update(true, 3399));
    assert(relay.update(true, 3400));
    assert(relay.update(true, 6399));
    assert(!relay.update(true, 6400));
    assert(!relay.update(true, 10000));
    assert(!relay.update(false, 10100));
    assert(!relay.update(true, 10500)); // A brief dry glitch cannot rearm.
    assert(!relay.update(true, 10800));
    assert(!relay.update(false, 11000));
    assert(!relay.update(false, 12000));
    assert(!relay.update(true, 12100));
    assert(relay.update(true, 12400));
}

void testForecastBuzzerTimingAndCancellation() {
    station::ForecastBuzzer buzzer;
    const uint32_t start = UINT32_MAX - 100;
    assert(buzzer.start(start));
    for (uint32_t elapsed = 0; elapsed < 1250; ++elapsed) {
        assert(buzzer.active(start + elapsed));
        assert(buzzer.buzzerOn(start + elapsed) == (elapsed / 250 % 2 == 0));
    }
    assert(!buzzer.buzzerOn(start + 1250));
    assert(!buzzer.start(start + 179999));
    assert(buzzer.start(start + 180000));
    buzzer.cancel();
    assert(!buzzer.buzzerOn(start + 180000));
}

int main() {
    testMovingAverage();
    testInvalidSampleAndRecovery();
    testPhysicalLimits();
    testRainPolarity();
    testAlertTimingAndDuplicates();
    testDisabledActions();
    testMillisWraparound();
    testBmpUnmeasuredRegression();
    testBmpCompensationFromCapturedSample();
    testRainRelayPulseAndRearm();
    testForecastBuzzerTimingAndCancellation();
    puts("11 station logic tests passed");
}

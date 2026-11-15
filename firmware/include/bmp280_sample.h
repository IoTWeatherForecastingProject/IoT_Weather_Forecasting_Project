#pragma once

#include <math.h>
#include <stdint.h>

namespace station {

// Bosch BMP280 datasheet, section 8.1. Use the temperature and pressure
// channels from the same six-byte register read.
inline bool compensateBmp280(const uint8_t *calibration, uint32_t adcTemperature,
                             uint32_t adcPressure, float &pressureHpa) {
    uint16_t coefficients[12];
    for (uint8_t i = 0; i < 12; ++i) {
        coefficients[i] = uint16_t(calibration[2 * i]) |
                          (uint16_t(calibration[2 * i + 1]) << 8);
    }
    if (!coefficients[0] || coefficients[0] == 0xFFFF ||
        !coefficients[3] || coefficients[3] == 0xFFFF) return false;

    const double delta = adcTemperature / 131072.0 - coefficients[0] / 8192.0;
    const double fine = (adcTemperature / 16384.0 - coefficients[0] / 1024.0) *
                            int16_t(coefficients[1]) +
                        delta * delta * int16_t(coefficients[2]);
    const double temperature = fine / 5120.0;
    if (temperature < -40 || temperature > 85) return false;

    const double offset = int32_t(fine) / 2.0 - 64000.0;
    const double pressureOffset =
        (offset * offset * int16_t(coefficients[8]) / 32768.0 +
         offset * int16_t(coefficients[7]) * 2.0) / 4.0 +
        int16_t(coefficients[6]) * 65536.0;
    const double gain = coefficients[3] * (1.0 +
        (int16_t(coefficients[5]) * offset * offset / 524288.0 +
         int16_t(coefficients[4]) * offset) / 17179869184.0);
    if (gain == 0.0) return false;

    const double pressure = (1048576.0 - adcPressure - pressureOffset / 4096.0) *
                            6250.0 / gain;
    const double correction = int16_t(coefficients[11]) * pressure * pressure / 2147483648.0 +
                              int16_t(coefficients[10]) * pressure / 32768.0 +
                              int16_t(coefficients[9]);
    const double hpa = (pressure + correction / 16.0) / 100.0;
    if (!isfinite(hpa) || hpa < 300 || hpa > 1100) return false;
    pressureHpa = hpa;
    return true;
}
} // namespace station

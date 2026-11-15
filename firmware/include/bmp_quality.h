#pragma once
#include <stdint.h>

namespace station {
// nullptr means usable raw channels, not calibrated accuracy or final plausibility.
inline const char *bmpRawIssue(bool readOk, uint32_t temperatureAdc,
                               uint32_t pressureAdc, uint8_t ctrlMeas) {
    if (!readOk) return "bmp_register_read_failed";
    if ((ctrlMeas & 0xE0) == 0 || (ctrlMeas & 0x1C) == 0)
        return "bmp_measurement_disabled";
    // Bosch uses 0x80000 for skipped/unmeasured channels after reset.
    if (temperatureAdc == 0x80000 || pressureAdc == 0x80000)
        return "bmp_unmeasured_adc";
    if (temperatureAdc == 0 || pressureAdc == 0 ||
        temperatureAdc >= 0xFFFFF || pressureAdc >= 0xFFFFF)
        return "bmp_zero_or_saturated_adc";
    return nullptr;
}
} // namespace station

#ifndef STATION_LOGIC_H
#define STATION_LOGIC_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>

namespace station {

struct Reading {
    float temperature = NAN;
    float humidity = NAN;
    float pressure = NAN;
    int rainRaw = 0;

    bool valid() const {
        return isfinite(temperature) && isfinite(humidity) && isfinite(pressure)
            && temperature >= -40.0f && temperature <= 85.0f
            && humidity >= 0.0f && humidity <= 100.0f
            && pressure >= 300.0f && pressure <= 1100.0f;
    }
};

// A failed sample clears history, so recovery never publishes stale values.
template <size_t Window>
class MovingAverage {
    static_assert(Window > 0, "Filter window must be positive");
public:
    bool add(const Reading& reading, Reading& filtered) {
        if (!reading.valid()) {
            count_ = index_ = 0;
            filtered = reading;
            return false;
        }
        readings_[index_] = reading;
        index_ = (index_ + 1) % Window;
        if (count_ < Window) ++count_;
        filtered.temperature = filtered.humidity = filtered.pressure = 0;
        long rainSum = 0;
        for (size_t i = 0; i < count_; ++i) {
            filtered.temperature += readings_[i].temperature;
            filtered.humidity += readings_[i].humidity;
            filtered.pressure += readings_[i].pressure;
            rainSum += readings_[i].rainRaw;
        }
        filtered.temperature /= count_;
        filtered.humidity /= count_;
        filtered.pressure /= count_;
        filtered.rainRaw = rainSum / count_;
        return true;
    }
private:
    Reading readings_[Window];
    size_t index_ = 0;
    size_t count_ = 0;
};

inline bool rainDetected(int raw, int threshold, bool wetIsLow) {
    return wetIsLow ? raw < threshold : raw > threshold;
}

class AlertState {
public:
    // Ignore repeated commands until this alert finishes; never extend coil time.
    bool start(uint32_t now, bool buzzer, bool led) {
        if (active_) return false;
        active_ = true;
        startedAt_ = now;
        buzzer_ = buzzer;
        led_ = led;
        return true;
    }
    void update(uint32_t now, uint32_t duration) {
        if (active_ && static_cast<uint32_t>(now - startedAt_) >= duration) {
            active_ = false;
        }
    }
    bool active() const { return active_; }
    bool buzzerOn(uint32_t now, uint32_t relayDuration) const {
        return active_ && buzzer_
            && static_cast<uint32_t>(now - startedAt_) < relayDuration;
    }
    bool ledOn(uint32_t now, uint32_t blinkInterval) const {
        return active_ && led_ && (static_cast<uint32_t>(now - startedAt_)
            / blinkInterval) % 2 == 0;
    }
private:
    bool active_ = false;
    bool buzzer_ = false;
    bool led_ = false;
    uint32_t startedAt_ = 0;
};

} // namespace station
#endif

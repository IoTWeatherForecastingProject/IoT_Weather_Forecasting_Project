#pragma once

#include <stdint.h>

namespace station {

class ForecastBuzzer {
public:
    bool start(uint32_t now) {
        if (active(now) || (hasPlayed_ && now - startedAt_ < 180000)) return false;
        startedAt_ = now;
        hasPlayed_ = true;
        playing_ = true;
        return true;
    }

    void cancel() { playing_ = false; }

    bool active(uint32_t now) const {
        return playing_ && now - startedAt_ < 5 * stepMs_;
    }

    bool buzzerOn(uint32_t now) const {
        return active(now) && ((now - startedAt_) / stepMs_) % 2 == 0;
    }

private:
    static constexpr uint32_t stepMs_ = 250;
    uint32_t startedAt_ = 0;
    bool hasPlayed_ = false;
    bool playing_ = false;
};

} // namespace station

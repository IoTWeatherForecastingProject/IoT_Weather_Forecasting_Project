#pragma once

#include <stdint.h>

namespace station {

class RainRelay {
public:
    bool update(bool wet, uint32_t now) {
        if (active_ && now - startedAt_ >= 3000) active_ = false;
        if (!seen_ || wet != candidateWet_) {
            seen_ = true;
            candidateWet_ = wet;
            changedAt_ = now;
            return active_;
        }
        if (now - changedAt_ < (wet ? 300u : 1000u)) return active_;
        if (!wet) {
            armed_ = true;
        } else if (armed_) {
            armed_ = false;
            if (!active_) {
                startedAt_ = now;
                active_ = true;
            }
        }
        return active_;
    }

private:
    bool seen_ = false;
    bool candidateWet_ = false;
    bool armed_ = false;
    bool active_ = false;
    uint32_t changedAt_ = 0;
    uint32_t startedAt_ = 0;
};
} // namespace station

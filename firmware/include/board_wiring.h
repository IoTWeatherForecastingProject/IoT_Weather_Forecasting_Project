#pragma once

// Current NodeMCU wiring: relay IN -> D0/GPIO16, confirmed 2026-11-03.
// Override only for an explicit historical D6 diagnostic build.
#ifndef ESP8266_RELAY_GPIO
#define ESP8266_RELAY_GPIO 16
#endif

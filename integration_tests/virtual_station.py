"""Contract-level station double for TV1 E2E; no hardware or AI inference.

Durations model the agreed 3s buzzer/10s LED behavior. This is not an emulator
of the ESP8266 firmware and cannot certify electrical timing or parser parity.
"""
import json
import math
import threading
import time


class VirtualStation:
    def __init__(self, device_id, alert_topic, clock=time.monotonic):
        self.device_id = device_id
        self.alert_topic = alert_topic
        self.clock = clock
        self.lock = threading.Lock()
        self.started_at = None
        self.buzzer = False
        self.led = False
        self.accepted_count = 0
        self.events = []

    def _snapshot(self, now):
        elapsed = now - self.started_at if self.started_at is not None else 0
        active = self.started_at is not None and elapsed < 10
        return {'active':active, 'buzzer_on':bool(active and self.buzzer and elapsed < 3),
                'led_on':bool(active and self.led and int(elapsed / 0.25) % 2 == 0),
                'elapsed_seconds':elapsed, 'accepted_count':self.accepted_count}

    def snapshot(self):
        with self.lock:
            return self._snapshot(self.clock())

    def accept(self, topic, payload, retained=False):
        with self.lock:
            now = self.clock()
            reason = None
            if topic != self.alert_topic:
                reason = 'wrong_topic'
            elif retained:
                reason = 'retained_command'
            try:
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise ValueError('not an object')
                probability = data.get('probability')
                action = data.get('action')
                if (data.get('type') != 'rain_warning' or data.get('device_id') != self.device_id
                        or isinstance(probability, bool) or not isinstance(probability, (int, float))
                        or not math.isfinite(probability) or not 0 <= probability <= 1
                        or type(data.get('forecast_minutes')) is not int or data['forecast_minutes'] not in (10, 30, 60)
                        or not isinstance(action, dict)
                        or type(action.get('buzzer')) is not bool or type(action.get('led_blink')) is not bool
                        or not isinstance(action.get('oled_message'), str)):
                    raise ValueError('invalid alert contract')
            except (ValueError, TypeError, UnicodeDecodeError):
                reason = reason or 'invalid_payload'
            if reason is None and self._snapshot(now)['active']:
                reason = 'busy'
            if reason is None:
                self.started_at = now
                self.buzzer, self.led = action['buzzer'], action['led_blink']
                self.accepted_count += 1
            result = 'accepted' if reason is None else reason
            self.events.append({'event':result, 'at_monotonic':now})
            return result

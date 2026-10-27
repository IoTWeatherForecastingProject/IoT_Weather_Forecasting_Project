"""Offline checks for simulated ESP8266/ESP32 telemetry; no broker required."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "simulate_iot_device", Path(__file__).with_name("simulate_iot_device.py")
)
simulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator)


def collect_payloads(adc_bits: int, rain: bool = False, anomaly: bool = False) -> list[dict]:
    client = Mock()
    with patch.object(simulator.mqtt, "Client", return_value=client), \
         patch.object(simulator.time, "sleep", side_effect=[None] * 4 + [KeyboardInterrupt]), \
         patch.object(simulator.logger, "info"), patch.object(simulator.logger, "warning"):
        simulator.run_simulator("localhost", 1883, 5, rain, anomaly, adc_bits=adc_bits)
    client.connect.assert_called_once()
    client.disconnect.assert_called_once()
    payloads = []
    for call in client.publish.call_args_list:
        assert call.args[0] == "weather/station01/data"
        payloads.append(json.loads(call.args[1]))
    return payloads


class SimulatorPayloadTests(unittest.TestCase):
    def test_all_scenarios_fit_selected_adc(self):
        for bits in (10, 12):
            for rain, anomaly in ((False, False), (True, False), (False, True)):
                with self.subTest(bits=bits, rain=rain, anomaly=anomaly):
                    payloads = collect_payloads(bits, rain, anomaly)
                    self.assertEqual(len(payloads), 5)
                    for payload in payloads:
                        self.assertEqual(payload["device_id"], "station01")
                        self.assertGreaterEqual(payload["rain_raw"], 0)
                        self.assertLessEqual(payload["rain_raw"], (1 << bits) - 1)
                        for field in ("temperature", "humidity", "pressure"):
                            self.assertIsInstance(payload[field], (float, int))

    def test_rain_flag_agrees_with_firmware_default_threshold(self):
        for bits, threshold in ((10, 600), (12, 2500)):
            with self.subTest(bits=bits):
                payloads = collect_payloads(bits, rain=True)
                self.assertEqual([p["rain_detected"] for p in payloads], [0, 0, 1, 1, 1])
                for payload in payloads:
                    self.assertEqual(payload["rain_detected"], int(payload["rain_raw"] < threshold))


if __name__ == "__main__":
    unittest.main()

"""Delivery, cooldown and concurrency contracts; never sends real notifications."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import paho.mqtt.client as mqtt
import pytest

from app.config import settings
from app.services import alert_service
from app.services.alert_service import AlertService


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(AlertService, "_last_sent", {})
    monkeypatch.setattr(AlertService, "_in_flight", set())
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(alert_service.time, "monotonic", clock)
    monkeypatch.setattr(settings, "ALERT_COOLDOWN_SECONDS", 180)
    monkeypatch.setattr(settings, "ALERT_MQTT_ACK_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(settings, "MQTT_ALERT_TOPIC", "weather/{device_id}/alert")
    monkeypatch.setattr(settings, "ENABLE_TELEGRAM_NOTIFICATIONS", False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-test-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "test-chat")
    info = Mock(rc=mqtt.MQTT_ERR_SUCCESS)
    info.is_published.return_value = True
    client = Mock()
    client.is_connected.return_value = True
    client.publish.return_value = info
    audit, telegram = Mock(), Mock(return_value=True)
    monkeypatch.setattr(AlertService, "_log_alert_to_db", audit)
    monkeypatch.setattr(AlertService, "_send_telegram_alert", telegram)
    return SimpleNamespace(client=client, info=info, audit=audit, telegram=telegram, clock=clock)


def trigger(context, **overrides):
    arguments = dict(device_id="station01", rain_probability=0.85, horizon_minutes=30,
                     mqtt_client=context.client, threshold=0.70)
    arguments.update(overrides)
    return AlertService.evaluate_and_trigger(**arguments)


@pytest.mark.parametrize("template", ["weather/{device_id}/alert", "weather/station01/alert"])
def test_acknowledged_alert_uses_correct_device_topic_payload_and_audit(context, monkeypatch, template):
    monkeypatch.setattr(settings, "MQTT_ALERT_TOPIC", template)
    assert trigger(context, device_id="sim_tv1") is True
    call = context.client.publish.call_args
    assert call.args[0] == "weather/sim_tv1/alert"
    assert call.kwargs == {"qos": 1, "retain": False}
    payload = json.loads(call.args[1])
    assert payload["device_id"] == "sim_tv1"
    assert payload["type"] == "rain_warning"
    assert payload["action"]["buzzer"] is True
    assert payload["forecast_minutes"] == 30
    context.info.wait_for_publish.assert_called_once_with(timeout=2)
    assert context.audit.call_args.kwargs["mqtt_sent"] is True
    assert context.audit.call_args.kwargs["telegram_sent"] is False
    context.telegram.assert_not_called()


@pytest.mark.parametrize("probability,threshold", [(0.69, 0.7), (float("nan"), 0.7),
                                                  (0.9, float("nan")), (1.1, 0.7)])
def test_below_threshold_or_invalid_values_do_not_send(context, probability, threshold):
    assert trigger(context, rain_probability=probability, threshold=threshold) is False
    context.client.publish.assert_not_called()
    context.audit.assert_not_called()


def test_threshold_is_inclusive(context):
    assert trigger(context, rain_probability=0.7, threshold=0.7) is True


def test_cooldown_is_per_device_and_expires_at_boundary(context):
    assert trigger(context) is True
    context.clock.return_value = 279.99
    assert trigger(context) is False
    assert trigger(context, device_id="station02") is True
    context.clock.return_value = 280.0
    assert trigger(context) is True
    assert context.client.publish.call_count == 3
    assert context.audit.call_count == 3


def test_overlapping_api_and_monitor_calls_only_publish_once(context):
    def publish(*args, **kwargs):
        assert trigger(context) is False  # A second thread enters before the ACK.
        return context.info
    context.client.publish.side_effect = publish
    assert trigger(context) is True
    context.client.publish.assert_called_once()
    assert not AlertService._in_flight


@pytest.mark.parametrize("failure", ["offline", "rejected", "timeout", "exception"])
def test_failed_delivery_is_audited_and_can_retry_without_waiting_for_cooldown(context, failure):
    if failure == "offline":
        context.client.is_connected.return_value = False
    elif failure == "rejected":
        context.info.rc = mqtt.MQTT_ERR_NO_CONN
    elif failure == "timeout":
        context.info.is_published.return_value = False
    else:
        context.info.wait_for_publish.side_effect = RuntimeError("socket closed")
    assert trigger(context) is False
    assert context.audit.call_args.kwargs["mqtt_sent"] is False
    assert not AlertService._last_sent
    context.client.is_connected.return_value = True
    context.info.rc = mqtt.MQTT_ERR_SUCCESS
    context.info.is_published.return_value = True
    context.info.wait_for_publish.side_effect = None
    assert trigger(context) is True


def test_successful_telegram_does_not_prevent_failed_mqtt_retry(context, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_TELEGRAM_NOTIFICATIONS", True)
    context.client.is_connected.return_value = False
    assert trigger(context) is True
    assert context.audit.call_args.kwargs["mqtt_sent"] is False
    context.client.is_connected.return_value = True
    assert trigger(context) is True
    context.telegram.assert_called_once()
    context.client.publish.assert_called_once()


def test_failed_telegram_retries_without_repeating_successful_mqtt(context, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_TELEGRAM_NOTIFICATIONS", True)
    context.telegram.side_effect = [False, True]
    assert trigger(context) is True
    assert trigger(context) is True
    assert trigger(context) is False
    context.client.publish.assert_called_once()
    assert context.telegram.call_count == 2


@pytest.mark.parametrize("device", ["", "bad/id", "bad+id", "bad#id"])
def test_invalid_topic_device_is_not_published(context, device):
    assert trigger(context, device_id=device) is False
    context.client.publish.assert_not_called()


@pytest.mark.parametrize("status,ok,expected", [(200, True, True), (200, False, False), (401, False, False)])
def test_telegram_requires_successful_api_result(monkeypatch, status, ok, expected):
    response = Mock(status_code=status)
    response.json.return_value = {"ok": ok}
    http = Mock()
    http.__enter__ = Mock(return_value=http)
    http.__exit__ = Mock(return_value=False)
    http.post.return_value = response
    monkeypatch.setattr(alert_service.httpx, "Client", Mock(return_value=http))
    assert AlertService._send_telegram_alert("station01", 0.85, 30) is expected
    body = http.post.call_args.kwargs["json"]
    assert body["parse_mode"] == "Markdown"
    assert "85.0%" in body["text"]
    assert "đã tự động kích hoạt" not in body["text"]


def test_telegram_network_error_does_not_expose_bot_url(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "private-test-token")
    monkeypatch.setattr(alert_service.httpx, "Client", Mock(side_effect=httpx.ConnectError(
        "https://api.telegram.org/botprivate-test-token/sendMessage")))
    assert AlertService._send_telegram_alert("station01", 0.85, 30) is False
    assert "private-test-token" not in caplog.text

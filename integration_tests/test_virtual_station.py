import json
import pytest

from integration_tests.virtual_station import VirtualStation


@pytest.fixture
def station():
    clock = [100.0]
    device = VirtualStation('s1', 'test/s1/alert', clock=lambda:clock[0])
    payload = {'type':'rain_warning', 'device_id':'s1', 'probability':0.9, 'forecast_minutes':30,
               'action':{'buzzer':True, 'led_blink':True, 'oled_message':'test'}}
    return device, clock, payload


def test_buzzer_and_led_deadlines_and_duplicate_do_not_extend(station):
    device, clock, payload = station
    assert device.accept(device.alert_topic, json.dumps(payload)) == 'accepted'
    assert device.snapshot()['buzzer_on'] and device.snapshot()['led_on']
    clock[0] = 100.25
    assert not device.snapshot()['led_on']
    clock[0] = 102.999
    assert device.accept(device.alert_topic, json.dumps(payload)) == 'busy'
    assert device.snapshot()['buzzer_on']
    clock[0] = 103.0
    assert not device.snapshot()['buzzer_on'] and device.snapshot()['active']
    clock[0] = 110.0
    assert not device.snapshot()['active'] and not device.snapshot()['led_on']
    assert device.accept(device.alert_topic, json.dumps(payload)) == 'accepted'
    assert device.snapshot()['accepted_count'] == 2


@pytest.mark.parametrize('change', [
    {'device_id':'other'}, {'probability':float('nan')}, {'probability':float('inf')},
    {'probability':1.1}, {'probability':True}, {'forecast_minutes':True},
    {'forecast_minutes':15}, {'type':'other'}, {'action':{'buzzer':'yes'}},
])
def test_invalid_commands_never_actuate(station, change):
    device, _, payload = station
    payload.update(change)
    assert device.accept(device.alert_topic, json.dumps(payload)) == 'invalid_payload'
    assert not device.snapshot()['buzzer_on'] and device.snapshot()['accepted_count'] == 0


@pytest.mark.parametrize('payload', ['[]', 'null', '{broken', b'\xff'])
def test_malformed_commands_are_rejected(station, payload):
    device, _, _ = station
    assert device.accept(device.alert_topic, payload) == 'invalid_payload'
    assert not device.snapshot()['active']


def test_retained_or_wrong_topic_does_not_start_action(station):
    device, _, payload = station
    raw = json.dumps(payload)
    assert device.accept(device.alert_topic, raw, retained=True) == 'retained_command'
    assert device.accept('test/other/alert', raw) == 'wrong_topic'
    assert not device.snapshot()['active']


def test_disabled_actions_still_have_finite_alert_lifetime(station):
    device, clock, payload = station
    payload['action'].update(buzzer=False, led_blink=False)
    device.accept(device.alert_topic, json.dumps(payload))
    assert device.snapshot()['active'] and not device.snapshot()['buzzer_on'] and not device.snapshot()['led_on']
    clock[0] += 10
    assert not device.snapshot()['active']

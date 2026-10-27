"""Isolated E2E: MQTT -> PostgreSQL -> REST/WebSocket -> scheduled alert -> cooldown.

Usage from root:
  backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --dashboard
All seeded history is test data in a disposable database and MQTT namespace.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import os

import paho.mqtt.client as mqtt
from sqlalchemy import insert, select, func
from websockets.sync.client import connect

from runtime import ROOT, isolated_backend
from app.db.models import WeatherMeasurement, ReferenceWeather, AlertLog
from virtual_station import VirtualStation


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise TimeoutError("Condition did not become true within timeout")


def core_checks(rt, report):
    api = rt.api
    connected, alert = threading.Event(), threading.Event()
    commands, lock = [], threading.Lock()
    client = mqtt.Client(client_id=f"probe_{rt.run_id}", clean_session=True)
    client.username_pw_set(rt.config.MQTT_USERNAME, rt.config.MQTT_PASSWORD)
    topic = f"{rt.prefix}/{rt.device}/data"
    alert_topic = f"{rt.prefix}/{rt.device}/alert"
    station = VirtualStation(rt.device, alert_topic)
    original_threshold = api.get('/api/weather/alerts/threshold').json()['threshold']
    ws = None
    connections = ExitStack()

    def step(name, **details):
        report['checks'].append({'name': name, 'status': 'passed', **details})
        print(f"PASS {name}", flush=True)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(alert_topic, qos=1)

    def on_subscribe(client, userdata, mid, granted_qos):
        if all(q != 128 for q in granted_qos):
            connected.set()

    def on_message(client, userdata, msg):
        station.accept(msg.topic, msg.payload, retained=msg.retain)
        with lock:
            commands.append({'topic':msg.topic, 'retained':msg.retain, 'payload':json.loads(msg.payload)})
        alert.set()

    def publish(**values):
        payload = dict(device_id=rt.device, timestamp=datetime.now(timezone.utc).isoformat(),
                       temperature=31.23, humidity=90, pressure=1002, rain_raw=200, rain_detected=1)
        payload.update(values)
        info = client.publish(topic, json.dumps(payload), qos=1, retain=False)
        info.wait_for_publish(timeout=5)
        assert info.is_published()
        return payload

    try:
        client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
        client.connect(rt.config.MQTT_BROKER_HOST, rt.config.MQTT_BROKER_PORT)
        client.loop_start()
        assert connected.wait(10), 'MQTT subscription failed'
        ws = connections.enter_context(connect(
            rt.base_url.replace('http', 'ws', 1) + '/ws/weather/live', open_timeout=5))
        step('health_and_observers_ready')
        integration = api.get('/api/weather/integrations')
        integration.raise_for_status()
        assert integration.json()['forecast']['status'] == 'local_heuristic'
        assert integration.json()['analytics']['status'] == 'not_integrated'
        assert rt.external_modules_blocked
        step('tv1_runs_without_tv2_tv3_imports', integrations=integration.json())
        now = datetime.now(timezone.utc)
        history = [dict(device_id=rt.device, timestamp=now-timedelta(seconds=index*30),
                        temperature=31.5, humidity=90, pressure=1002 + index / 160 * 6,
                        rain_raw=200, rain_detected=1)
                   for index in range(160, 0, -1)]
        with rt.engine.begin() as db:
            db.execute(insert(WeatherMeasurement), history)
            db.execute(insert(ReferenceWeather), [
                dict(source='open-meteo', timestamp=now-timedelta(minutes=minutes), lat=0, lon=0,
                     temperature=30, humidity=80, pressure=1005) for minutes in (20, 10)
            ])
        payload = publish()
        streamed = json.loads(ws.recv(timeout=10))
        assert streamed['device_id'] == rt.device and streamed['temperature'] == payload['temperature']
        measured_at = datetime.fromisoformat(payload['timestamp'])

        def live_count():
            with rt.engine.connect() as db:
                return db.execute(select(func.count()).select_from(WeatherMeasurement).where(
                    WeatherMeasurement.device_id == rt.device,
                    WeatherMeasurement.timestamp == measured_at)).scalar_one()
        wait_until(lambda: live_count() == 1)
        current = api.get('/api/weather/current', params={'device_id': rt.device})
        current.raise_for_status()
        assert current.json()['temperature'] == payload['temperature']
        rows = api.get('/api/weather/history', params={'device_id':rt.device,'limit':1000}).json()
        assert len(rows) == 161
        step('telemetry_persisted_api_and_websocket', rows=len(rows))

        # Re-publish the same UTC measurement and a malformed one; neither may broadcast.
        client.publish(topic, json.dumps(payload), qos=1).wait_for_publish(timeout=5)
        client.publish(topic, json.dumps({'device_id':rt.device,'temperature':None}), qos=1).wait_for_publish(timeout=5)
        try:
            ws.recv(timeout=0.8)
            raise AssertionError('Duplicate/invalid telemetry was broadcast')
        except TimeoutError:
            pass
        assert live_count() == 1
        step('duplicate_and_invalid_payloads_rejected')

        # No /forecast has been requested: receipt proves the background monitor acted.
        assert alert.wait(10), 'No independently scheduled alert'
        with lock:
            first = commands[0]
        assert first['topic'] == alert_topic and first['retained'] is False
        assert first['payload']['device_id'] == rt.device and first['payload']['type'] == 'rain_warning'
        assert first['payload']['action']['buzzer'] is True
        step('scheduled_alert_without_forecast_request', topic=alert_topic)
        assert station.snapshot()['accepted_count'] == 1

        def acknowledged_count():
            with rt.engine.connect() as db:
                return db.execute(select(func.count()).select_from(AlertLog).where(
                    AlertLog.device_id == rt.device, AlertLog.mqtt_sent.is_(True))).scalar_one()
        wait_until(lambda: acknowledged_count() == 1)
        forecast = None
        for _ in range(8):
            response = api.get('/api/weather/forecast', params={'device_id':rt.device})
            response.raise_for_status()
            forecast = response.json()
        assert forecast['history_window_minutes'] == 76 and forecast['history_measurements'] > 150
        assert 75 <= forecast['history_span_minutes'] <= 76
        assert forecast['alert_triggered'] is True
        assert all(forecast[f'plus_{h}m']['rain_source'] == 'heuristic' for h in (10,30,60))
        assert forecast['forecast_engine'] == 'local_heuristic' and forecast['fallback_reason'] == 'standalone_mode'
        time.sleep(1.1)  # Two 0.5s monitor cycles, well inside the 180s cooldown.
        with lock:
            unique = {c['payload']['timestamp'] for c in commands}
        assert len(unique) == 1 and acknowledged_count() == 1
        step('forecast_contract_and_shared_cooldown', history_measurements=forecast['history_measurements'])

        changed = api.post('/api/weather/alerts/threshold', json={'threshold':1.0})
        changed.raise_for_status()
        assert api.get('/api/weather/alerts/threshold').json()['threshold'] == 1.0
        assert api.get('/api/weather/forecast', params={'device_id':rt.device}).json()['alert_triggered'] is False
        invalid = api.post('/api/weather/alerts/threshold', json={'threshold':1.1})
        assert invalid.status_code == 422
        api.post('/api/weather/alerts/threshold', json={'threshold':original_threshold}).raise_for_status()
        step('threshold_read_write_and_validation')

        health = api.get('/api/weather/sensor-health', params={'device_id':rt.device})
        health.raise_for_status()
        assert health.json()['status'] == 'UNKNOWN' and health.json()['reason'] == 'analytics_not_integrated'
        benchmark = api.get('/api/weather/benchmark', params={'device_id':rt.device})
        benchmark.raise_for_status()
        assert len(benchmark.json()['reference']) == 2, f"Reference count: {benchmark.json()}"
        assert benchmark.json()['latest_bias'] is None and benchmark.json()['reason'] == 'analytics_not_integrated'
        assert benchmark.json()['metrics'] == {}
        missing = rt.device + '_missing'
        assert api.get('/api/weather/forecast', params={'device_id':missing}).status_code == 404
        assert api.get('/api/weather/sensor-health', params={'device_id':missing}).json()['status'] == 'UNKNOWN'
        assert api.get('/api/weather/benchmark', params={'device_id':missing}).json()['latest_bias'] is None
        step('unmerged_analytics_and_empty_states')
        # This validates backend -> contract double only, not electrical timing.
        wait_until(lambda: not station.snapshot()['buzzer_on'], timeout=4)
        wait_until(lambda: not station.snapshot()['active'], timeout=11)
        assert not station.snapshot()['led_on'] and station.snapshot()['accepted_count'] == 1
        report['virtual_station'] = {'kind':'contract_double_not_firmware_emulator',
                                     'buzzer_duration_seconds':3, 'alert_duration_seconds':10,
                                     'final_state':station.snapshot(), 'events':station.events,
                                     'hardware_actuation_verified':False}
        step('virtual_station_finishes_buzzer_and_led', accepted_commands=1)
        report['forecast'] = forecast
        report['mqtt_alert'] = first
        return publish
    finally:
        try:
            api.post('/api/weather/alerts/threshold', json={'threshold':original_threshold}).raise_for_status()
            assert api.get('/api/weather/alerts/threshold').json()['threshold'] == original_threshold
            report['threshold_restored'] = True
        finally:
            connections.close()
            # A publish callable remains usable by browser checks, so reconnect there if requested.
            client.disconnect()
            client.loop_stop()


def run_e2e_tests(report_dir, dashboard=False, backend_tests=False):
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {'started_at':datetime.now(timezone.utc).isoformat(), 'status':'failed',
              'data_source':'isolated_test_fixtures', 'external_modules_blocked':True,
              'tv2_tv3_merged':False, 'checks':[]}
    code = 1
    try:
        with isolated_backend(report_dir) as rt:
            report['run_id'] = rt.run_id
            report['mqtt_namespace'] = rt.prefix
            report['isolated_database'] = rt.database
            if backend_tests:
                result = subprocess.run(
                    [sys.executable, '-m', 'pytest', 'tests', '-q', '--junitxml', str(report_dir/'backend_pytest.xml')],
                    cwd=ROOT/'backend', env=rt.env, capture_output=True, text=True,
                    timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                (report_dir/'backend_pytest.log').write_text(result.stdout+result.stderr, encoding='utf-8')
                report['backend_pytest_exit_code'] = result.returncode
                if result.returncode:
                    raise AssertionError('Backend suite failed; inspect backend_pytest.log')
                print('PASS backend_suite_in_disposable_database_without_external_modules', flush=True)
            core_checks(rt, report)
            if dashboard:
                from dashboard_check import check_dashboard
                def browser_publish(**values):
                    import paho.mqtt.publish as publish
                    payload = dict(device_id=rt.device, timestamp=datetime.now(timezone.utc).isoformat(),
                                   temperature=31.23, humidity=90, pressure=1002, rain_raw=200, rain_detected=1)
                    payload.update(values)
                    publish.single(f'{rt.prefix}/{rt.device}/data', json.dumps(payload), qos=1,
                                   hostname=rt.config.MQTT_BROKER_HOST, port=rt.config.MQTT_BROKER_PORT,
                                   auth={'username':rt.config.MQTT_USERNAME,'password':rt.config.MQTT_PASSWORD})
                try:
                    report['dashboard'] = check_dashboard(rt, report_dir, browser_publish)
                    print('PASS dashboard_browser_and_reconnect', flush=True)
                finally:
                    rt.api.post('/api/weather/alerts/threshold', json={'threshold':0.7}).raise_for_status()
                    assert rt.api.get('/api/weather/alerts/threshold').json()['threshold'] == 0.7
        report['cleanup'] = 'backend stopped; disposable database dropped; production topics and threshold untouched'
        report['status'] = 'passed'
        code = 0
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        print(f"FAIL {report['error']}", flush=True)
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['git_commit'] = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
        report['working_tree_modified'] = bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True).stdout)
        (report_dir / 'e2e.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(f'Report: {report_dir / "e2e.json"}', flush=True)
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dashboard', action='store_true')
    parser.add_argument('--backend-tests', action='store_true', help='Run the full backend suite in the same disposable DB, with TV2/TV3 imports blocked')
    parser.add_argument('--report-dir', type=Path, default=ROOT/'personal/tv1/verification'/datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    raise SystemExit(run_e2e_tests(args.report_dir.resolve(), args.dashboard, args.backend_tests))

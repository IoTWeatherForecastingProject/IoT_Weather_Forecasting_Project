"""Disposable PostgreSQL + backend, with MQTT namespace isolated from real stations."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
from app.config import Settings


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def isolated_backend(report_dir, integrated_models=False):
    config = Settings(_env_file=BACKEND / ".env")
    run_id = uuid.uuid4().hex[:12]
    database = "weather_e2e_" + run_id
    prefix = f"e2e/{run_id}/weather"
    admin = create_engine(config.DATABASE_URL, isolation_level="AUTOCOMMIT")
    database_url = make_url(config.DATABASE_URL).set(database=database)
    engine, server, created = None, None, False
    log = (report_dir / "backend.log").open("w", encoding="utf-8")
    try:
        with admin.connect() as db:
            db.exec_driver_sql(f'CREATE DATABASE "{database}"')
            created = True
        engine = create_engine(database_url)
        port = free_port()
        env = os.environ.copy()
        python_paths = [str(BACKEND), str(ROOT)]
        if not integrated_models:
            # Prove TV1 can boot/run with every TV2/TV3 import unavailable.
            # The guard exists only in this test subprocess.
            guard_dir = report_dir / 'no_external_modules'
            guard_dir.mkdir(exist_ok=True)
            (guard_dir / 'sitecustomize.py').write_text(
                "import importlib.abc, importlib.util, sys\n"
                "class NoExternalModules(importlib.abc.MetaPathFinder):\n"
                "    def find_spec(self, fullname, path=None, target=None):\n"
                "        if fullname.split('.')[0] in {'ml', 'ai_engine', 'inference', 'sensor_analytics', 'openweather_benchmark', 'rain_classification', 'temperature_forecasting', 'common'}:\n"
                "            raise ModuleNotFoundError('TV1 isolated run: external modules unavailable: ' + fullname)\n"
                "sys.meta_path.insert(0, NoExternalModules())\n"
                "try:\n"
                "    importlib.util.find_spec('inference')\n"
                "except ModuleNotFoundError:\n"
                "    print('TV1_EXTERNAL_IMPORT_GUARD_ACTIVE', flush=True)\n"
                "else:\n"
                "    raise RuntimeError('External import guard did not activate')\n",
                encoding='utf-8',
            )
            python_paths.insert(0, str(guard_dir))
        env['PYTHONPATH'] = os.pathsep.join(python_paths)
        env.update(DATABASE_URL=database_url.render_as_string(hide_password=False),
                   MQTT_BROKER_HOST=config.MQTT_BROKER_HOST, MQTT_BROKER_PORT=str(config.MQTT_BROKER_PORT),
                   MQTT_USERNAME=config.MQTT_USERNAME, MQTT_PASSWORD=config.MQTT_PASSWORD,
                   MQTT_CLIENT_ID=f"backend_e2e_{run_id}", MQTT_TOPIC_PREFIX=prefix,
                   MQTT_DATA_TOPIC=f"{prefix}/+/data", MQTT_ALERT_TOPIC=f"{prefix}/{{device_id}}/alert",
                   AUTO_MIGRATE="true", ENABLE_TELEGRAM_NOTIFICATIONS="false",
                   FORECAST_ENGINE_MODE="auto" if integrated_models else "heuristic",
                   ANALYTICS_ENGINE_MODE="auto" if integrated_models else "disabled",
                   ALERT_MONITOR_ENABLED="true",
                   ALERT_EVALUATION_INTERVAL_SECONDS="0.5", ALERT_COOLDOWN_SECONDS="180")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        server = subprocess.Popen(
            [sys.executable, "-u", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        base_url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base_url, timeout=30 if integrated_models else 5, trust_env=False) as api:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Isolated backend exited; inspect backend.log")
                try:
                    health = api.get("/api/health")
                    if (health.status_code == 200 and health.json()["mqtt_connected"]
                            and health.json()["database_connected"] and health.json()["alert_monitor_running"]):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise TimeoutError("Isolated backend did not become healthy")
            guard_active = 'TV1_EXTERNAL_IMPORT_GUARD_ACTIVE' in (report_dir / 'backend.log').read_text(encoding='utf-8')
            if guard_active == integrated_models:
                raise RuntimeError('Backend external import guard does not match the requested mode')
            yield SimpleNamespace(api=api, engine=engine, prefix=prefix, device=f"e2e_{run_id}",
                                  run_id=run_id, base_url=base_url, config=config,
                                  database=database, external_modules_blocked=guard_active,
                                  integrated_models=integrated_models, env=env)
    finally:
        if server is not None and server.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
            else:
                server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        log.close()
        if engine is not None:
            engine.dispose()
        if created:
            # This name is generated here and can never refer to the user's database.
            assert database.startswith("weather_e2e_") and len(database) == 24
            with admin.connect() as db:
                db.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                                "WHERE datname=:name AND pid <> pg_backend_pid()"), {"name": database})
                db.exec_driver_sql(f'DROP DATABASE "{database}"')
        admin.dispose()

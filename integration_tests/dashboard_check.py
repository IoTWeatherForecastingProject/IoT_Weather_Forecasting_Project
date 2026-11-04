"""Browser checks against the same isolated backend after core E2E passes."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading


def check_dashboard(runtime, report_dir, publish):
    from playwright.sync_api import sync_playwright, expect

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(
        Handler, directory=str(Path(__file__).resolve().parents[1] / "dashboard")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    failures, errors = [], []
    try:
        with sync_playwright() as browser_runtime:
            browser = browser_runtime.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: failures.append({"url": response.url, "status": response.status})
                        if "/api/weather/" in response.url and response.status >= 400 else None)
                page.goto(f"http://127.0.0.1:{server.server_port}/?api={runtime.base_url}&device={runtime.device}",
                          wait_until="domcontentloaded", timeout=45000)
                expect(page.locator("#connection-status")).to_have_text("WS CONNECTED", timeout=20000)
                expect(page.locator("#fc-src-10")).to_have_text("HEURISTIC", timeout=15000)
                expect(page.locator("#threshold-applied")).to_contain_text("70%", timeout=15000)
                expect(page.locator("#alert-banner")).to_be_visible(timeout=15000)
                expect(page.locator("#alert-title")).to_contain_text("XÁC SUẤT ĐẠT NGƯỠNG")
                # A previous threshold read can be stale. The alert must show
                # the threshold used by this forecast, rather than browser state.
                page.evaluate("async () => { state.threshold = 0.01; await fetchForecast(); }")
                expect(page.locator("#alert-message")).to_contain_text("ngưỡng 70%")
                page.evaluate("loadThreshold()")
                publish(temperature=30.1)
                expect(page.locator("#card-temp")).to_have_text("30.1", timeout=10000)
                page.locator("#threshold-slider").evaluate(
                    "el => { el.value='65'; el.dispatchEvent(new Event('input', {bubbles:true})); }"
                )
                page.locator("#btn-save-threshold").click()
                expect(page.locator("#threshold-status")).to_contain_text("thành công", timeout=10000)
                assert runtime.api.get("/api/weather/alerts/threshold").json()["threshold"] == 0.65
                page.evaluate("window.oldSocket = state.ws; state.ws.close()")
                page.wait_for_function("state.ws !== window.oldSocket && state.ws.readyState === 1", timeout=15000)
                page.screenshot(path=str(report_dir / "dashboard_desktop.png"), full_page=True)
                mobile = browser.new_page(viewport={"width": 390, "height": 844})
                mobile.on("pageerror", lambda error: errors.append(str(error)))
                mobile.goto(page.url, wait_until="domcontentloaded", timeout=45000)
                expect(mobile.locator("#connection-status")).to_have_text("WS CONNECTED", timeout=20000)
                expect(mobile.locator("#card-temp")).to_have_text("30.1", timeout=15000)
                expect(mobile.locator("#fc-src-10")).to_have_text("HEURISTIC", timeout=15000)
                mobile.wait_for_function(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1", timeout=5000
                )
                mobile.screenshot(path=str(report_dir / "dashboard_mobile.png"), full_page=True)
                assert not failures, f"Dashboard API errors: {failures}"
                assert not errors, f"Dashboard JS errors: {errors}"
                return {"status": "passed", "api_errors": failures, "javascript_errors": errors,
                        "websocket_reconnect": True, "threshold_write": True,
                        "forecast_threshold_display": True,
                        "alert_describes_probability_decision": True,
                        "screenshots": ["dashboard_desktop.png", "dashboard_mobile.png"]}
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

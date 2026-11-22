const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(ids.length, new Set(ids).size, "HTML contains duplicate IDs");

function element() {
    const classes = new Set();
    const use = { href: "", setAttribute(_, value) { this.href = value; } };
    return {
        textContent: "", className: "", dataset: {}, style: {}, children: [],
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        classList: {
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
            contains(name) { return classes.has(name); },
        },
        querySelector() { return use; },
        get use() { return use; },
    };
}

const nodes = new Map(ids.map((id) => [id, element()]));
const context = vm.createContext({
    window: { location: { search: "", protocol: "http:", hostname: "localhost" } },
    document: { documentElement: { dataset: { view: "forecast" } }, getElementById: (id) => nodes.get(id), createElement: () => element(), addEventListener() {} },
    URLSearchParams, URL, Date, Number, Math, Object, String, console,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "app.js"), "utf8"), context);
const run = (source) => vm.runInContext(source, context);

run(`state.latestForecast = {generated_at: new Date().toISOString(), plus_10m:{rain_probability:0.82}, plus_30m:{rain_probability:0.3}, plus_60m:{rain_probability:0.5}};`);
run(`renderHorizon("10", {temperature_c:31.2,rain_probability:0.82,rain_source:"heuristic"});`);
assert.equal(nodes.get("fc-rain-10").textContent, "82%");
assert.equal(nodes.get("fc-card-10").dataset.risk, "high");
assert.equal(nodes.get("fc-src-10").textContent, "ƯỚC TÍNH");
assert.equal(nodes.get("fc-icon-10").use.href, "#i-rain");
assert.equal(nodes.get("fc-temp-10").textContent, "31.2 °C");

run(`state.latestForecast.forecast_scope = "VVTS";
renderHorizon("10", {temperature_c:null, rain_probability:null, rain_source:"unavailable"});
renderHorizon("60", {temperature_c:30, rain_probability:0.12, rain_source:"model", valid_at:"2026-11-15T09:30:00Z"});`);
assert.equal(nodes.get("fc-rain-10").textContent, "--%");
assert.equal(nodes.get("fc-time-10").textContent, "--:--");
assert.equal(nodes.get("fc-src-60").textContent, "TÂN SƠN NHẤT");
assert.equal(nodes.get("fc-rain-60").textContent, "12%");
run(`delete state.latestForecast.forecast_scope;`);

run(`renderHorizon("30", {temperature_c:null,rain_probability:null});`);
assert.equal(nodes.get("fc-rain-30").textContent, "--%");
assert.equal(nodes.get("fc-card-30").dataset.risk, "unknown");
assert.equal(nodes.get("fc-temp-30").textContent, "--");

run(`renderHorizon("10", {temperature_c:31.2, temperature_source:"persistence", rain_probability:null,
    issue:"observations_unavailable", history_available_minutes:15, history_required_minutes:30});`);
assert.equal(nodes.get("fc-risk-10").textContent, "Đã có 15/30 phút số đo liên tục");
assert.equal(nodes.get("fc-temp-10").children.at(-1).textContent, "Tạm dùng nhiệt độ mới nhất");

run(`updateTelemetryCards({timestamp:new Date().toISOString(),temperature:30.1,humidity:76,pressure:1008,rain_detected:0,rain_raw:3570});`);
assert.equal(nodes.get("card-temp").textContent, "30.1");
assert.equal(nodes.get("hero-rain-short").textContent, "Chưa mưa");
assert.match(nodes.get("hero-summary").textContent, /82%/);
run(`state.lastSampleAt = Date.now() - 60_000; renderWeatherSummary();`);
assert.equal(nodes.get("hero-freshness").textContent, "Dữ liệu đã cũ");
assert.match(nodes.get("hero-summary").textContent, /lần cập nhật cuối/);

run(`state.lastSampleAt = Date.now(); state.latestMeasurement = {temperature:30.1,humidity:76,pressure:1008};
renderHealth({status:"WARNING",checked_at:new Date().toISOString(),anomalies:[{type:"FROZEN_VALUE",sensor:"pressure"}]}, "Đã kiểm tra");`);
const components = nodes.get("health-list").children;
assert.equal(components.length, 4);
const byName = (name) => components.find((row) => row.children[0].children[0].textContent === name);
assert.equal(byName("BMP280").dataset.level, "warning");
assert.equal(byName("DHT11").dataset.level, "observed");
assert.equal(byName("Cảm biến mưa").dataset.level, "observed");
run(`renderHealth(null, "Không tải được");`);
assert.equal(nodes.get("health-list").children.find((row) => row.children[0].children[0].textContent === "BMP280").dataset.level, "observed");
console.log("Dashboard UI state checks passed");

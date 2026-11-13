/**
 * ==============================================================================
 * DỰ ÁN: IOT LOCAL WEATHER MONITORING & FORECASTING
 * MODULE 4: FRONTEND SCADA DASHBOARD APP LOGIC
 * Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
 * Các Task: SA-05, SA-06 (TASK.md)
 * ==============================================================================
 *
 * Nguyên tắc: chỉ hiển thị dữ liệu thật từ Backend. Khi Backend/endpoint chưa sẵn
 * sàng, giao diện hiện "--" hoặc trạng thái chờ, KHÔNG sinh số giả.
 * Mọi dữ liệu từ server được gán bằng textContent (không innerHTML) để tránh XSS.
 *
 * Tham số URL (tùy chọn):
 *   ?api=http://192.168.1.10:8000   địa chỉ Backend (mặc định: cùng host, cổng 8000)
 *   ?device=station01               mã trạm cần theo dõi
 */

const params = new URLSearchParams(window.location.search);
const API_ORIGIN = (params.get("api") ||
    `${window.location.protocol === "https:" ? "https" : "http"}://${window.location.hostname || "localhost"}:8000`
).replace(/\/+$/, "");

const CONFIG = {
    API_BASE: `${API_ORIGIN}/api/weather`,
    WS_URL: `${API_ORIGIN.replace(/^http/, "ws")}/ws/weather/live`,
    DEVICE_ID: params.get("device") || "station01",
    REF_SOURCE: "open-meteo-15min",              // khớp crawler --once/--loop
    HISTORY_WINDOW_MS: 2 * 60 * 60 * 1000,      // biểu đồ giữ 2 giờ gần nhất
    HISTORY_PAGE_SIZE: 1000,                     // giới hạn của GET /history
    FORECAST_INTERVAL_MS: 15000,
    HEALTH_INTERVAL_MS: 30000,
    BENCHMARK_INTERVAL_MS: 10 * 60 * 1000,
    CHART_REDRAW_MS: 1000,                       // gom điểm WS, vẽ lại tối đa 1 lần/giây
    CHART_MIN_SPAN_MS: 30000,
    WS_BACKOFF_MAX_MS: 30000,
    WS_CONNECT_TIMEOUT_MS: 8000,
    LIVE_DATA_TIMEOUT_MS: 30000,
    PRESSURE_TREND_HPA_PER_H: 1.0,
    THRESHOLD_MIN: 0.40,
    THRESHOLD_MAX: 0.95,
};

const VARIABLES = {
    temperature: { label: "Nhiệt độ", unit: "°C", digits: 1 },
    humidity: { label: "Độ ẩm", unit: "%", digits: 1 },
    pressure: { label: "Áp suất", unit: "hPa", digits: 1 },
};

const state = {
    ws: null,
    wsStatus: "connecting",
    wsOpenedAt: 0,
    lastSampleAt: null,
    wsRetryMs: 1000,
    chart: null,
    chartVar: "temperature",
    chartDirty: false,
    chartRange: null,
    chartExtent: null,
    points: [],          // [{t, temperature, humidity, pressure}] tăng dần theo t
    reference: [],       // dữ liệu tham chiếu của đúng một source/cadence
    benchmarkReady: null, // null: chưa biết, false: endpoint chưa có
    threshold: null,
    historyFailed: false,
    historyLoading: true,
    failures: {},        // đếm lỗi theo loại request để hiện trạng thái Backend
};

const $ = (id) => document.getElementById(id);

// --- Tiện ích -------------------------------------------------------------------

function isNum(v) {
    return typeof v === "number" && Number.isFinite(v);
}

function fmt(v, digits = 1, suffix = "") {
    const n = Number(v);
    return v !== null && v !== undefined && Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "--";
}

function setText(id, text, className) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    if (className !== undefined) el.className = className;
}

function toMs(ts) {
    const ms = Date.parse(ts);
    return Number.isFinite(ms) ? ms : null;
}

function timeLabel(ms) {
    return new Date(ms).toLocaleTimeString("vi-VN", { hour12: false });
}

function rainTimeLabel(ms) {
    const date = new Date(ms);
    return `${timeLabel(ms)} · ${date.toLocaleDateString("vi-VN")}`;
}

/** 404/405: Backend chưa có endpoint (hoặc chỉ có method khác), khác với lỗi mạng. */
function isMissingEndpoint(err) {
    return err instanceof HttpError && (err.status === 404 || err.status === 405);
}

class HttpError extends Error {
    constructor(status, detail) {
        super(`HTTP ${status}`);
        this.status = status;
        this.detail = detail;
    }
}

async function apiGet(path, query = {}) {
    const url = new URL(`${CONFIG.API_BASE}${path}`);
    Object.entries(query).forEach(([k, v]) => {
        if (v !== null && v !== undefined) url.searchParams.set(k, v);
    });
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
        let detail = null;
        try { detail = (await res.json()).detail; } catch (_) { /* body không phải JSON */ }
        throw new HttpError(res.status, detail);
    }
    return res.json();
}

/** Ghi nhận kết quả từng loại request; hiện cờ MẤT KẾT NỐI khi lỗi mạng. */
function markBackend(kind, ok, err) {
    // HTTP 4xx/5xx nghĩa là Backend vẫn trả lời; chỉ lỗi mạng mới tính là mất kết nối
    const networkError = !ok && !(err instanceof HttpError);
    state.failures[kind] = networkError;
    const down = Object.values(state.failures).some(Boolean);
    $("backend-status").classList.toggle("hidden", !down);
}

// --- 1. Đồng hồ -----------------------------------------------------------------

function initClock() {
    const tick = () => {
        setText("live-clock", `${timeLabel(Date.now())} (Local)`);
        updateLiveDataWarning();
    };
    tick();
    setInterval(tick, 1000);
}

// --- 2. Biểu đồ -----------------------------------------------------------------

function clampChartRange({ min, max }) {
    const extent = state.chartExtent;
    if (!extent) return { min, max };
    const width = extent.max - extent.min;
    const span = Math.min(width, Math.max(CONFIG.CHART_MIN_SPAN_MS, max - min));
    const center = (min + max) / 2;
    const start = Math.max(extent.min, Math.min(center - span / 2, extent.max - span));
    return { min: start, max: start + span };
}

function initChartNavigation(chartElement) {
    let spaceHeld = false;
    let drag = null;
    let frame = 0;

    function showRange(range) {
        const extent = state.chartExtent;
        if (!extent) return;
        const next = range ? clampChartRange(range) : extent;
        state.chartRange = next.min === extent.min && next.max === extent.max ? null : next;
        if (frame) return;
        frame = requestAnimationFrame(() => {
            frame = 0;
            if (state.chartExtent)
                state.chart.updateOptions({ xaxis: state.chartRange || state.chartExtent }, false, false);
        });
    }

    chartElement.addEventListener("wheel", (event) => {
        const plot = chartElement.querySelector(".apexcharts-grid")?.getBoundingClientRect();
        const range = state.chartRange || state.chartExtent;
        if (!plot?.width || !range || drag || !event.deltaY ||
            event.clientX < plot.left || event.clientX > plot.right ||
            event.clientY < plot.top || event.clientY > plot.bottom) return;
        event.preventDefault();
        const fraction = (event.clientX - plot.left) / plot.width;
        const span = range.max - range.min;
        const anchor = range.min + span * fraction;
        const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 120 : 1);
        const nextSpan = Math.max(CONFIG.CHART_MIN_SPAN_MS, Math.min(
            state.chartExtent.max - state.chartExtent.min,
            span * Math.exp(Math.max(-1, Math.min(1, delta * 0.002)))
        ));
        showRange({ min: anchor - nextSpan * fraction, max: anchor + nextSpan * (1 - fraction) });
    }, { passive: false });

    function releaseSpace() {
        spaceHeld = false;
        chartElement.classList.remove("chart-pan-ready");
        if (drag && chartElement.hasPointerCapture(drag.pointerId))
            chartElement.releasePointerCapture(drag.pointerId);
        drag = null;
        chartElement.classList.remove("chart-panning");
    }

    document.addEventListener("keydown", (event) => {
        if (event.code !== "Space" ||
            event.target.closest?.("input, textarea, select, [contenteditable]") ||
            (!chartElement.matches(":hover") && document.activeElement !== chartElement)) return;
        event.preventDefault();
        spaceHeld = true;
        chartElement.classList.add("chart-pan-ready");
    });
    document.addEventListener("keyup", (event) => {
        if (event.code === "Space" && spaceHeld) releaseSpace();
    });
    window.addEventListener("blur", releaseSpace);

    chartElement.addEventListener("pointerdown", (event) => {
        const plot = chartElement.querySelector(".apexcharts-grid")?.getBoundingClientRect();
        const range = state.chartRange || state.chartExtent;
        if (!spaceHeld || event.button !== 0 || !range || !plot?.width ||
            event.clientX < plot.left || event.clientX > plot.right ||
            event.clientY < plot.top || event.clientY > plot.bottom) return;
        event.preventDefault();
        chartElement.setPointerCapture(event.pointerId);
        drag = { pointerId: event.pointerId, x: event.clientX, range, width: plot.width };
        chartElement.classList.add("chart-panning");
    });
    chartElement.addEventListener("pointermove", (event) => {
        if (drag?.pointerId !== event.pointerId) return;
        const { min, max } = drag.range;
        const shift = (drag.x - event.clientX) * (max - min) / drag.width;
        showRange({ min: min + shift, max: max + shift });
    });
    chartElement.addEventListener("lostpointercapture", () => {
        drag = null;
        chartElement.classList.remove("chart-panning");
    });
    $("chart-reset-view").addEventListener("click", () => showRange(null));
}

function initChart() {
    const chartElement = $("weather-chart");
    state.chart = new ApexCharts(chartElement, {
        chart: {
            type: "line",
            height: 288,
            background: "transparent",
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: false },
        },
        theme: { mode: "dark" },
        stroke: { curve: "straight", width: [2, 2] },
        markers: { size: [0, 4] },
        colors: ["#06b6d4", "#f59e0b"],
        series: [],
        noData: { text: "Chưa có dữ liệu", style: { color: "#94a3b8" } },
        xaxis: {
            type: "datetime",
            tooltip: { enabled: false },
            labels: {
                datetimeUTC: false,
                style: { colors: "#64748b", fontSize: "11px", fontFamily: "JetBrains Mono" },
            },
        },
        yaxis: {
            decimalsInFloat: 1,
            labels: { style: { colors: "#64748b", fontSize: "11px", fontFamily: "JetBrains Mono" } },
        },
        grid: { borderColor: "#1e293b", strokeDashArray: 4 },
        legend: { position: "top", horizontalAlign: "right", labels: { colors: "#cbd5e1" } },
        tooltip: {
            theme: "dark",
            shared: false,
            intersect: false,
            followCursor: true,
            x: { format: "HH:mm:ss dd/MM" },
        },
    });
    state.chart.render();
    initChartNavigation(chartElement);
    const positionTooltip = (event) => {
        const tooltip = chartElement.querySelector(".apexcharts-tooltip");
        if (!tooltip?.offsetParent) return;
        // ApexCharts 3 can anchor a non-shared tooltip to the series rather than
        // the cursor when series have different timestamps. Position its box here.
        const bounds = tooltip.offsetParent.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const gap = 10;
        const left = x + gap + tooltip.offsetWidth <= bounds.width
            ? x + gap : Math.max(0, x - gap - tooltip.offsetWidth);
        const top = y + gap + tooltip.offsetHeight <= bounds.height
            ? y + gap : Math.max(0, y - gap - tooltip.offsetHeight);
        tooltip.style.setProperty("--cursor-left", `${left}px`);
        tooltip.style.setProperty("--cursor-top", `${top}px`);
        tooltip.classList.add("cursor-positioned");
    };
    chartElement.addEventListener("mousemove", positionTooltip);
    chartElement.addEventListener("pointerdown", positionTooltip);

    document.querySelectorAll(".chart-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.chartVar = btn.dataset.var;
            renderChart();
        });
    });
    setInterval(() => {
        if (state.chartDirty) renderChart();
    }, CONFIG.CHART_REDRAW_MS);
}

function renderChart() {
    state.chartDirty = false;
    const v = state.chartVar;
    const meta = VARIABLES[v];
    document.querySelectorAll(".chart-tab").forEach((btn) => {
        btn.setAttribute("aria-selected", String(btn.dataset.var === v));
    });

    const start = Date.now() - CONFIG.HISTORY_WINDOW_MS;
    const iot = state.points.filter((p) => p.t >= start && isNum(p[v])).map((p) => [p.t, p[v]]);
    const ref = state.reference.filter((p) => p.t >= start && isNum(p[v])).map((p) => [p.t, p[v]]);

    const nonEmptySeries = [iot, ref].filter((series) => series.length);
    state.chartExtent = null;
    if (nonEmptySeries.length) {
        const first = Math.min(...nonEmptySeries.map((series) => series[0][0]));
        const last = Math.max(...nonEmptySeries.map((series) => series[series.length - 1][0]));
        state.chartExtent = { min: first, max: Math.max(first + CONFIG.CHART_MIN_SPAN_MS, last) };
    }
    if (state.chartRange && state.chartExtent) state.chartRange = clampChartRange(state.chartRange);
    const xaxis = state.chartRange && state.chartExtent
        ? clampChartRange(state.chartRange)
        : state.chartExtent || { min: undefined, max: undefined };

    let min, max, tickAmount;
    if (v === "temperature") {
        // Center on the typical station reading. Round the center to 2°C
        // steps and keep at least 16°C of span to avoid zooming into noise.
        const temperatures = iot.map(([, temperature]) => temperature).sort((a, b) => a - b);
        const middle = Math.floor(temperatures.length / 2);
        const median = temperatures.length
            ? (temperatures[middle] + temperatures[Math.floor((temperatures.length - 1) / 2)]) / 2
            : 32;
        const center = 2 * Math.round(median / 2);
        let halfSpan = 8;
        for (const series of [iot, ref]) {
            for (const [, temperature] of series) {
                halfSpan = Math.max(halfSpan, 4 * Math.ceil((Math.abs(temperature - center) + 1) / 4));
            }
        }
        min = center - halfSpan;
        max = center + halfSpan;
        tickAmount = 4;
    }

    state.chart.updateOptions({
        xaxis,
        series: [
            { name: `Trạm IoT (${meta.unit})`, data: iot },
            { name: `Tham chiếu Open-Meteo (${meta.unit})`, data: ref },
        ],
        yaxis: {
            min,
            max,
            tickAmount,
            decimalsInFloat: 1,
            title: { text: `${meta.label} (${meta.unit})`, style: { color: "#94a3b8" } },
            labels: { style: { colors: "#64748b", fontSize: "11px", fontFamily: "JetBrains Mono" } },
        },
    }, false, false);

    let note = state.historyFailed && !iot.length
        ? "Không tải được lịch sử từ Backend"
        : `${iot.length} điểm IoT trong 2 giờ gần nhất`;
    if (state.benchmarkReady === false) note += " · chưa có endpoint đối chuẩn /benchmark";
    else if (state.benchmarkReady) note += ref.length
        ? ` · ${ref.length} điểm Open-Meteo`
        : " · Chưa có dữ liệu Open-Meteo trong 2 giờ gần nhất";
    setText("chart-note", note);
    renderRainHistory();
}

function renderRainHistory() {
    const now = Date.now();
    const start = now - CONFIG.HISTORY_WINDOW_MS;
    const events = [];
    let previous = null;
    let event = null;
    let hasRainReadings = false;
    for (const point of state.points) {
        if (point.t > now) break;
        if (point.t < start) {
            previous = point;
            continue;
        }
        if (point.raining !== null) hasRainReadings = true;
        if (event && (point.t - event.lastWet.t > CONFIG.LIVE_DATA_TIMEOUT_MS || point.raining === null)) {
            event.interrupted = true;
            event = null;
        }
        if (point.raining === true) {
            if (!event) {
                event = { firstWet: point, lastWet: point, dryAt: null, interrupted: false,
                    hasDryBefore: previous?.raining === false && point.t - previous.t <= CONFIG.LIVE_DATA_TIMEOUT_MS };
                events.push(event);
            }
            event.lastWet = point;
        } else if (point.raining === false && event) {
            event.dryAt = point.t;
            event = null;
        }
        previous = point;
    }

    const list = $("rain-history-list");
    const items = events.reverse().map(({ firstWet, lastWet, dryAt, interrupted, hasDryBefore }) => {
        const item = document.createElement("li");
        item.className = "rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm";
        const time = document.createElement("p");
        time.className = "font-semibold text-slate-100";
        time.textContent = `${hasDryBefore ? "Chuyển sang ướt" : "Ghi nhận ướt"} lúc ${rainTimeLabel(firstWet.t)}`;
        const readings = document.createElement("p");
        readings.className = "mt-1 font-mono text-cyan-300";
        readings.textContent = [
            `Nhiệt độ ${fmt(firstWet.temperature, 1, " °C")}`,
            `Độ ẩm ${fmt(firstWet.humidity, 1, "%")}`,
            `Áp suất ${fmt(firstWet.pressure, 1, " hPa")}`,
        ].join(" · ");
        const end = document.createElement("p");
        end.className = "mt-1 text-xs text-slate-400";
        if (dryAt !== null) {
            end.textContent = `Ghi nhận khô lại lúc ${rainTimeLabel(dryAt)}`;
        } else if (interrupted || now - lastWet.t > CONFIG.LIVE_DATA_TIMEOUT_MS) {
            end.textContent = `Mẫu ướt cuối lúc ${rainTimeLabel(lastWet.t)}. Chưa rõ lúc khô lại.`;
        } else {
            end.textContent = "Tấm dò vẫn báo ướt";
        }
        item.append(time, readings, end);
        return item;
    });
    list.replaceChildren(...items);

    let note = "Chưa có số đo mưa trong 2 giờ gần nhất.";
    if (state.historyLoading) note = "Đang tải lịch sử…";
    else if (state.historyFailed) note = "Không tải đủ lịch sử. Danh sách hiển thị các mẫu đã nhận.";
    else if (items.length) note = `${items.length} lần ghi nhận tấm dò ướt`;
    else if (hasRainReadings) note = "Tấm dò chưa báo ướt trong các mẫu đã lưu.";
    setText("rain-history-note", note);
}

function addPoint(record) {
    const t = toMs(record.timestamp);
    if (t === null) return;
    const point = {
        t,
        raining: record.rain_detected === 1 ? true : record.rain_detected === 0 ? false : null,
    };
    for (const v of Object.keys(VARIABLES)) {
        const n = Number(record[v]);
        point[v] = record[v] !== null && record[v] !== undefined && Number.isFinite(n) ? n : null;
    }
    const last = state.points[state.points.length - 1];
    if (!last || t > last.t) {
        state.points.push(point);
    } else if (t !== last.t && !state.points.some((p) => p.t === t)) {
        state.points.push(point);
        state.points.sort((a, b) => a.t - b.t);
    }
    // Giữ thêm 10 phút ngoài cửa sổ hiển thị để tính xu hướng áp suất 60 phút
    const keepFrom = Date.now() - CONFIG.HISTORY_WINDOW_MS - 10 * 60 * 1000;
    while (state.points.length && state.points[0].t < keepFrom) state.points.shift();
    state.chartDirty = true;
}

async function loadHistory() {
    const start = new Date(Date.now() - CONFIG.HISTORY_WINDOW_MS).toISOString();
    try {
        // /history trả tối đa 1000 bản ghi MỚI NHẤT mỗi trang -> lấy thêm trang để phủ đủ 2 giờ
        for (let offset = 0; offset < 10 * CONFIG.HISTORY_PAGE_SIZE; offset += CONFIG.HISTORY_PAGE_SIZE) {
            const rows = await apiGet("/history", {
                device_id: CONFIG.DEVICE_ID,
                start_time: start,
                limit: CONFIG.HISTORY_PAGE_SIZE,
                offset,
            });
            rows.forEach(addPoint);
            if (rows.length < CONFIG.HISTORY_PAGE_SIZE) break;
        }
        state.historyFailed = false;
        markBackend("history", true);
    } catch (err) {
        state.historyFailed = true;
        markBackend("history", false, err);
    } finally {
        state.historyLoading = false;
        updatePressureTrend();
        renderChart();
    }
}

// --- 3. Thẻ chỉ số --------------------------------------------------------------

function updateTelemetryCards(data) {
    const timestamp = toMs(data.timestamp);
    if (timestamp === null || (state.lastSampleAt !== null && timestamp < state.lastSampleAt)) return;
    state.lastSampleAt = timestamp;
    updateLiveDataWarning();
    setText("card-temp", fmt(data.temperature, 1));
    setText("card-press", fmt(data.pressure, 1));
    setText("card-hum", fmt(data.humidity, 1));
    const hum = Number(data.humidity);
    $("bar-hum").style.width = Number.isFinite(hum) ? `${Math.min(Math.max(hum, 0), 100)}%` : "0%";
    setText("card-rain-raw", isNum(Number(data.rain_raw)) && data.rain_raw !== null ? String(data.rain_raw) : "----");

    if (data.rain_detected === 1 || data.rain_detected === 0) {
        if (data.rain_detected === 1) {
            setText("card-rain-status", "ĐANG MƯA", "text-2xl font-bold font-mono text-rose-500 animate-pulse");
        } else {
            setText("card-rain-status", "KHÔ RÁO", "text-2xl font-bold font-mono text-emerald-400");
        }
    } else {
        setText("card-rain-status", "--", "text-2xl font-bold font-mono text-slate-500");
    }
}

function clearTelemetryCards(label) {
    ["card-temp", "card-hum", "card-press"].forEach((id) => setText(id, "--.-"));
    $("bar-hum").style.width = "0%";
    setText("card-rain-raw", "----");
    setText("card-rain-status", label, "text-2xl font-bold font-mono text-slate-500");
}

/** Xu hướng áp suất: ΔP giữa điểm mới nhất và điểm cách ~60 phút, quy về hPa/giờ. */
function updatePressureTrend() {
    const pts = state.points.filter((p) => isNum(p.pressure));
    const last = pts[pts.length - 1];
    if (!last) return setText("trend-press", "--", "font-mono text-slate-500");
    const target = last.t - 60 * 60 * 1000;
    const base = pts.find((p) => p.t >= target);
    const spanH = base ? (last.t - base.t) / 3600000 : 0;
    if (!base || spanH < 0.75) {
        return setText("trend-press", "Chưa đủ 60 phút", "font-mono text-slate-500");
    }
    const rate = (last.pressure - base.pressure) / spanH;
    const label = `${rate >= 0 ? "+" : ""}${rate.toFixed(1)} hPa/h`;
    if (rate <= -CONFIG.PRESSURE_TREND_HPA_PER_H) {
        setText("trend-press", `Đang giảm ${label}`, "font-mono text-amber-400");
    } else if (rate >= CONFIG.PRESSURE_TREND_HPA_PER_H) {
        setText("trend-press", `Đang tăng ${label}`, "font-mono text-cyan-400");
    } else {
        setText("trend-press", `Ổn định ${label}`, "font-mono text-emerald-400");
    }
}

async function fetchCurrent() {
    try {
        const data = await apiGet("/current", { device_id: CONFIG.DEVICE_ID });
        markBackend("current", true);
        // Backend trả giá trị mẫu kèm status="waiting_data" khi DB trống -> không hiển thị
        if (data.status === "waiting_data") {
            if (state.lastSampleAt === null) clearTelemetryCards("CHỜ DỮ LIỆU");
            return;
        }
        updateTelemetryCards(data);
        addPoint(data);
    } catch (err) {
        markBackend("current", false, err);
        if (state.lastSampleAt === null) clearTelemetryCards("--");
    }
}

// --- 4. WebSocket ---------------------------------------------------------------

function updateLiveDataWarning() {
    let message = "";
    if (state.wsStatus === "reconnecting") {
        message = "Mất kết nối trực tiếp. Đang tự kết nối lại.";
    } else if (state.wsStatus === "connected" &&
        Date.now() - (state.lastSampleAt ?? state.wsOpenedAt) > CONFIG.LIVE_DATA_TIMEOUT_MS) {
        message = "Không nhận được số đo mới từ trạm trong hơn 30 giây.";
    }
    if (message && state.lastSampleAt !== null) {
        message += ` Số đo gần nhất lúc ${timeLabel(state.lastSampleAt)}.`;
    }
    const warning = $("live-data-warning");
    if (warning.textContent !== message) {
        warning.textContent = message;
        if (state.lastSampleAt !== null) state.chartDirty = true;
    }
    warning.classList.toggle("hidden", !message);
}

function setWsStatus(kind) {
    const styles = {
        connecting: ["ĐANG KẾT NỐI…", "text-amber-400", "bg-amber-500", false],
        connected: ["WS CONNECTED", "text-emerald-400", "bg-emerald-500", true],
        reconnecting: ["MẤT KẾT NỐI", "text-rose-400", "bg-rose-500", false],
    }[kind];
    state.wsStatus = kind;
    updateLiveDataWarning();
    setText("connection-status", styles[0], styles[1]);
    $("status-dot").className = `relative inline-flex rounded-full h-2.5 w-2.5 ${styles[2]}`;
    $("status-ping").className = styles[3]
        ? "pulse-indicator absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"
        : "hidden";
}

function connectWebSocket() {
    setWsStatus(state.ws ? "reconnecting" : "connecting");
    let ws;
    try {
        ws = new WebSocket(CONFIG.WS_URL);
    } catch (e) {
        setWsStatus("reconnecting");
        scheduleReconnect();
        return;
    }
    state.ws = ws;
    const timeout = setTimeout(() => {
        if (ws.readyState === WebSocket.CONNECTING) ws.close();
    }, CONFIG.WS_CONNECT_TIMEOUT_MS);

    ws.onopen = () => {
        clearTimeout(timeout);
        state.wsRetryMs = 1000;
        state.wsOpenedAt = Date.now();
        setWsStatus("connected");
    };
    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (err) {
            console.warn("WS payload khong hop le:", err);
            return;
        }
        if (data.device_id && data.device_id !== CONFIG.DEVICE_ID) return;
        updateTelemetryCards(data);
        addPoint(data);
        updatePressureTrend();
    };
    ws.onclose = () => {
        clearTimeout(timeout);
        setWsStatus("reconnecting");
        scheduleReconnect();
    };
    // onerror luôn được theo sau bởi onclose -> không reconnect ở đây để tránh kết nối đôi
    ws.onerror = () => {};
}

function scheduleReconnect() {
    const delay = state.wsRetryMs;
    state.wsRetryMs = Math.min(state.wsRetryMs * 2, CONFIG.WS_BACKOFF_MAX_MS);
    setTimeout(connectWebSocket, delay);
}

// --- 5. Đối chuẩn tham chiếu ----------------------------------------------------

async function fetchBenchmark() {
    try {
        const data = await apiGet("/benchmark", {
            device_id: CONFIG.DEVICE_ID, source: CONFIG.REF_SOURCE, hours: 24,
        });
        state.benchmarkReady = true;
        markBackend("benchmark", true);
        state.reference = (data.reference || [])
            .map((r) => ({ ...r, t: toMs(r.timestamp) }))
            .filter((r) => r.t !== null)
            .sort((a, b) => a.t - b.t);
        const bias = data.latest_bias;
        if (bias && isNum(Number(bias.temp_bias_c)) && bias.temp_bias_c !== null) {
            const b = Number(bias.temp_bias_c);
            setText("bias-temp", `${b > 0 ? "+" : ""}${b.toFixed(1)}°C`, "font-mono text-cyan-400");
        } else {
            setText("bias-temp", "N/A", "font-mono text-slate-500");
        }
    } catch (err) {
        markBackend("benchmark", false, err);
        state.benchmarkReady = isMissingEndpoint(err) ? false : state.benchmarkReady;
        setText("bias-temp", "N/A", "font-mono text-slate-500");
    }
    state.chartDirty = true;
}

// --- 6. Sức khỏe cảm biến (SA-03) -----------------------------------------------

const HEALTH_STYLES = {
    OK: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    WARNING: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    FAULT: "bg-rose-500/10 text-rose-400 border-rose-500/30",
    UNKNOWN: "bg-slate-800 text-slate-400 border-slate-700",
};

const HEALTH_UNKNOWN_REASONS = {
    analytics_not_integrated: "Phân tích sức khỏe cảm biến đang tắt",
    analytics_unavailable: "Bộ phân tích cảm biến chưa sẵn sàng",
    analytics_failed: "Không phân tích được số đo cảm biến",
    stale_data: "Dữ liệu trạm đã cũ",
};

function renderHealth(status, anomalies, note) {
    const key = HEALTH_STYLES[status] ? status : "UNKNOWN";
    setText("health-badge", key, `text-xs font-mono font-bold px-2.5 py-1 rounded-full border ${HEALTH_STYLES[key]}`);
    const list = $("health-list");
    list.replaceChildren();
    (anomalies || []).forEach((a) => {
        const li = document.createElement("li");
        li.className = "flex flex-wrap gap-2 items-baseline p-2 rounded-lg bg-slate-900/60 border border-slate-800";
        const type = document.createElement("span");
        type.className = "font-mono text-xs font-bold text-amber-400";
        type.textContent = String(a.type || "ANOMALY");
        const sensor = document.createElement("span");
        sensor.className = "font-mono text-xs text-cyan-400";
        sensor.textContent = String(a.sensor || "");
        const msg = document.createElement("span");
        msg.className = "text-slate-300 text-xs";
        msg.textContent = String(a.message || "");
        li.append(type, sensor, msg);
        list.appendChild(li);
    });
    setText("health-note", note);
}

async function fetchSensorHealth() {
    try {
        const data = await apiGet("/sensor-health", { device_id: CONFIG.DEVICE_ID, window_minutes: 360 });
        markBackend("health", true);
        const n = (data.anomalies || []).length;
        const checked = toMs(data.checked_at);
        const when = checked ? ` · bản ghi lúc ${timeLabel(checked)}` : "";
        let note = n ? `${n} dị thường` : "Không phát hiện dị thường";
        if (data.status === "UNKNOWN") {
            note = data.reason === "no_data"
                ? `Chưa có dữ liệu đo trong ${data.window_minutes || 360} phút gần nhất`
                : HEALTH_UNKNOWN_REASONS[data.reason] || "Chưa đánh giá được sức khỏe cảm biến";
        }
        renderHealth(data.status, data.anomalies, note + when);
    } catch (err) {
        markBackend("health", false, err);
        renderHealth("UNKNOWN", [], isMissingEndpoint(err)
            ? "Backend chưa có endpoint /sensor-health"
            : "Không kiểm tra được sức khỏe cảm biến");
    }
}

// --- 7. Dự báo AI ---------------------------------------------------------------

const RAIN_SOURCE_STYLES = {
    model: ["MODEL", "text-emerald-400 border-emerald-500/40"],
    heuristic: ["HEURISTIC", "text-amber-400 border-amber-500/40"],
};

function renderHorizon(h, horizon) {
    horizon = horizon || {};
    setText(`fc-temp-${h}`, fmt(horizon.temperature_c, 1, " °C"));
    const p = Number(horizon.rain_probability);
    const valid = horizon.rain_probability !== null && horizon.rain_probability !== undefined && Number.isFinite(p);
    const pct = valid ? Math.round(Math.min(Math.max(p, 0), 1) * 100) : null;
    setText(`fc-rain-${h}`, valid ? `${pct}%${horizon.rain_level ? ` (${horizon.rain_level})` : ""}` : "--%");
    $(`fc-bar-${h}`).style.width = valid ? `${pct}%` : "0%";

    const src = RAIN_SOURCE_STYLES[horizon.rain_source];
    const badge = $(`fc-src-${h}`);
    if (src) {
        badge.textContent = src[0];
        badge.className = `ml-1 px-1.5 py-0.5 rounded text-[10px] font-normal border ${src[1]}`;
    } else {
        badge.className = "hidden";
    }
    return valid ? p : null;
}

async function fetchForecast() {
    try {
        const data = await apiGet("/forecast", { device_id: CONFIG.DEVICE_ID });
        markBackend("forecast", true);
        const probs = {};
        for (const h of ["10", "30", "60"]) probs[h] = renderHorizon(h, data[`plus_${h}m`]);
        const generated = toMs(data.generated_at);
        setText("fc-updated", generated ? `Cập nhật ${timeLabel(generated)}` : "Đã cập nhật");
        renderAlert(data, probs);
    } catch (err) {
        markBackend("forecast", false, err);
        for (const h of ["10", "30", "60"]) renderHorizon(h, null);
        setText("fc-updated", "Không tải được dự báo");
        $("alert-banner").classList.add("hidden");
    }
}

function renderAlert(data, probs) {
    const banner = $("alert-banner");
    if (!data.alert_triggered) {
        banner.classList.add("hidden");
        return;
    }
    // Horizon gây cảnh báo = horizon có xác suất lớn nhất
    let best = null;
    for (const [h, p] of Object.entries(probs)) {
        if (p !== null && (best === null || p > probs[best])) best = h;
    }
    const threshold = data.rain_alert_threshold ?? state.threshold;
    const thr = threshold !== null && Number.isFinite(threshold)
        ? ` (ngưỡng ${Math.round(threshold * 100)}%)` : "";
    const detail = best !== null ? `Xác suất mưa ${Math.round(probs[best] * 100)}% tại +${best} phút${thr}. ` : "";
    banner.classList.remove("hidden");
    setText("alert-title", "CẢNH BÁO MƯA: XÁC SUẤT ĐẠT NGƯỠNG");
    setText("alert-message", detail + (data.alert_message || "Xác suất mưa đã đạt ngưỡng cảnh báo."));
}

// --- 8. Điều khiển 2 chiều: ngưỡng cảnh báo (SA-06) ------------------------------

function showThreshold(value, fromServer) {
    state.threshold = value;
    const pct = Math.round(value * 100);
    $("threshold-slider").value = String(pct);
    setText("threshold-val", `${pct}%`);
    setText("threshold-applied", fromServer
        ? `Ngưỡng đang áp dụng trên server: ${pct}%`
        : `Không đọc được ngưỡng từ server`);
}

async function loadThreshold() {
    try {
        const data = await apiGet("/alerts/threshold");
        markBackend("threshold", true);
        const v = Number(data.threshold);
        if (Number.isFinite(v)) showThreshold(v, true);
    } catch (err) {
        markBackend("threshold", false, err);
        setText("threshold-val", `${$("threshold-slider").value}%`);
        setText("threshold-applied", isMissingEndpoint(err)
            ? "Backend chưa có GET /alerts/threshold — chưa biết ngưỡng hiện tại"
            : "Không đọc được ngưỡng từ server");
    }
}

function initTwoWayControl() {
    const slider = $("threshold-slider");
    const btnSave = $("btn-save-threshold");
    const statusEl = $("threshold-status");
    let clearTimer = null;

    slider.addEventListener("input", (e) => setText("threshold-val", `${e.target.value}%`));

    btnSave.addEventListener("click", async () => {
        const newThreshold = Number(slider.value) / 100;
        if (!(newThreshold >= CONFIG.THRESHOLD_MIN && newThreshold <= CONFIG.THRESHOLD_MAX)) {
            statusEl.textContent = "Ngưỡng phải trong khoảng 40% - 95%";
            statusEl.className = "text-xs text-center block text-rose-400";
            return;
        }
        btnSave.disabled = true;
        btnSave.textContent = "ĐANG GỬI...";
        statusEl.textContent = "Đang lưu ngưỡng cảnh báo...";
        statusEl.className = "text-xs text-center block text-cyan-400";
        clearTimeout(clearTimer);

        try {
            const res = await fetch(`${CONFIG.API_BASE}/alerts/threshold`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ threshold: newThreshold }),
            });
            if (!res.ok) {
                let detail = `Server trả lỗi HTTP ${res.status}`;
                try {
                    const body = await res.json();
                    if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg).join("; ");
                    else if (body.detail) detail = String(body.detail);
                } catch (_) { /* giữ thông điệp mặc định */ }
                throw new HttpError(res.status, detail);
            }
            const body = await res.json();
            markBackend("threshold", true);
            const saved = Number(body.new_threshold);
            showThreshold(Number.isFinite(saved) ? saved : newThreshold, true);
            statusEl.textContent = `Đã cập nhật ngưỡng mới: ${slider.value}% thành công!`;
            statusEl.className = "text-xs text-center block text-emerald-400";
            fetchForecast();   // banner cảnh báo cập nhật theo ngưỡng mới
        } catch (err) {
            markBackend("threshold", false, err);
            statusEl.textContent = err instanceof HttpError ? `Lỗi: ${err.detail}` : "Lỗi kết nối Backend. Thử lại sau.";
            statusEl.className = "text-xs text-center block text-rose-400";
        } finally {
            btnSave.disabled = false;
            btnSave.textContent = "LƯU NGƯỠNG CẢNH BÁO";
            clearTimer = setTimeout(() => { statusEl.textContent = ""; }, 5000);
        }
    });

    $("btn-refresh-forecast").addEventListener("click", fetchForecast);
}

// --- Khởi động ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
    setText("station-id", CONFIG.DEVICE_ID);
    initClock();
    connectWebSocket();
    initChart();
    initTwoWayControl();

    loadHistory().then(fetchCurrent);
    loadThreshold().then(fetchForecast);
    fetchBenchmark();
    fetchSensorHealth();

    setInterval(fetchForecast, CONFIG.FORECAST_INTERVAL_MS);
    setInterval(fetchSensorHealth, CONFIG.HEALTH_INTERVAL_MS);
    setInterval(fetchBenchmark, CONFIG.BENCHMARK_INTERVAL_MS);
    setInterval(updatePressureTrend, 60000);
});

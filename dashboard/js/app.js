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
const CURRENT_VIEW = document.documentElement.dataset.view || "forecast";
const VIEW_CONTENT = {
    forecast: {
        eyebrow: "TỔNG QUAN THỜI TIẾT",
        title: "Dự báo thời tiết",
        description: "Điều kiện hiện tại và xu hướng trong 60 phút tới.",
        tab: "Dự báo",
    },
    observations: {
        eyebrow: "DỮ LIỆU QUAN TRẮC",
        title: "Biểu đồ thời tiết",
        description: "So sánh số đo trạm IoT với dữ liệu tham chiếu Open-Meteo.",
        tab: "Quan trắc",
    },
    station: {
        eyebrow: "TRẠM THỜI TIẾT IOT",
        title: "Trạm đo & sức khỏe",
        description: "Tình trạng linh kiện, dữ liệu đối chuẩn và lịch sử mưa.",
        tab: "Trạm đo",
    },
};
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
    RAIN_HISTORY_INTERVAL_MS: 15000,
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
    latestMeasurement: null,
    wsRetryMs: 1000,
    chart: null,
    chartAvailable: true,
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
    rainHistorySnapshot: null,
    failures: {},        // đếm lỗi theo loại request để hiện trạng thái Backend
    latestRain: null,
    latestForecast: null,
    healthReport: null,
    healthNote: "",
};

const $ = (id) => document.getElementById(id);

function initView() {
    const current = VIEW_CONTENT[CURRENT_VIEW] || VIEW_CONTENT.forecast;
    setText("view-eyebrow", current.eyebrow);
    setText("view-title", current.title);
    setText("view-description", current.description);
    document.title = `${current.tab} | IoT Local Weather`;
    const targetUrl = new URL(window.location.href);
    targetUrl.hash = "";
    document.querySelectorAll("[data-view-link]").forEach((link) => {
        const view = link.dataset.viewLink;
        targetUrl.searchParams.set("view", view);
        link.href = `${targetUrl.pathname}${targetUrl.search}`;
        if (view === CURRENT_VIEW) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
    });
    targetUrl.searchParams.set("view", "forecast");
    document.querySelector(".brand").href = `${targetUrl.pathname}${targetUrl.search}`;
}

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
    if (el.textContent !== String(text)) el.textContent = text;
    if (className !== undefined && el.className !== className) el.className = className;
}

function toMs(ts) {
    const ms = Date.parse(ts);
    return Number.isFinite(ms) ? ms : null;
}

function timeLabel(ms) {
    return new Date(ms).toLocaleTimeString("vi-VN", { hour12: false });
}

function rainTimeLabel(timestamp) {
    return new Date(timestamp).toLocaleString("vi-VN", {
        timeZone: "Asia/Ho_Chi_Minh", hour12: false,
    });
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
        setText("live-clock", timeLabel(Date.now()));
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
    if (typeof ApexCharts === "undefined") {
        state.chartAvailable = false;
        $("chart-loading").classList.remove("hidden");
        setText("chart-loading", "Không tải được thư viện biểu đồ. Kiểm tra kết nối mạng.");
        state.chart = { updateOptions() {} };
        return;
    }
    state.chart = new ApexCharts(chartElement, {
        chart: {
            type: "line",
            height: 390,
            background: "transparent",
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: false },
        },
        theme: { mode: "dark" },
        stroke: { curve: "smooth", width: [3, 2], dashArray: [0, 5] },
        // ApexCharts 3 needs an actual marker for reliable hover on the IoT
        // area series; zero-sized markers only left the sparse reference clickable.
        markers: { size: [2, 3], strokeWidth: 0, hover: { size: 5 } },
        colors: ["#73d8de", "#f4bf76"],
        fill: { type: ["gradient", "solid"], gradient: { shade: "dark", opacityFrom: 0.22, opacityTo: 0.01, stops: [0, 95, 100] } },
        series: [],
        noData: { text: "Chưa có dữ liệu", style: { color: "#94a3b8" } },
        xaxis: {
            type: "datetime",
            tooltip: { enabled: false },
            labels: {
                datetimeUTC: false,
                style: { colors: "#8ba6b4", fontSize: "11px" },
            },
        },
        yaxis: {
            decimalsInFloat: 1,
            labels: { style: { colors: "#8ba6b4", fontSize: "11px" } },
        },
        grid: { borderColor: "#294356", strokeDashArray: 4 },
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
    let lastPointer = null;
    let tooltipFrame = 0;
    const positionTooltip = () => {
        if (!lastPointer) return;
        const tooltip = chartElement.querySelector(".apexcharts-tooltip");
        if (!tooltip) return;
        // ApexCharts 3 can anchor a non-shared tooltip to the series rather than
        // the cursor when series have different timestamps. The tooltip may be
        // temporarily hidden while ApexCharts redraws, so offsetParent can be null.
        const canvas = chartElement.querySelector(".apexcharts-canvas") || chartElement;
        const bounds = canvas.getBoundingClientRect();
        const x = lastPointer.x - bounds.left;
        const y = lastPointer.y - bounds.top;
        const gap = 10;
        const left = x + gap + tooltip.offsetWidth <= bounds.width
            ? x + gap : Math.max(0, x - gap - tooltip.offsetWidth);
        const top = y + gap + tooltip.offsetHeight <= bounds.height
            ? y + gap : Math.max(0, y - gap - tooltip.offsetHeight);
        tooltip.style.setProperty("--cursor-left", `${left}px`);
        tooltip.style.setProperty("--cursor-top", `${top}px`);
        tooltip.classList.add("cursor-positioned");
    };
    const trackTooltip = (event) => {
        lastPointer = { x: event.clientX, y: event.clientY };
        positionTooltip();
        // ApexCharts can create/show the tooltip after the mouse event handler.
        if (!tooltipFrame) tooltipFrame = requestAnimationFrame(() => {
            tooltipFrame = 0;
            positionTooltip();
        });
    };
    chartElement.addEventListener("mousemove", trackTooltip);
    chartElement.addEventListener("pointerdown", trackTooltip);
    chartElement.addEventListener("mouseleave", () => { lastPointer = null; });

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
    if (!state.chart) return;
    state.chartDirty = false;
    const v = state.chartVar;
    const meta = VARIABLES[v];
    document.querySelectorAll(".chart-tab").forEach((btn) => {
        btn.setAttribute("aria-selected", String(btn.dataset.var === v));
    });

    const start = Date.now() - CONFIG.HISTORY_WINDOW_MS;
    const iot = state.points.filter((p) => p.t >= start && isNum(p[v])).map((p) => [p.t, p[v]]);
    const ref = state.reference.filter((p) => p.t >= start && isNum(p[v])).map((p) => [p.t, p[v]]);
    const loading = $("chart-loading");
    if (!state.historyLoading && state.chartAvailable) loading.classList.add("hidden");

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
            { name: `Trạm IoT (${meta.unit})`, type: "area", data: iot },
            { name: `Tham chiếu Open-Meteo (${meta.unit})`, type: "line", data: ref },
        ],
        yaxis: {
            min,
            max,
            tickAmount,
            decimalsInFloat: 1,
            title: { text: `${meta.label} (${meta.unit})`, style: { color: "#94a3b8" } },
            labels: { style: { colors: "#8ba6b4", fontSize: "11px" } },
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
    if (!state.chartAvailable || (!iot.length && !ref.length)) {
        loading.classList.remove("hidden");
        setText("chart-loading", !state.chartAvailable ? "Không tải được thư viện biểu đồ. Kiểm tra kết nối mạng."
            : state.historyFailed ? "Không tải được lịch sử quan trắc." : "Chưa có số đo trong 2 giờ gần nhất.");
    }
}

function renderRainHistory(data) {
    const list = $("rain-history-list");
    const wasOpen = new Map([...list.querySelectorAll("details")].map((day) => [day.dataset.date, day.open]));
    let count = 0;
    const days = data.days.map((day, index) => {
        const group = document.createElement("li");
        group.className = "rain-day";
        const details = document.createElement("details");
        details.dataset.date = day.date;
        details.open = wasOpen.get(day.date) ?? (index === 0);
        const title = document.createElement("summary");
        title.textContent = `${day.date.split("-").reverse().join("/")} · ${day.events.length} lần báo ướt`;
        const events = document.createElement("ul");
        events.className = "detail-list rain-day-events";
        for (const event of day.events) events.append(renderRainEvent(event));
        count += day.events.length;
        details.append(title, events);
        group.append(details);
        return group;
    });
    list.replaceChildren(...days);
    setText("rain-history-note", count
        ? `${count} lần ghi nhận tấm dò ướt`
        : data.has_readings ? "Tấm dò chưa báo ướt trong các mẫu đã lưu." : "Chưa có số đo trong 7 ngày gần nhất.");
}

function renderRainEvent(event) {
    const item = document.createElement("li");
    const time = document.createElement("p");
    time.className = "rain-event-time";
    time.textContent = `${event.confirmed_start ? "Chuyển sang ướt" : "Ghi nhận ướt"} lúc ${rainTimeLabel(event.first_wet_at)}`;
    const readings = document.createElement("p");
    readings.className = "rain-event-readings";
    readings.textContent = [
        `Nhiệt độ ${fmt(event.temperature, 1, " °C")}`,
        `Độ ẩm ${fmt(event.humidity, 1, "%")}`,
        `Áp suất ${fmt(event.pressure, 1, " hPa")}`,
    ].join(" · ");
    const end = document.createElement("p");
    end.className = "detail-note";
    if (event.status === "dry") {
        end.textContent = `Ghi nhận khô lại lúc ${rainTimeLabel(event.dry_at)}`;
    } else if (event.status === "wet") {
        end.textContent = "Tấm dò vẫn báo ướt";
    } else {
        end.textContent = `Mẫu ướt cuối lúc ${rainTimeLabel(event.last_wet_at)}. Chưa rõ lúc khô lại.`;
    }
    item.append(time, readings, end);
    return item;
}

async function fetchRainHistory() {
    try {
        const data = await apiGet("/rain-history", { device_id: CONFIG.DEVICE_ID });
        markBackend("rainHistory", true);
        const snapshot = JSON.stringify(data);
        if (state.rainHistorySnapshot !== snapshot) renderRainHistory(data);
        state.rainHistorySnapshot = snapshot;
    } catch (err) {
        markBackend("rainHistory", false, err);
        state.rainHistorySnapshot = null;
        setText("rain-history-note", "Không cập nhật được lịch sử mưa.");
    }
}

function addPoint(record) {
    const t = toMs(record.timestamp);
    if (t === null) return;
    const point = { t };
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
    state.latestMeasurement = data;
    state.latestRain = data.rain_detected === 1 ? true : data.rain_detected === 0 ? false : null;
    updateLiveDataWarning();
    setText("hero-updated", `Số đo lúc ${rainTimeLabel(timestamp)}`);
    setText("card-temp", fmt(data.temperature, 1));
    setText("card-press", fmt(data.pressure, 1));
    setText("card-hum", fmt(data.humidity, 1));
    const hum = Number(data.humidity);
    $("bar-hum").style.width = Number.isFinite(hum) ? `${Math.min(Math.max(hum, 0), 100)}%` : "0%";
    setText("card-rain-raw", isNum(Number(data.rain_raw)) && data.rain_raw !== null ? String(data.rain_raw) : "----");

    if (data.rain_detected === 1 || data.rain_detected === 0) {
        if (data.rain_detected === 1) {
            setText("card-rain-status", "Cảm biến đang ghi nhận mưa");
            setText("hero-rain-short", "Đang mưa");
        } else {
            setText("card-rain-status", "Cảm biến chưa ghi nhận mưa");
            setText("hero-rain-short", "Chưa mưa");
        }
    } else {
        setText("card-rain-status", "Chưa có trạng thái mưa");
        setText("hero-rain-short", "Chưa có");
    }
    $("hero-weather-icon").querySelector("use").setAttribute("href", state.latestRain ? "#i-rain" : "#i-cloud");
    renderWeatherSummary();
    if (state.healthReport) renderHealth(state.healthReport, state.healthNote);
}

function clearTelemetryCards(label) {
    ["card-temp", "card-hum", "card-press"].forEach((id) => setText(id, "--"));
    $("bar-hum").style.width = "0%";
    setText("card-rain-raw", "----");
    state.latestMeasurement = null;
    setText("card-rain-status", label);
    setText("hero-rain-short", "Chưa có");
    setText("hero-updated", "Chưa có thời gian cập nhật");
    renderWeatherSummary();
}

function renderWeatherSummary() {
    const stale = state.lastSampleAt === null || Date.now() - state.lastSampleAt > CONFIG.LIVE_DATA_TIMEOUT_MS;
    const disconnected = state.wsStatus === "reconnecting";
    const freshness = $("hero-freshness");
    freshness.classList.toggle("stale", stale || disconnected);
    setText("hero-freshness", state.lastSampleAt === null ? "Đang chờ số đo" : disconnected ? "Mất kết nối" : stale ? "Dữ liệu đã cũ" : "Số đo mới");
    if (state.lastSampleAt === null) {
        setText("hero-summary", "Dự báo sẽ xuất hiện khi trạm gửi đủ số đo.");
        return;
    }
    if (stale || disconnected) {
        setText("hero-summary", "Số đo hiển thị là lần cập nhật cuối. Kiểm tra kết nối trước khi sử dụng.");
        return;
    }
    const forecast = state.latestForecast;
    const probabilities = [10, 30, 60].map((h) => forecast?.[`plus_${h}m`]?.rain_probability)
        .filter((p) => p !== null && p !== undefined).map(Number)
        .filter((p) => Number.isFinite(p) && p >= 0 && p <= 1);
    if (state.latestRain) {
        setText("hero-summary", "Tấm dò đang báo ướt tại trạm. Theo dõi các mốc dự báo bên dưới để xem xu hướng mưa.");
    } else if (probabilities.length && forecast.forecast_scope === "VVTS") {
        const peak = Math.round(Math.max(...probabilities) * 100);
        setText("hero-summary", `Dự báo khu vực Tân Sơn Nhất có xác suất mưa cao nhất ${peak}%.`);
    } else if (probabilities.length) {
        const peak = Math.round(Math.max(...probabilities) * 100);
        setText("hero-summary", `Trong 60 phút tới, xác suất mưa cao nhất ở ba mốc dự báo là ${peak}%.`);
    } else {
        setText("hero-summary", "Chưa có dự báo cho giờ tới. Số đo hiện tại được cập nhật trực tiếp từ trạm.");
    }
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

const LIVE_STATUS = {
    connecting: ["Đang kết nối…", "amber"],
    reconnecting: ["Mất kết nối trực tiếp", "rose"],
    waiting: ["Chờ số đo", "amber"],
    offline: ["Trạm ngoại tuyến", "rose"],
    live: ["Trực tiếp", "emerald"],
};

function renderConnectionStatus(stationSilent) {
    let status = state.wsStatus;
    if (status === "connected") {
        status = stationSilent ? "offline" : state.lastSampleAt === null ? "waiting" : "live";
    }
    const [label, color] = LIVE_STATUS[status];
    setText("connection-status", label, `text-${color}-400`);
    $("status-dot").className = `bg-${color}-500`;
    $("status-ping").classList.toggle("hidden", status !== "live");
}

function updateLiveDataWarning() {
    const stationSilent = Date.now() - (state.lastSampleAt ?? state.wsOpenedAt) > CONFIG.LIVE_DATA_TIMEOUT_MS;
    renderConnectionStatus(stationSilent);
    let message = "";
    if (state.wsStatus === "reconnecting") {
        message = "Mất kết nối trực tiếp. Đang tự kết nối lại.";
    } else if (state.wsStatus === "connected" && stationSilent) {
        message = "Không nhận được số đo mới từ trạm trong hơn 30 giây.";
    }
    if (message && state.lastSampleAt !== null) {
        message += ` Số đo gần nhất lúc ${rainTimeLabel(state.lastSampleAt)}.`;
    }
    const warning = $("live-data-warning");
    if (warning.textContent !== message) {
        warning.textContent = message;
        if (state.lastSampleAt !== null) state.chartDirty = true;
    }
    warning.classList.toggle("hidden", !message);
    renderWeatherSummary();
}

function setWsStatus(kind) {
    state.wsStatus = kind;
    updateLiveDataWarning();
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

const HEALTH_LABELS = {
    OK: "DỮ LIỆU ỔN",
    WARNING: "CẦN KIỂM TRA",
    FAULT: "SỐ ĐO LỖI",
    UNKNOWN: "CHƯA ĐÁNH GIÁ",
};

// Chỉ hiện các tín hiệu có thể đối chiếu với số đo trạm và /sensor-health.
const STATION_COMPONENTS = [
    { id: "controller", name: "ESP8266 NodeMCU", role: "Bộ điều khiển trạm" },
    { id: "dht11", name: "DHT11", role: "Nhiệt độ · độ ẩm", sensors: ["temperature", "humidity"] },
    { id: "bmp280", name: "BMP280", role: "Áp suất", sensors: ["pressure"] },
    { id: "rain", name: "Cảm biến mưa", role: "Tấm dò · tín hiệu DO", sensors: ["rain"] },
];

const ANOMALY_LABELS = {
    MISSING_VALUE: "Thiếu giá trị đo",
    OUT_OF_RANGE: "Giá trị ngoài khoảng",
    SPIKE: "Biến động đột ngột",
    FROZEN_VALUE: "Giá trị không đổi lâu",
    WATER_STAGNATION_DRIFT: "Dữ liệu báo ướt kéo dài",
};

function componentAssessment(component, data) {
    const latest = state.lastSampleAt || 0;
    const fresh = latest > 0 && Date.now() - latest <= CONFIG.LIVE_DATA_TIMEOUT_MS;
    if (component.id === "controller") {
        if (fresh) return { level: "observed", label: "Có dữ liệu mới",
            detail: "Backend đang nhận số đo mới của trạm." };
        return { level: "unknown", label: latest === 0 ? "Chưa có dữ liệu" : "Dữ liệu đã cũ",
            detail: latest === 0 ? "Chưa nhận được số đo từ trạm." :
                `Số đo cuối lúc ${timeLabel(latest)}.` };
    }
    if (!fresh || !state.latestMeasurement)
        return { level: "unknown", label: "Chưa có số đo mới",
            detail: "Cần số đo mới từ trạm để kiểm tra tín hiệu." };
    const checked = toMs(data?.checked_at);
    const reportFresh = checked !== null && Date.now() - checked <= CONFIG.LIVE_DATA_TIMEOUT_MS;
    const anomalies = reportFresh
        ? (data.anomalies || []).filter((a) => component.sensors?.includes(a.sensor))
        : [];
    if (anomalies.length) {
        const fault = anomalies.some((a) => ["MISSING_VALUE", "OUT_OF_RANGE"].includes(a.type));
        return { level: fault ? "fault" : "warning", label: fault ? "Lỗi số đo" : "Cần kiểm tra",
            detail: anomalies.map((a) => ANOMALY_LABELS[a.type] || String(a.type || "Dị thường")).join(" · ") };
    }
    if (component.id === "rain") {
        if (state.latestRain !== null)
            return { level: "observed", label: state.latestRain ? "DO báo ướt" : "DO báo khô",
                detail: "Trạng thái DO do firmware gửi trong số đo mới nhất." };
        return { level: "unknown", label: "Chưa đủ dữ liệu",
            detail: "Chưa có tín hiệu mưa mới từ trạm." };
    }
    const reading = state.latestMeasurement;
    if (component.id === "dht11" && reading.temperature != null && reading.humidity != null &&
        isNum(Number(reading.temperature)) && isNum(Number(reading.humidity))) {
        return { level: "observed", label: "Có số đo mới",
            detail: `Nhiệt độ ${fmt(reading.temperature, 1)}°C · Độ ẩm ${fmt(reading.humidity, 1)}%.` };
    }
    if (component.id === "bmp280" && reading.pressure != null && isNum(Number(reading.pressure))) {
        return { level: "observed", label: "Có số đo mới",
            detail: `Áp suất ${fmt(reading.pressure, 1)} hPa.` };
    }
    return { level: "unknown", label: "Thiếu số đo",
        detail: "Số đo mới nhất chưa có giá trị của cảm biến này." };
}

function renderHealth(data, note) {
    state.healthReport = data;
    state.healthNote = note;
    const checked = toMs(data?.checked_at);
    const fresh = checked !== null && Date.now() - checked <= CONFIG.LIVE_DATA_TIMEOUT_MS;
    const key = fresh && HEALTH_STYLES[data?.status] ? data.status : "UNKNOWN";
    setText("health-badge", HEALTH_LABELS[key],
        `text-xs font-mono font-bold px-2.5 py-1 rounded-full border ${HEALTH_STYLES[key]}`);
    const list = $("health-list");
    const rows = STATION_COMPONENTS.map((component) => {
        const assessment = componentAssessment(component, data);
        const li = document.createElement("li");
        li.className = "component-row";
        li.dataset.level = assessment.level;
        const top = document.createElement("div");
        top.className = "component-top";
        const name = document.createElement("strong");
        name.textContent = component.name;
        const badge = document.createElement("span");
        badge.className = "component-status";
        badge.textContent = assessment.label;
        top.append(name, badge);
        const role = document.createElement("span");
        role.className = "component-role";
        role.textContent = component.role;
        const detail = document.createElement("p");
        detail.className = "component-detail";
        detail.textContent = assessment.detail;
        li.append(top, role, detail);
        return li;
    });
    list.replaceChildren(...rows);
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
        renderHealth(data, note + when + " · Đánh giá theo dữ liệu trạm gửi về.");
    } catch (err) {
        markBackend("health", false, err);
        renderHealth(null, isMissingEndpoint(err)
            ? "Backend chưa có endpoint /sensor-health"
            : "Không kiểm tra được sức khỏe cảm biến");
    }
}

// --- 7. Dự báo AI ---------------------------------------------------------------

const RAIN_SOURCE_STYLES = {
    model: ["MÔ HÌNH", "source-tag"],
    heuristic: ["ƯỚC TÍNH", "source-tag"],
};

function horizonWaitMessage(horizon) {
    if (horizon.issue === "observations_unavailable") {
        const { history_available_minutes: have, history_required_minutes: need } = horizon;
        if (Number.isInteger(have) && Number.isInteger(need) && have < need) {
            return `Đã có ${have}/${need} phút số đo liên tục`;
        }
        return "Thiếu số đo ở một số mốc cần thiết";
    }
    return {
        observations_stale: "Đang chờ số đo mới từ trạm",
        model_unavailable: "Mô hình chưa sẵn sàng",
        model_partial: "Chưa có kết quả mô hình cho chỉ số này",
    }[horizon.issue];
}

function renderHorizon(h, horizon, unavailableMessage) {
    horizon = horizon || {};
    const regional = state.latestForecast?.forecast_scope === "VVTS";
    const stationModel = state.latestForecast?.forecast_engine === "station_inputs";
    const temperature = $(`fc-temp-${h}`);
    setText(`fc-temp-${h}`, fmt(horizon.temperature_c, 1, " °C"));
    const waiting = unavailableMessage || horizonWaitMessage(horizon);
    if (horizon.temperature_source === "persistence" ||
        (horizon.temperature_c == null && horizon.rain_probability != null && waiting)) {
        const note = document.createElement("small");
        note.className = "forecast-temperature-note";
        note.textContent = horizon.temperature_source === "persistence" ? "Tạm dùng nhiệt độ mới nhất" : waiting;
        temperature.append(note);
    }
    const p = Number(horizon.rain_probability);
    const valid = horizon.rain_probability !== null && horizon.rain_probability !== undefined && Number.isFinite(p) && p >= 0 && p <= 1;
    const pct = valid ? Math.round(Math.min(Math.max(p, 0), 1) * 100) : null;
    setText(`fc-rain-${h}`, valid ? `${pct}%` : "--%");
    $(`fc-bar-${h}`).style.width = valid ? `${pct}%` : "0%";
    const risk = !valid ? "unknown" : p >= 0.7 ? "high" : p >= 0.4 ? "medium" : "low";
    $(`fc-card-${h}`).dataset.risk = risk;
    setText(`fc-risk-${h}`, {
        unknown: waiting || (regional && h === "10" ? "Chưa hỗ trợ mốc 10 phút" : "Chưa có dự báo mưa"),
        low: "Khả năng thấp", medium: "Cần chú ý", high: "Khả năng cao",
    }[risk]);
    $(`fc-icon-${h}`).querySelector("use").setAttribute("href", valid && p >= 0.4 ? "#i-rain" : "#i-cloud");

    const src = regional && horizon.rain_source === "model"
        ? ["TÂN SƠN NHẤT", "source-tag"] : RAIN_SOURCE_STYLES[horizon.rain_source];
    const badge = $(`fc-src-${h}`);
    badge.title = "";
    if (src) {
        badge.textContent = src[0];
        badge.className = src[1];
    } else {
        badge.className = "hidden";
    }
    const generated = state.latestForecast ? toMs(state.latestForecast.generated_at) : null;
    const validAt = regional || stationModel ? toMs(horizon.valid_at) : generated && generated + Number(h) * 60000;
    setText(`fc-time-${h}`, validAt ? timeLabel(validAt).slice(0, 5) : "--:--");
    return valid ? p : null;
}

async function fetchForecast() {
    try {
        const data = await apiGet("/forecast", { device_id: CONFIG.DEVICE_ID });
        markBackend("forecast", true);
        state.latestForecast = data;
        const probs = {};
        for (const h of ["10", "30", "60"]) probs[h] = renderHorizon(h, data[`plus_${h}m`]);
        const generated = toMs(data.generated_at);
        const regional = data.forecast_scope === "VVTS";
        const stationModel = data.forecast_engine === "station_inputs";
        const reference = toMs(data.forecast_reference_at);
        const forecastStale = generated !== null && Date.now() - generated > 2 * 60 * 1000;
        let updated = "Không có thời gian tạo";
        if (regional) {
            updated = reference ? `Bản tin Tân Sơn Nhất lúc ${timeLabel(reference)}` : "Đang chờ bản tin Tân Sơn Nhất";
        } else if (stationModel) {
            updated = reference ? `Số đo trạm lúc ${timeLabel(reference)}` : "Đang chờ số đo trạm";
        } else if (generated) {
            updated = `${forecastStale ? "Dự báo đã cũ · " : "Tạo lúc "}${timeLabel(generated)}`;
        }
        setText("fc-updated", updated);
        const valid = Object.values(probs).filter((p) => p !== null);
        if (valid.length) {
            const peak = Math.round(Math.max(...valid) * 100);
            setText("rain-peak", `${peak}%`);
            setText("rain-outlook", regional ? "Dự báo khu vực Tân Sơn Nhất. Còi dự báo tại trạm chưa áp dụng nguồn này."
                : stationModel ? "Dự báo từ số đo trạm. Còi cảnh báo theo ngưỡng đang áp dụng."
                : forecastStale ? "Dự báo đã cũ. Hãy làm mới trước khi sử dụng."
                : data.alert_triggered
                ? "Dự báo đã đạt ngưỡng cảnh báo đang áp dụng."
                : peak >= 40 ? "Có khả năng mưa ở một hoặc nhiều mốc dự báo." : "Khả năng mưa ở các mốc dự báo hiện thấp.");
        } else {
            setText("rain-peak", "--%");
            const issue = {
                model_unavailable: "Mô hình dự báo chưa sẵn sàng.",
                observations_stale: stationModel ? "Số đo trạm đã cũ. Chờ trạm gửi số mới."
                    : "Bản tin Tân Sơn Nhất đã cũ. Chờ bản tin mới.",
                observations_unavailable: stationModel ? "Cần số đo gần thời điểm hiện tại, 30 và 60 phút trước."
                    : "Chưa có đủ bản tin Tân Sơn Nhất liên tiếp để dự báo.",
            }[data.forecast_issue];
            setText("rain-outlook", issue || "Chưa có xác suất mưa hợp lệ.");
        }
        renderWeatherSummary();
        renderAlert(data, probs);
    } catch (err) {
        const reason = err.detail?.code;
        const unavailable = {
            no_recent_measurements: "Đang chờ số đo từ trạm",
            sensor_data_unusable: "Số đo mới nhất ngoài khoảng hợp lệ",
        }[reason];
        markBackend("forecast", Boolean(unavailable), err);
        state.latestForecast = null;
        const message = unavailable || "Không tải được dự báo";
        for (const h of ["10", "30", "60"]) renderHorizon(h, null, message);
        setText("fc-updated", message);
        setText("rain-peak", "--%");
        setText("rain-outlook", message);
        renderWeatherSummary();
        $("alert-banner").classList.add("hidden");
    }
}

async function refreshForecastEvaluation() {
    const list = $("evaluation-list");
    const button = $("refresh-evaluation");
    button.disabled = true;
    try {
        const result = await apiGet("/forecast/evaluation", { device_id: CONFIG.DEVICE_ID });
        list.replaceChildren();
        const logged = result.horizons.some((row) => row.forecasts > 0);
        setText("evaluation-note", logged
            ? `Đã đánh dấu ${result.test_periods} khoảng thử. Mỗi mẫu mưa là một dự báo được đối chiếu với tấm dò; nhiều dự báo có thể cùng rơi vào một đợt mưa.`
            : "Chưa lưu được dự báo từ mô hình. Dữ liệu sẽ xuất hiện sau khi trạm có đủ số đo.");
        if (!logged) return;
        for (const row of result.horizons) {
            const item = document.createElement("li");
            const title = document.createElement("strong");
            title.textContent = `+${row.horizon_minutes} phút`;
            const temperature = document.createElement("p");
            temperature.textContent = row.temperature_samples
                ? `Nhiệt độ lệch trung bình ${fmt(row.temperature_mae_c, 2)} °C · Giữ nguyên số đo: ${fmt(row.baseline_mae_c, 2)} °C · ${row.temperature_samples} mẫu`
                : "Nhiệt độ chưa có mẫu đối chiếu";
            const rain = document.createElement("p");
            rain.textContent = row.rain_samples
                ? `Mưa: ${row.rain_samples} mẫu · ${row.rain_events} có ướt · ${row.hits} báo đúng · ${row.false_alarms} báo nhầm · ${row.misses} bỏ sót`
                : "Mưa chưa có mẫu đối chiếu";
            const count = document.createElement("p");
            count.textContent = `${row.forecasts} dự báo đã lưu · ${row.pending} đang chờ · ${row.excluded} loại vì trùng khoảng thử`;
            item.append(title, temperature, rain, count);
            list.appendChild(item);
        }
    } catch (_) {
        list.replaceChildren();
        setText("evaluation-note", "Không tải được đánh giá dự báo.");
    } finally {
        button.disabled = false;
    }
}

function initForecastEvaluation() {
    const details = $("forecast-evaluation");
    const form = $("evaluation-test-form");
    details.addEventListener("toggle", () => {
        if (details.open) refreshForecastEvaluation();
    });
    $("refresh-evaluation").addEventListener("click", refreshForecastEvaluation);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const starts = form.elements.starts_at.value;
        const ends = form.elements.ends_at.value;
        if (!starts || !ends || starts >= ends) {
            setText("evaluation-test-status", "Chọn giờ kết thúc sau giờ bắt đầu.");
            return;
        }
        const button = form.querySelector("button");
        button.disabled = true;
        try {
            const res = await fetch(`${CONFIG.API_BASE}/forecast/evaluation/test-periods`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    device_id: CONFIG.DEVICE_ID,
                    starts_at: new Date(`${starts}+07:00`).toISOString(),
                    ends_at: new Date(`${ends}+07:00`).toISOString(),
                }),
            });
            if (!res.ok) throw new Error(String(res.status));
            setText("evaluation-test-status", "Đã lưu khoảng thử. Kết quả đã lưu sẽ được tính lại.");
            form.reset();
            await refreshForecastEvaluation();
        } catch (_) {
            setText("evaluation-test-status", "Không lưu được khoảng thử. Mỗi khoảng dài tối đa 7 ngày.");
        } finally {
            button.disabled = false;
        }
    });
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
    initView();
    setText("station-id", CONFIG.DEVICE_ID);
    $("trend-press").title = "Thay đổi áp suất theo giờ, tính từ số đo trạm trong khoảng 60 phút.";
    $("card-rain-raw").title = "Giá trị ADC thô của cảm biến mưa; cách diễn giải phụ thuộc hiệu chuẩn phần cứng.";
    $("health-badge").title = "Đánh giá dị thường cảm biến trong cửa sổ 6 giờ.";
    initClock();
    connectWebSocket();
    if (CURRENT_VIEW === "observations") {
        initChart();
        loadHistory().then(fetchCurrent);
        fetchBenchmark();
        setInterval(fetchBenchmark, CONFIG.BENCHMARK_INTERVAL_MS);
    } else if (CURRENT_VIEW === "station") {
        renderHealth(null, "Đang kiểm tra dữ liệu từng linh kiện…");
        fetchCurrent().then(fetchSensorHealth);
        fetchRainHistory();
        fetchBenchmark();
        setInterval(fetchSensorHealth, CONFIG.HEALTH_INTERVAL_MS);
        setInterval(fetchRainHistory, CONFIG.RAIN_HISTORY_INTERVAL_MS);
        setInterval(fetchBenchmark, CONFIG.BENCHMARK_INTERVAL_MS);
    } else {
        initTwoWayControl();
        initForecastEvaluation();
        loadHistory().then(fetchCurrent);
        loadThreshold().then(fetchForecast);
        setInterval(fetchForecast, CONFIG.FORECAST_INTERVAL_MS);
        setInterval(updatePressureTrend, 60000);
    }
});

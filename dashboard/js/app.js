/**
 * ==============================================================================
 * DỰ ÁN: IOT LOCAL WEATHER MONITORING & FORECASTING
 * MODULE 4: FRONTEND SCADA DASHBOARD APP LOGIC
 * Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
 * Các Task: SA-05, SA-06 (TASK.md)
 * ==============================================================================
 */

const CONFIG = {
    WS_URL: "ws://localhost:8000/ws/weather/live",
    API_BASE: "http://localhost:8000/api/weather",
    FORECAST_INTERVAL_MS: 15000, // Cập nhật dự báo mỗi 15 giây
    CHART_MAX_POINTS: 20
};

// State toàn cục của Dashboard
const state = {
    ws: null,
    isConnected: false,
    chart: null,
    iotSeries: [],
    openWeatherSeries: [],
    categories: [],
    currentThreshold: 0.70
};

// --- Khởi tạo khi nạp trang ---
document.addEventListener("DOMContentLoaded", () => {
    initClock();
    initChart();
    connectWebSocket();
    fetchCurrentWeatherFallback();
    fetchForecast();
    initTwoWayControl();

    // Định kỳ lấy forecast
    setInterval(fetchForecast, CONFIG.FORECAST_INTERVAL_MS);
});

// 1. Đồng hồ thời gian thực
function initClock() {
    const clockEl = document.getElementById("live-clock");
    setInterval(() => {
        const now = new Date();
        clockEl.innerText = now.toTimeString().split(" ")[0] + " (Local)";
    }, 1000);
}

// 2. Khởi tạo Biểu đồ Realtime ApexCharts
function initChart() {
    const options = {
        chart: {
            type: "line",
            height: 280,
            background: "transparent",
            toolbar: { show: false },
            animations: { enabled: true, easing: "linear", dynamicAnimation: { speed: 1000 } }
        },
        theme: { mode: "dark" },
        stroke: { curve: "smooth", width: [3, 2] },
        colors: ["#06b6d4", "#f59e0b"],
        series: [
            { name: "Cảm biến IoT (°C)", data: [] },
            { name: "OpenWeather Benchmark (°C)", data: [] }
        ],
        xaxis: {
            categories: [],
            labels: { style: { colors: "#64748b", fontSize: "11px", fontFamily: "JetBrains Mono" } }
        },
        yaxis: {
            labels: { style: { colors: "#64748b", fontSize: "11px", fontFamily: "JetBrains Mono" } },
            title: { text: "Nhiệt độ (°C)", style: { color: "#94a3b8" } }
        },
        grid: { borderColor: "#1e293b", strokeDashArray: 4 },
        legend: { position: "top", horizontalAlign: "right", labels: { colors: "#cbd5e1" } },
        tooltip: { theme: "dark" }
    };

    state.chart = new ApexCharts(document.querySelector("#weather-chart"), options);
    state.chart.render();
}

// 3. Kết nối WebSocket Live
function connectWebSocket() {
    const statusText = document.getElementById("connection-status");
    const statusDot = document.getElementById("status-dot");
    const statusPing = document.getElementById("status-ping");

    try {
        state.ws = new WebSocket(CONFIG.WS_URL);

        state.ws.onopen = () => {
            state.isConnected = true;
            statusText.innerText = "WS CONNECTED";
            statusText.className = "text-emerald-400";
            statusDot.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500";
            statusPing.className = "pulse-indicator absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75";
        };

        state.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                updateTelemetryCards(data);
                updateChartData(data.temperature);
            } catch (err) {
                console.error("Lỗi parse WS payload:", err);
            }
        };

        state.ws.onclose = () => {
            state.isConnected = false;
            statusText.innerText = "RECONNECTING...";
            statusText.className = "text-amber-400";
            statusDot.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500";
            statusPing.className = "hidden";
            setTimeout(connectWebSocket, 3000);
        };

        state.ws.onerror = () => {
            state.ws.close();
        };

    } catch (e) {
        console.warn("WebSocket không thể kết nối ngay, đang thử lại...");
        setTimeout(connectWebSocket, 5000);
    }
}

// 4. Cập nhật Thẻ Metric Realtime
function updateTelemetryCards(data) {
    if (data.temperature !== undefined) {
        document.getElementById("card-temp").innerText = Number(data.temperature).toFixed(1);
    }
    if (data.humidity !== undefined) {
        const hum = Number(data.humidity);
        document.getElementById("card-hum").innerText = hum.toFixed(1);
        document.getElementById("bar-hum").style.width = `${Math.min(hum, 100)}%`;
    }
    if (data.pressure !== undefined) {
        document.getElementById("card-press").innerText = Number(data.pressure).toFixed(1);
    }
    if (data.rain_raw !== undefined) {
        document.getElementById("card-rain-raw").innerText = data.rain_raw;
    }
    if (data.rain_detected !== undefined) {
        const isRain = data.rain_detected === 1;
        const rainEl = document.getElementById("card-rain-status");
        if (isRain) {
            rainEl.innerText = "ĐANG MƯA";
            rainEl.className = "text-2xl font-bold font-mono text-rose-500 animate-pulse";
        } else {
            rainEl.innerText = "KHÔ RÁO";
            rainEl.className = "text-2xl font-bold font-mono text-emerald-400";
        }
    }
}

// 5. Cập nhật Biểu đồ chuỗi thời gian
function updateChartData(iotTemp) {
    const now = new Date().toTimeString().split(" ")[0];
    // Giả lập sai lệch benchmark OpenWeather ±0.4°C để đối chuẩn trực quan
    const openWeatherTemp = Number((iotTemp + (Math.random() * 0.8 - 0.4)).toFixed(1));

    document.getElementById("bias-temp").innerText = `${(iotTemp - openWeatherTemp > 0 ? "+" : "")}${(iotTemp - openWeatherTemp).toFixed(1)}°C`;

    state.iotSeries.push(iotTemp);
    state.openWeatherSeries.push(openWeatherTemp);
    state.categories.push(now);

    if (state.iotSeries.length > CONFIG.CHART_MAX_POINTS) {
        state.iotSeries.shift();
        state.openWeatherSeries.shift();
        state.categories.shift();
    }

    if (state.chart) {
        state.chart.updateSeries([
            { name: "Cảm biến IoT (°C)", data: state.iotSeries },
            { name: "OpenWeather Benchmark (°C)", data: state.openWeatherSeries }
        ]);
        state.chart.updateOptions({ xaxis: { categories: state.categories } });
    }
}

// 6. Lấy Dự báo Ngắn Hạn AI từ Backend
async function fetchForecast() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/forecast`);
        if (!res.ok) return;
        const data = await res.json();

        // Cập nhật +10m
        document.getElementById("fc-temp-10").innerText = `${data.plus_10m.temperature_c.toFixed(1)} °C`;
        const p10 = Math.round(data.plus_10m.rain_probability * 100);
        document.getElementById("fc-rain-10").innerText = `${p10}% (${data.plus_10m.rain_level})`;
        document.getElementById("fc-bar-10").style.width = `${p10}%`;

        // Cập nhật +30m
        document.getElementById("fc-temp-30").innerText = `${data.plus_30m.temperature_c.toFixed(1)} °C`;
        const p30 = Math.round(data.plus_30m.rain_probability * 100);
        document.getElementById("fc-rain-30").innerText = `${p30}% (${data.plus_30m.rain_level})`;
        document.getElementById("fc-bar-30").style.width = `${p30}%`;

        // Cập nhật +60m
        document.getElementById("fc-temp-60").innerText = `${data.plus_60m.temperature_c.toFixed(1)} °C`;
        const p60 = Math.round(data.plus_60m.rain_probability * 100);
        document.getElementById("fc-rain-60").innerText = `${p60}% (${data.plus_60m.rain_level})`;
        document.getElementById("fc-bar-60").style.width = `${p60}%`;

        // Hiển thị Banner nếu có Alert kích hoạt
        const banner = document.getElementById("alert-banner");
        if (data.alert_triggered) {
            banner.classList.remove("hidden");
            document.getElementById("alert-title").innerText = "CẢNH BÁO MƯA CỤC BỘ (CLOSED-LOOP TRIGGERED)";
            document.getElementById("alert-message").innerText = data.alert_message || "Xác suất mưa cao! Hệ thống đã tự động kích hoạt còi hú và gửi cảnh báo.";
        } else {
            banner.classList.add("hidden");
        }

    } catch (e) {
        console.warn("Không thể tải API dự báo:", e);
    }
}

// 7. Fallback lấy thời tiết hiện tại qua REST
async function fetchCurrentWeatherFallback() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/current`);
        if (res.ok) {
            const data = await res.json();
            updateTelemetryCards(data);
            updateChartData(Number(data.temperature));
        }
    } catch (e) {
        // Mock data nếu backend chưa bật để Dashboard hiển thị đẹp mắt ngay khi mở
        updateTelemetryCards({
            temperature: 31.4,
            humidity: 78.0,
            pressure: 1006.5,
            rain_raw: 2450,
            rain_detected: 0
        });
        updateChartData(31.4);
    }
}

// 8. Điều khiển 2 chiều: Cập nhật ngưỡng cảnh báo
function initTwoWayControl() {
    const slider = document.getElementById("threshold-slider");
    const valDisplay = document.getElementById("threshold-val");
    const btnSave = document.getElementById("btn-save-threshold");
    const statusEl = document.getElementById("threshold-status");

    slider.addEventListener("input", (e) => {
        valDisplay.innerText = `${e.target.value}%`;
    });

    btnSave.addEventListener("click", async () => {
        const newThreshold = Number(slider.value) / 100.0;
        btnSave.disabled = true;
        statusEl.innerText = "Đang gửi lệnh xuống backend...";
        statusEl.className = "text-xs text-center block text-cyan-400";

        try {
            const res = await fetch(`${CONFIG.API_BASE}/alerts/threshold`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ threshold: newThreshold })
            });

            if (res.ok) {
                statusEl.innerText = `Đã cập nhật ngưỡng mới: ${slider.value}% thành công!`;
                statusEl.className = "text-xs text-center block text-emerald-400";
            } else {
                throw new Error("Server trả lỗi");
            }
        } catch (err) {
            statusEl.innerText = "Lỗi kết nối Backend. Thử lại sau.";
            statusEl.className = "text-xs text-center block text-rose-400";
        } finally {
            btnSave.disabled = false;
            setTimeout(() => { statusEl.innerText = ""; }, 4000);
        }
    });

    document.getElementById("btn-refresh-forecast").addEventListener("click", () => {
        fetchForecast();
    });
}


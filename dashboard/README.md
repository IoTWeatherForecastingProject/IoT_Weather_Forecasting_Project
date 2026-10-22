# MODULE 4: WEB SCADA REALTIME DASHBOARD
## Giao Diện Giám Sát Thời Gian Thực & Điều Khiển 2 Chiều

> **Phụ trách chính:** 👤 **Thành viên 3 (AI + Analytics + Frontend Engineer)**  
> **Phối hợp:** TV1 (kết nối kênh WebSocket và REST API).  
> **Các Task liên quan:** `SA-05`, `SA-06` (Xem chi tiết tại [TASK.md](../TASK.md)).

---

## 1. Mục tiêu Kỹ thuật

Xây dựng giao diện Web Dashboard phong cách **SCADA Công nghiệp (Industrial Realtime SCADA)** hiện đại, trực quan, hỗ trợ tương tác 2 chiều:
1. **Giám sát tức thời qua WebSocket:** Nhận và cập nhật số liệu cảm biến (Nhiệt độ, Độ ẩm, Khí áp, Trạng thái mưa) độ trễ $< 50$ms không cần F5 trình duyệt.
2. **Biểu đồ chuỗi thời gian đối chuẩn:** Vẽ đồng thời dữ liệu trạm IoT và dữ liệu trạm chuẩn khí tượng OpenWeatherMap bằng thư viện ApexCharts.
3. **Hiển thị Dự báo Ngắn hạn:** Trực quan hóa kết quả dự báo $+10$m, $+30$m, $+60$m kèm thanh đo xác suất mưa phân cấp (*Thấp, Trung bình, Cao*).
4. **Cảnh báo lỗi phần cứng:** Hiển thị banner cảnh báo nếu thuật toán phát hiện đột biến (Spike) hoặc kẹt cảm biến mưa do đọng nước.
5. **Điều khiển Phản hồi 2 chiều:** Cho phép người dùng tùy chỉnh ngưỡng kích hoạt cảnh báo mưa (ví dụ: từ $70\%$ sang $60\%$) và gửi ngược xuống Backend để cập nhật luật điều khiển.

---

## 2. Cấu trúc Thư mục Frontend

```text
dashboard/
├── README.md           # Tài liệu hướng dẫn phát triển và chạy Dashboard
├── index.html          # Trang giao diện chính (Single Page Application)
├── css/
│   └── style.css       # Custom styling, hiệu ứng SCADA và animations
└── js/
    └── app.js          # Logic WebSocket, ApexCharts, Fetch API và Event Handlers
```

---

## 3. Kiến trúc Luồng Dữ liệu Frontend

```text
[Backend FastAPI: ws://localhost:8000/ws/weather/live]
                       │ (WebSocket Push)
                       ▼
                 [app.js: onmessage]
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
[Cập nhật Thẻ Metric]      [Cập nhật ApexCharts]
(Nhiệt độ, Độ ẩm, Áp suất)  (Chuỗi thời gian realtime)

                       │ (Chu kỳ 30s gọi REST API)
                       ▼
[Backend FastAPI: GET /api/weather/forecast]
                       │
                       ▼
       [Cập nhật Khung Dự báo +10m, +30m, +60m]
       [Cập nhật Thanh Đo Xác suất Mưa]

                       ▲
                       │ (User thay đổi Slider & Submit)
[Form Điều khiển 2 chiều: POST /api/weather/alerts/threshold]
```

---

## 4. Hướng dẫn Chạy Thử nghiệm

### Cách 1: Mở trực tiếp trên Trình duyệt
Bạn chỉ cần nhấp đúp chuột vào tệp `index.html` hoặc mở bằng trình duyệt Google Chrome / Microsoft Edge.

### Cách 2: Sử dụng VS Code Live Server (Khuyến nghị)
1. Cài đặt tiện ích mở rộng **Live Server** trên VS Code.
2. Nhấp chuột phải vào `dashboard/index.html` $\rightarrow$ chọn **Open with Live Server**.
3. Dashboard sẽ mở tại địa chỉ `http://127.0.0.1:5500/dashboard/index.html`.

### Cách 3: Python http.server
```bash
cd dashboard && python -m http.server 5500     # mở http://localhost:5500/
```

### Cấu hình Địa chỉ Backend
Mặc định Dashboard gọi Backend tại **cùng host, cổng 8000** (`http://<host>:8000`, WebSocket `ws://<host>:8000/ws/weather/live`). Không cần sửa code, dùng tham số URL:

| Tham số | Ví dụ | Ý nghĩa |
|---|---|---|
| `api` | `?api=http://192.168.1.10:8000` | Địa chỉ Backend khi chạy trên máy khác |
| `device` | `?device=station02` | Mã trạm cần theo dõi (mặc định `station01`) |

### Nguyên tắc hiển thị
- **Không có dữ liệu giả.** Backend tắt → header hiện `MẤT KẾT NỐI BACKEND`, các thẻ hiện `--`. `/current` trả `status = "waiting_data"` (DB trống) → thẻ hiện `CHỜ DỮ LIỆU`.
- Biểu đồ trục thời gian theo `timestamp` của bản ghi, giữ 2 giờ gần nhất (nạp từ `/history`, nối thêm điểm từ WebSocket, vẽ lại tối đa 1 lần/giây). Tab chọn Nhiệt độ / Độ ẩm / Áp suất.
- Xu hướng áp suất = ΔP so với điểm cách ~60 phút, quy về hPa/giờ (cần ≥ 45 phút dữ liệu); giảm ≥ 1 hPa/h → `Đang giảm` (màu vàng).
- WebSocket tự kết nối lại với backoff 1 → 2 → 4 … tối đa 30 giây; chỉ nhận payload có `device_id` đúng trạm đang xem.
- Dữ liệu từ server luôn gán bằng `textContent` (không `innerHTML`).

### Endpoint Dashboard sử dụng

| Endpoint | Chu kỳ | Trạng thái Backend | Khi chưa có (404/405) |
|---|---|---|---|
| `GET /api/weather/current?device_id=` | lúc mở trang | Có | — |
| `GET /api/weather/history?device_id=&start_time=&limit=1000&offset=` | lúc mở trang | Có | — |
| `WS /ws/weather/live` | realtime | Có | — |
| `GET /api/weather/forecast?device_id=` | 15 s | Có | — |
| `POST /api/weather/alerts/threshold` `{"threshold": 0.4–0.95}` | khi bấm nút | Có | — |
| `GET /api/weather/alerts/threshold` → `{"threshold": 0.70}` | lúc mở trang | **Chưa có** | Thanh trượt giữ 70%, ghi "chưa biết ngưỡng hiện tại" |
| `GET /api/weather/sensor-health?device_id=&window_minutes=360` → `{status, checked_at, anomalies[{type, sensor, message}]}` | 30 s | **Chưa có** (dùng `SensorAnomalyDetector.analyze()` của SA-03) | Badge `UNKNOWN` |
| `GET /api/weather/benchmark?device_id=&source=open-meteo&hours=24` → `{reference[{timestamp, temperature, humidity, pressure}], latest_bias{temp_bias_c, ...} \| null}` | 10 phút | **Chưa có** (dữ liệu từ bảng `reference_weather` của SA-04) | Không có series tham chiếu, bias `N/A` |

Trường `rain_source` (`model` / `heuristic`) của mỗi horizon dự báo được hiển thị thành badge nếu `/forecast` trả về (hiện `ForecastResponse` của Backend đang lược bỏ trường này).

---

## 5. Tiêu chí Hoàn thành (DoD)

- [ ] Dashboard kết nối thành công WebSocket tới Backend và tự động kết nối lại khi Backend khởi động lại.
- [ ] Biểu đồ chuỗi thời gian vẽ mượt mà theo timestamp thật và cập nhật theo thời gian thực.
- [ ] Khung dự báo hiển thị đúng 3 mốc $+10$m, $+30$m, $+60$m và đổi màu cảnh báo (Đỏ/Vàng/Xanh) theo xác suất mưa.
- [ ] Nút cập nhật ngưỡng cảnh báo mưa gửi thành công request `POST /api/weather/alerts/threshold` và nhận phản hồi `200 OK`.


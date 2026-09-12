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

### Cấu hình Địa chỉ Backend
Trong tệp `js/app.js`, bạn có thể tùy chỉnh địa chỉ Backend nếu chạy trên máy khác:
```javascript
const CONFIG = {
    WS_URL: "ws://localhost:8000/ws/weather/live",
    API_BASE: "http://localhost:8000/api/weather"
};
```

---

## 5. Tiêu chí Hoàn thành (DoD)

- [ ] Dashboard kết nối thành công WebSocket tới Backend và tự động kết nối lại khi Backend khởi động lại.
- [ ] Biểu đồ chuỗi thời gian vẽ mượt mà, hỗ trợ zoom/pan và cập nhật theo thời gian thực.
- [ ] Khung dự báo hiển thị đúng 3 mốc $+10$m, $+30$m, $+60$m và đổi màu cảnh báo (Đỏ/Vàng/Xanh) theo xác suất mưa.
- [ ] Nút cập nhật ngưỡng cảnh báo mưa gửi thành công request `POST /api/weather/alerts/threshold` và nhận phản hồi `200 OK`.


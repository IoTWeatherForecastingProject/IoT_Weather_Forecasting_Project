# KỊCH BẢN THỰC NGHIỆM DEMO NGHIỆM THU (DEMO SCENARIOS)
## IoT Local Weather Monitoring & Short-Term Forecasting System

---

## 1. Kịch bản 1: Giám Sát Thời Gian Thực Ổn Định (Realtime Telemetry Monitoring)

- **Mục đích:** Chứng minh chuỗi kết nối từ cảm biến phần cứng qua mạng không dây đến CSDL và hiển thị trên Web SCADA đạt độ trễ thấp và ổn định liên tục.
- **Các bước thực hiện:**
  1. Khởi động Docker (`docker-compose up -d`) và Backend Server (`uvicorn app.main:app`).
  2. Bật nguồn trạm đo ESP32 hoặc chạy script giả lập `simulate_iot_device.py`.
  3. Mở giao diện `dashboard/index.html`.
- **Hiện tượng & Tiêu chí đạt:**
  - Badge trạng thái trên Dashboard chuyển sang màu xanh: `WS CONNECTED`.
  - Các thẻ chỉ số (Nhiệt độ, Độ ẩm, Áp suất, Mưa) cập nhật liên tục mỗi chu kỳ 5 giây mà không cần bấm F5 trình duyệt.
  - Biểu đồ thời gian thực vẽ mượt mà, hiển thị đồng thời đường số liệu IoT và đường đối chuẩn OpenWeatherMap.

---

## 2. Kịch bản 2: Dự Báo Thời Tiết Ngắn Hạn & So Sánh Giá Trị Thực (Short-Term AI Forecasting)

- **Mục đích:** Chứng minh năng lực của các mô hình Time Series AI trong việc dự đoán xu hướng thời tiết ngắn hạn và so sánh với giá trị thực tế sau đó.
- **Các bước thực hiện:**
  1. Cho trạm đo chạy ổn định ít nhất 15-30 phút để tích lũy cửa sổ dữ liệu.
  2. Quan sát khung hiển thị dự báo trên Dashboard tại 3 mốc: $+10$ phút, $+30$ phút, $+60$ phút.
  3. Ghi chép lại giá trị nhiệt độ dự báo $\hat{T}_{t+10}$.
  4. Chờ 10 phút trôi qua và đối chiếu với giá trị nhiệt độ thực tế đo được từ cảm biến $T_{t+10}$.
- **Hiện tượng & Tiêu chí đạt:**
  - Sai số tuyệt đối $|T_{t+10} - \hat{T}_{t+10}| < 0.8^\circ$C, tốt hơn rõ rệt so với mô hình dự báo không đổi (Persistence Baseline).
  - Thanh đo xác suất mưa phản ánh đúng trạng thái bầu trời (Ví dụ: Trời quang thì xác suất mưa $\le 20\%$).

---

## 3. Kịch bản 3: Kích Hoạt Tình Huống Mưa Dông & Phản Hồi 2 Chiều Khép Kín (Closed-Loop Actuation)

- **Mục đích:** Chứng minh tính năng cao cấp nhất của đề tài - Vòng lặp điều khiển phản hồi 2 chiều khép kín (Sensing $\rightarrow$ AI Prediction $\rightarrow$ Actuation).
- **Các bước thực hiện:**
  1. Trên Dashboard, thiết lập ngưỡng cảnh báo mưa là **70%** (hoặc giảm xuống **60%** bằng thanh trượt).
  2. Tạo tình huống áp suất giảm và độ ẩm tăng:
     - *Nếu dùng trạm thật:* Dùng khăn ẩm hoặc giọt nước nhỏ lên cảm biến mưa, thổi hơi ẩm vào BME280.
     - *Nếu dùng máy tính:* Chạy script giả lập với cờ kích hoạt:
       ```bash
       python integration_tests/simulate_iot_device.py --simulate-rain
       ```
  3. Backend phát hiện xác suất mưa tính toán đạt $\ge 70\%$.
- **Hiện tượng & Tiêu chí đạt:**
  1. **Trên Web Dashboard:** Banner cảnh báo màu đỏ xuất hiện nổi bật: `CẢNH BÁO MƯA CỤC BỘ (CLOSED-LOOP TRIGGERED)`.
  2. **Dưới trạm đo IoT:**
     - Còi Buzzer phát âm thanh bíp bíp ngắt quãng liên tục.
     - Đèn LED cảnh báo chớp nháy đỏ.
     - Màn hình OLED hiển thị dòng chữ: `CANH BAO MUA (+30m: 85%)`.
  3. **Trên điện thoại người dùng:** Nhận được tin nhắn cảnh báo tức thì từ Telegram Bot kèm thông số chi tiết.


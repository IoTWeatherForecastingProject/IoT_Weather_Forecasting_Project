# MODULE 5: INTEGRATION TESTS & FAULT TOLERANCE TESTING
## Kiểm Thử Tích Hợp Toàn Chuỗi & Kịch Bản Chịu Lỗi Ngoại Lệ

> **Phụ trách:** 👥 **Cả 3 thành viên làm chung**  
> **Các Task liên quan:** `SYS-01`, `SYS-02`, `SYS-03` (Xem chi tiết tại [TASK.md](../TASK.md)).

---

## 1. Mục tiêu Kiểm thử

Đảm bảo hệ thống vận hành liên thông, ổn định và có khả năng chịu lỗi (Fault-tolerant) từ trạm đo biên đến máy chủ đám mây và giao diện người dùng:
1. **Kiểm thử liên thông (End-to-End Integration):** Xác minh luồng dữ liệu thông suốt: Cảm biến $\rightarrow$ MQTT $\rightarrow$ Ingestion $\rightarrow$ CSDL PostgreSQL $\rightarrow$ AI Inference $\rightarrow$ Dashboard $\rightarrow$ Lệnh phản hồi 2 chiều.
2. **Kiểm thử chịu lỗi (Fault Tolerance & Stress Test):**
   - Mất kết nối WiFi / MQTT và khả năng tự phục hồi (Auto-reconnect).
   - Dữ liệu cảm biến bị gián đoạn thời gian dài (Missing data interpolation).
   - Cảm biến mưa bị kẹt nước hoặc cảm biến BME280 bị rút dây.
   - Tải truy cập nhiều WebSocket client cùng lúc.

---

## 2. Cấu trúc Thư mục Kiểm thử

```text
integration_tests/
├── README.md               # Hướng dẫn quy trình chạy test
├── simulate_iot_device.py  # Giả lập trạm đo IoT gửi stream MQTT (có kịch bản mưa và lỗi)
└── test_end_to_end.py      # Script tự động kiểm tra toàn bộ luồng E2E
```

---

## 3. Hướng dẫn Chạy Giả lập Trạm IoT (Mock Hardware)

Khi chưa có phần cứng thật hoặc khi kiểm thử trên máy tính, sử dụng script `simulate_iot_device.py` để phát dữ liệu MQTT giả lập:

### Kịch bản 1: Giả lập thời tiết bình thường
```bash
python simulate_iot_device.py --broker localhost --port 1883 --interval 5
```

### Kịch bản 2: Kích hoạt tình huống mưa dông (Kích hoạt Cảnh báo 2 chiều)
Script sẽ chủ động hạ áp suất khí quyển từ 1008 hPa xuống 1002 hPa, tăng độ ẩm lên 95% và kích hoạt cảm biến mưa:
```bash
python simulate_iot_device.py --simulate-rain --interval 3
```

### Kịch bản 3: Giả lập lỗi cảm biến (Spike dị thường)
```bash
python simulate_iot_device.py --simulate-anomaly
```

---

## 4. Chạy Kiểm thử Tự Động End-to-End

Script `test_end_to_end.py` sẽ thực hiện toàn bộ quy trình:
1. Kết nối MQTT và publish 1 bản ghi thời tiết.
2. Kiểm tra xem Backend Ingestion Worker có ghi bản ghi đó vào PostgreSQL không.
3. Gọi API `/api/weather/current` và `/api/weather/forecast` kiểm tra kết quả.
4. Đăng ký nhận topic `weather/station01/alert` để xác nhận Backend bắn lệnh phản hồi khi xác suất mưa cao.

Lệnh thực thi:
```bash
python test_end_to_end.py
```
Nếu toàn bộ các bước đều xanh (`[PASS]`), hệ thống đã sẵn sàng cho buổi nghiệm thu và demo!


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
├── test_end_to_end.py      # Script tự động kiểm tra toàn bộ luồng E2E
└── test_fault_tolerance.py # Script MQTT -> sensor-health cho SYS-02
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

## 5. Kiểm thử chịu lỗi cảm biến (SYS-02)

Chạy các lệnh sau từ thư mục gốc repo, với Docker (MQTT, PostgreSQL) và backend
đang chạy bằng code hiện tại. Môi trường Python cần `paho-mqtt` và `httpx`
(có trong `backend/requirements.txt`). Các mẫu là **dữ liệu tổng hợp từ simulator**.

Worker mặc định subscribe `weather/+/data`, nên `--device-id` được dùng cho cả
topic `weather/<device_id>/data` và payload. Dùng mã trạm riêng để không trộn với
demo `station01`; nếu cấu hình worker đã đổi, cần bảo đảm subscription nhận các
topic này. Simulator nhận cảnh báo trên `weather/<device_id>/alert`.

```bash
# Bình thường; không tham số vẫn gửi station01 mỗi 5 giây và chạy vô hạn
python integration_tests/simulate_iot_device.py --scenario normal --device-id sys02-normal --backfill-minutes 40 --interval 10 --count 1
# Mưa: tương đương --simulate-rain
python integration_tests/simulate_iot_device.py --scenario rain --device-id sys02-rain --count 10
# Spike 62°C/880 hPa mỗi mẫu thứ 5: tương đương --simulate-anomaly
python integration_tests/simulate_iot_device.py --scenario spike --device-id sys02-spike --count 5
# BME280 kẹt chính xác một giá trị trong hơn 30 phút
python integration_tests/simulate_iot_device.py --scenario frozen --device-id sys02-frozen --backfill-minutes 35 --interval 10 --count 1
# Cảm biến mưa kẹt ướt, độ ẩm khô và áp suất ổn định hơn 6 giờ
python integration_tests/simulate_iot_device.py --scenario stuck-wet --device-id sys02-stuck-wet --backfill-minutes 370 --interval 10 --count 1
# Rút dây BME280: gửi null như ArduinoJson serialize NaN
python integration_tests/simulate_iot_device.py --scenario unplugged --device-id sys02-unplugged --count 1
```

`--backfill-minutes N` publish nhanh lịch sử timestamp UTC từ hiện tại trừ N phút
đến hiện tại, QoS 1, chờ PUBACK từng mẫu và nghỉ 5 ms giữa các mẫu.
`--count M` chỉ đếm mẫu realtime sau backfill; `0` là chạy vô hạn, `1` để kết thúc
nhanh trong script. Khi bật cả hai cờ cũ, spike vẫn ưu tiên mỗi mẫu thứ 5 và các
mẫu còn lại mô phỏng mưa như trước.

```bash
# Chạy đủ 6 kịch bản, gồm offline: lịch sử dừng từ 20 phút trước
python integration_tests/test_fault_tolerance.py
# Chỉ chạy kẹt ướt hoặc cấu hình dịch vụ/báo cáo riêng
python integration_tests/test_fault_tolerance.py --only stuck-wet --base-url http://localhost:8000 --broker localhost --port 1883 --username weather_admin --password weather_secure_pass_2026 --report docs/reports/sys02_sensor_fault_results.md
```

Script tạo `sys02-<scenario>-<epoch>` riêng cho mỗi kịch bản, backfill chu kỳ
10 giây (stuck-wet: 2221 mẫu), rồi poll tối đa 30 giây sau publish tới khi
`n_records` đủ trước khi đánh giá. Kẹt ướt dùng `window_minutes=400`, các trường
hợp khác dùng `60`. Kỳ vọng: normal OK; frozen và stuck-wet WARNING; spike,
unplugged và offline FAULT. Offline phải có STALE_DATA, spike/unplugged phải có
OUT_OF_RANGE. Cửa sổ không có bản ghi vẫn UNKNOWN/no_data.

Bảng PASS/FAIL và thời gian phát hiện được in ra và ghi vào
`docs/reports/sys02_sensor_fault_results.md` theo mặc định, kèm UTC và mã trạm.
Thời gian tính từ trước kết nối/publish đến khi API thấy đủ mẫu; lỗi dịch vụ
được ghi FAIL và script trả exit code 1. Script giữ dữ liệu thử trong DB để
có thể kiểm tra lại theo mã trạm, không xóa dữ liệu demo.

Kiểm chứng logic khi không có broker/Docker:

```bash
cd ai_engine
.venv/Scripts/python.exe -m pytest -q tests/test_anomaly_detector.py tests/test_simulator_scenarios.py
```


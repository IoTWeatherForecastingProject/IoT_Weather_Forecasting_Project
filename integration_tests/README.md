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
   - Cảm biến mưa bị kẹt nước hoặc cảm biến BMP280/DHT11 bị rút dây.
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

Mặc định `rain_raw` dùng ADC 10-bit (0–1023) của NodeMCU ESP8266; thêm `--adc-bits 12` nếu cần dữ liệu giả lập kiểu ESP32. Cờ `rain_detected` và giá trị AO được tạo cùng chiều: giá trị thấp biểu thị ướt. Đây là dữ liệu tổng hợp, không thay cho hiệu chỉnh cảm biến thật.

Kiểm tra offline các kịch bản ADC 10/12-bit (cần `paho-mqtt`, không cần broker), chạy từ thư mục gốc:

```bash
python -m unittest discover -s integration_tests -p test_simulator_payloads.py
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

## 4. E2E tự động trong môi trường riêng

Chạy từ thư mục gốc dự án, khi Docker PostgreSQL và Mosquitto hoạt động:

```powershell
& backend/.venv/Scripts/python.exe -m pip install -r integration_tests/requirements.txt
& backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --dashboard
```

Thêm `--report-dir personal/tv1/verification/my-run` để chọn nơi lưu. Bỏ `--dashboard` khi chỉ kiểm tra pipeline. Kiểm thử trình duyệt sử dụng Microsoft Edge đã cài trên Windows.

Script tạo **database PostgreSQL mới và MQTT namespace riêng** `e2e/<run_id>/weather`, chạy backend trên cổng tạm với MQTT client ID riêng. Tài khoản DB phát triển cần quyền CREATE DATABASE; không dùng script này với tài khoản/DB production. Namespace test không khớp subscription `weather/+/data` của backend chính.

Các bước thực tế:

1. Chạy migration trên DB mới, đợi health xác nhận DB/MQTT/tác vụ nền.
2. Subscribe alert và mở WebSocket trước khi gửi telemetry.
3. Gieo lịch sử fixture vào DB test; publish mẫu mới qua MQTT, kiểm tra DB/current/history/WebSocket.
4. Gửi lại mẫu UTC và mẫu lỗi: không thêm DB/stream trùng hoặc số liệu mặc định giả.
5. Xác nhận cảnh báo từ tác vụ nền trước khi gọi forecast, đúng topic/payload và audit PUBACK.
6. Gọi forecast nhiều lần, qua thêm chu kỳ nền, kiểm tra cooldown dùng chung.
7. Đọc/đổi ngưỡng, kiểm tra validation, sensor-health/benchmark và trạng thái dữ liệu rỗng.
8. Nếu bật `--dashboard`, kiểm tra Edge desktop/mobile: dữ liệu realtime, badge HEURISTIC, đổi ngưỡng, reconnect, lỗi JS/API và tràn ngang; lưu ảnh.
9. Trong cleanup, khôi phục ngưỡng DB test, dừng backend test và xóa đúng database do script vừa tạo.

Mặc định E2E dùng `FORECAST_ENGINE_MODE=heuristic` và fixture để ổn định kết quả. Lịch sử gieo sẵn dài 121 phút với chu kỳ 30 giây; API lấy cửa sổ 120 phút, đủ cho yêu cầu lịch sử thực tối thiểu 90 phút của TV2. Tác vụ test chạy 0,5 giây/lần; cooldown vẫn 180 giây. Kiểm tra biên hết cooldown bằng đồng hồ điều khiển ở unit test nên không đợi thu lịch sử hay 180 giây mỗi lượt E2E.

Kết quả nằm trong `e2e.json`, `backend.log` và hai ảnh Dashboard. Khi bất kỳ bước nào fail, script trả exit code 1; đạt thì 0. Fixture được ghi rõ là dữ liệu test; dữ liệu trạm/nguỡng của backend chính không bị thay đổi. Nghiệm thu model, nguồn/cảm biến và relay/còi thực tế là các bước riêng.

## Kiểm thử độc lập TV1 khi TV2/TV3 chưa merge

Chạy suite backend và E2E trong DB/topic tạm, chặn import AI/phân tích bên ngoài:

```powershell
& backend/.venv/Scripts/python.exe -m pytest integration_tests/test_virtual_station.py integration_tests/test_simulator_payloads.py -q
& backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --backend-tests --report-dir personal/tv1/verification/independent_run
```

Mỗi lượt ghi `e2e.json`, `backend.log`, và khi dùng `--backend-tests` có thêm `backend_pytest.log`/XML. Chế độ độc lập bỏ các test có marker `integrated_model` vì chúng cần module/artifact TV2/TV3 thật. Mặc định heuristic + analytics disabled; raw reference vẫn được trả, bias chưa tích hợp là null và sensor-health là UNKNOWN. Trạm giả lập chỉ kiểm tra hợp đồng nhận lệnh, mô phỏng còi 3s/LED 10s; không tác động board/còi thật và không chứng minh chất lượng model hoặc firmware/điện áp. Không cần `--dashboard` để nghiệm thu phần TV1. Xem [điều kiện bàn giao](../docs/architecture/tv1_independent_handoff.md).

## Kiểm thử model TV2 và phân tích TV3 sau tích hợp

Cài thêm các thư viện inference, rồi chạy một lượt riêng:

```powershell
& backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-inference.txt
& backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --integrated-models --report-dir personal/tv1/verification/integrated_run
```

Chế độ này vẫn tạo DB, cổng backend và topic test riêng, tắt Telegram và khôi phục ngưỡng trong cleanup. Backend chạy `FORECAST_ENGINE_MODE=auto`, `ANALYTICS_ENGINE_MODE=auto`; các module TV2/TV3 được import thật. Thêm `--backend-tests` để kiểm tra suite backend trong DB tạm hoặc `--dashboard` để mở kiểm tra trình duyệt.

Kiểm tra bắt buộc nhiệt độ dùng artifact đã bàn giao trong `ml/models/` ở cả ba horizon, `temperature_confidence=normal` và không có lý do fallback. Test sẽ fail nếu backend chỉ trả persistence/heuristic dù HTTP vẫn thành công. Dự báo mưa giữ nguồn `rain_source` theo từng horizon: khi chưa có `ai_engine/saved_models/rain_classifier_models.joblib`, kết quả phải ghi `heuristic`; sự vắng mặt này được ghi vào báo cáo. Sensor-health và benchmark dùng thuật toán TV3 thật, với fixture tham chiếu đúng nguồn live `open-meteo-15min`.

Ngưỡng DB test được đặt tạm về 0 trước khi gieo lịch sử để kiểm tra cảnh báo nền độc lập với xác suất model, sau đó kiểm tra việc cập nhật ngưỡng 1 và dùng chung cooldown giữa API/tác vụ nền. Đây là kiểm chứng nối module và hợp đồng dữ liệu trên fixture tổng hợp, chưa đánh giá độ chính xác khí tượng hoặc tác động relay/còi vật lý.


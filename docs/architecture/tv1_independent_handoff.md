# TV1 chạy độc lập và điều kiện nhận bàn giao TV2/TV3

## Phạm vi hiện tại

TV2/TV3 chưa hoàn tất và chưa merge theo xác nhận của người dùng. Những thư mục mẫu AI/Dashboard đã có trong checkout không phải bằng chứng các thành viên đã bàn giao hoặc được nghiệm thu. TV1 không sửa thuật toán, huấn luyện weights, hay đánh dấu công việc TV2/TV3 hoàn tất.

Backend mặc định dùng `FORECAST_ENGINE_MODE=heuristic`, `ANALYTICS_ENGINE_MODE=disabled`. Không import module AI/phân tích của thành viên khác khi khởi động. Dữ liệu MQTT, PostgreSQL, REST, WebSocket, cấu hình ngưỡng và cảnh báo có thể kiểm thử bằng dữ liệu tổng hợp cùng trạm giả lập.

`GET /api/weather/integrations` trả chế độ cấu hình: forecast `local_heuristic`, analytics `not_integrated`. Khi opt-in `auto`, trạng thái chỉ là `external_opt_in_unverified`, không chứng minh module/weights hoặc chất lượng mô hình đã đạt. Không có tín hiệu kiểm chứng độ chính xác model trong phạm vi TV1.

## Biên inference TV2/TV3

Hàm bàn giao giữ `inference.unified_forecast.predict_forecast(recent_data, threshold=0.70)`; `recent_data` là pandas DataFrame của **một trạm**, sắp thời gian tăng dần, cột `device_id,timestamp,temperature,humidity,pressure,rain_raw,rain_detected`. Cửa sổ truy vấn backend 76 phút; thời gian UTC, °C, %, hPa. Mẫu mới nhất phải nằm trong khoảng cảm biến; thời gian nhận không được gọi là thời gian đo chính xác nếu thiết bị chưa có UTC.

Schema output: [forecast_provider.schema.json](../contracts/forecast_provider.schema.json). Backend kiểm tra trước khi dùng cho cảnh báo:

- Đủ `plus_10m`, `plus_30m`, `plus_60m`, giá trị số hữu hạn; xác suất trong [0,1], không nhận boolean hoặc chuỗi thay số.
- `rain_level` là Low/Medium/High; mỗi horizon ghi `rain_source=model|heuristic` trung thực theo artifact thực sự được dùng.
- `generated_at` có timezone; `device_id` khớp trạm đầu vào.
- TV1 tính lại `alert_triggered` từ xác suất và ngưỡng DB hiện tại; không để cờ của provider thay quyết định ngưỡng.

Module không tồn tại → local heuristic / `engine_unavailable`; provider lỗi → fallback có lý do; output sai hợp đồng → `invalid_engine_output`. Fallback không được ghi `rain_source=model`. `forecast_engine` và `fallback_reason` xuất qua API để đối chiếu. Heuristic chỉ phục vụ kiểm tra luồng, không phải model đã đánh giá khí tượng.

Trước khi bật `FORECAST_ENGINE_MODE=auto`: nhận commit đã review/merge, weights cùng metadata, thứ tự feature, phiên bản thư viện, minimum history và kết quả kiểm thử riêng của TV2/TV3. Sau đó chạy kiểm tra hợp đồng và E2E tích hợp model trên cấu hình/artifact cố định. File schema không thay yêu cầu bàn giao weights.

## Biên phân tích TV3

Chỉ bật `ANALYTICS_ENGINE_MODE=auto` sau bàn giao:

- `sensor_analytics.anomaly_detector.SensorAnomalyDetector.analyze(frame)` trả dict có `status=OK|WARNING|FAULT`, `anomalies` dạng list, tùy chọn `checked_at` ISO-8601. Output phải JSON-serializable, không có NaN/Infinity. Backend tự giữ `device_id` và phạm vi cửa sổ đã truy vấn.
- `openweather_benchmark.bias_analysis.build_report(iot_frame, ref_frame, device_id, source)` trả `(report, aligned_frame)`. `report` có `metrics`, `meta.notes`, tùy chọn `reason`; aligned_frame có `timestamp,n_iot,iot_temperature,ref_temperature,iot_humidity,ref_humidity,iot_pressure,ref_pressure`. Thống nhất mean IoT ±5 phút, tối thiểu 3 mẫu/biến, sai số IoT−tham chiếu. Đây là hợp đồng dự kiến của adapter, chưa nghiệm thu thuật toán TV3.

Chưa tích hợp: sensor-health là UNKNOWN / `analytics_not_integrated`; benchmark vẫn trả dữ liệu tham chiếu có thật nhưng `latest_bias=null`, `metrics={}`. Không có dữ liệu/cũ dùng `no_data`/`stale_data`; provider thiếu hoặc lỗi dùng `analytics_unavailable`/`analytics_failed`, không làm hỏng toàn bộ API hoặc giả báo cảm biến khỏe. Test TV1 dùng stub giao diện để kiểm tra adapter, không dùng stub làm thuật toán vận hành.

## Kiểm chứng TV1 không cần các module ngoài

```powershell
& backend/.venv/Scripts/python.exe -m pytest integration_tests/test_virtual_station.py integration_tests/test_simulator_payloads.py -q
& backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --backend-tests --report-dir personal/tv1/verification/independent_run
```

Lệnh thứ hai tạo DB `weather_e2e_<id>` và MQTT prefix `e2e/<id>/weather`, chạy backend và suite trong cùng DB tạm, **chặn import toàn bộ module TV2/TV3 bằng import hook trong tiến trình thử**. Không đổi tên/xóa thư mục thành viên khác. Import hook phải tự xác nhận đã hoạt động trước khi kiểm tra. Cuối lượt khôi phục ngưỡng, dừng backend thử, xóa đúng DB được tạo; không dùng topic station01, không gửi Telegram và không điều khiển COM9.

VirtualStation là test double theo hợp đồng, kiểm tra nhận đúng thiết bị/topic và trạng thái còi 3 giây/LED 10 giây. Nó không phải giả lập CPU ESP8266, không chứng minh parser firmware giống hoàn toàn hoặc thời gian điện thực. Host tests C++ và kiểm tra phần cứng vẫn là các lớp bằng chứng riêng. UI hiện có chỉ là scaffold; `--dashboard` là kiểm tra tùy chọn, không đánh dấu SA-05/SA-06 của TV3 hoàn tất.

## Còn chờ

Linh kiện BMP280/mưa để thu đủ số đo thật; nguồn/A0 và nghiệm thu trạm đủ tải/WiFi; artifact và phần mềm đã merge từ TV2/TV3; chất lượng dự báo trên dữ liệu thật; Telegram thật khi được yêu cầu và có cấu hình. Không dùng dữ liệu tổng hợp hoặc DHT11 đơn lẻ để đánh dấu các mục này đạt.

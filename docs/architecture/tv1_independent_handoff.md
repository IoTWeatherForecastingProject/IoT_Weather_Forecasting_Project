# TV1 chạy độc lập và điều kiện nhận bàn giao TV2/TV3

## Phạm vi hiện tại

Nhánh TV1 đã hợp nhất TV3 PR #11 và TV2 PR #24 từ `develop`. Adapter backend dùng artifacts nhiệt độ trong `ml/models` và pipeline mưa/phân tích của TV3. Việc nối được module và vượt qua kiểm thử kỹ thuật không thay thế nghiệm thu độ chính xác trên dữ liệu thật; không huấn luyện lại hoặc ghi đè weights trong bước tích hợp.

Backend mặc định dùng `FORECAST_ENGINE_MODE=heuristic`, `ANALYTICS_ENGINE_MODE=disabled`. Không import module AI/phân tích của thành viên khác khi khởi động. Dữ liệu MQTT, PostgreSQL, REST, WebSocket, cấu hình ngưỡng và cảnh báo có thể kiểm thử bằng dữ liệu tổng hợp cùng trạm giả lập.

`GET /api/weather/integrations` trả chế độ cấu hình: forecast `local_heuristic`, analytics `not_integrated`. Khi opt-in `auto`, trạng thái chỉ là `external_opt_in_unverified`, không chứng minh module/weights hoặc chất lượng mô hình đã đạt. Không có tín hiệu kiểm chứng độ chính xác model trong phạm vi TV1.

## Biên inference TV2/TV3

Backend gọi `app.services.integrated_forecast.predict_forecast(recent_data, threshold=0.70)`; `recent_data` là pandas DataFrame của **một trạm**, sắp thời gian tăng dần, cột `device_id,timestamp,temperature,humidity,pressure,rain_raw,rain_detected`. Cửa sổ truy vấn backend 120 phút; thời gian UTC, °C, %, hPa. Mẫu mới nhất phải nằm trong khoảng cảm biến; thời gian nhận không được gọi là thời gian đo chính xác nếu thiết bị chưa có UTC.

Adapter gọi `ml.inference_engine.get_engine().predict()` để chạy các model nhiệt độ đã bàn giao. TV2 kiểm tra ít nhất 90 phút thực và dựng đặc trưng trên lưới 1 phút. TV3 cung cấp `inference.unified_forecast.predict_rain_forecast()` cho nguồn mưa riêng từng horizon; đường này không nạp model nhiệt độ cũ. Nhiệt độ persistence không làm mất xác suất mưa hợp lệ. Backend khóa đường suy luận nhiệt độ để HTTP và tác vụ nền không ghi đè diagnostics dùng chung của singleton.

Schema output: [forecast_provider.schema.json](../contracts/forecast_provider.schema.json). Backend kiểm tra trước khi dùng cho cảnh báo:

- Đủ `plus_10m`, `plus_30m`, `plus_60m`, giá trị số hữu hạn; xác suất trong [0,1], không nhận boolean hoặc chuỗi thay số.
- `rain_level` là Low/Medium/High; mỗi horizon ghi `rain_source=model|heuristic` trung thực theo artifact thực sự được dùng.
- `generated_at` có timezone; `device_id` khớp trạm đầu vào.
- TV1 tính lại `alert_triggered` từ xác suất và ngưỡng DB hiện tại; không để cờ của provider thay quyết định ngưỡng.
- `temperature_source=model|persistence|heuristic` theo từng horizon; `temperature_model`, `temperature_confidence`, `temperature_fallback_reason` giải thích trạng thái nhiệt độ. Provider cũ thiếu các trường này được giữ null để tương thích, không tự công nhận model.

Module không tồn tại → local heuristic / `engine_unavailable`; provider lỗi → fallback có lý do; output sai hợp đồng → `invalid_engine_output`. Fallback không được ghi `rain_source=model`. `forecast_engine` và `fallback_reason` xuất qua API để đối chiếu. Heuristic chỉ phục vụ kiểm tra luồng, không phải model đã đánh giá khí tượng.

Trước khi bật `FORECAST_ENGINE_MODE=auto`, dùng Python ≥3.12 và cài `backend/requirements-inference.txt`; phiên bản sklearn/XGBoost được giữ theo artifacts hiện tại. Từ thư mục backend, chạy `python -m pytest -m integrated_model -q`, rồi E2E `--integrated-models`. Model nhiệt độ phải thật sự thành công khi đủ lịch sử; không chấp nhận test chỉ kiểm tra HTTP 200 hoặc cho phép fallback. File schema không thay yêu cầu bàn giao weights. Checkout hiện chưa có artifact mưa nên mưa vẫn ghi `heuristic`.

## Biên phân tích TV3

Bật `ANALYTICS_ENGINE_MODE=auto` để dùng các module TV3 đã hợp nhất:

- `sensor_analytics.anomaly_detector.SensorAnomalyDetector.analyze(frame)` trả dict có `status=OK|WARNING|FAULT`, `anomalies` dạng list, tùy chọn `checked_at` ISO-8601. Output phải JSON-serializable, không có NaN/Infinity. Backend tự giữ `device_id` và phạm vi cửa sổ đã truy vấn.
- `openweather_benchmark.bias_analysis.build_report(iot_frame, ref_frame, device_id, source)` trả `(report, aligned_frame)`. `report` có `metrics`, `meta.notes`, tùy chọn `reason`; aligned_frame có `timestamp,n_iot,iot_temperature,ref_temperature,iot_humidity,ref_humidity,iot_pressure,ref_pressure`. Thống nhất mean IoT ±5 phút, tối thiểu 3 mẫu/biến, sai số IoT−tham chiếu. Dashboard lấy source `open-meteo-15min` theo crawler hiện tại; client lịch sử có thể chọn `open-meteo`, còn API bỏ source vẫn giữ mặc định lịch sử theo giờ.

Chưa tích hợp: sensor-health là UNKNOWN / `analytics_not_integrated`; benchmark vẫn trả dữ liệu tham chiếu có thật nhưng `latest_bias=null`, `metrics={}`. Không có dữ liệu/cũ dùng `no_data`/`stale_data`; provider thiếu hoặc lỗi dùng `analytics_unavailable`/`analytics_failed`, không làm hỏng toàn bộ API hoặc giả báo cảm biến khỏe. Test TV1 dùng stub giao diện để kiểm tra adapter, không dùng stub làm thuật toán vận hành.

## Kiểm chứng TV1 không cần các module ngoài

```powershell
& backend/.venv/Scripts/python.exe -m pytest integration_tests/test_virtual_station.py integration_tests/test_simulator_payloads.py -q
& backend/.venv/Scripts/python.exe integration_tests/test_end_to_end.py --backend-tests --report-dir personal/tv1/verification/independent_run
```

Lệnh thứ hai tạo DB `weather_e2e_<id>` và MQTT prefix `e2e/<id>/weather`, chạy backend và suite độc lập trong cùng DB tạm, **chặn import toàn bộ module TV2/TV3 bằng import hook trong tiến trình thử**. Nhóm test đánh dấu `integrated_model` được loại trong chế độ này. Không đổi tên/xóa thư mục thành viên khác. Import hook phải tự xác nhận đã hoạt động trước khi kiểm tra. Cuối lượt khôi phục ngưỡng, dừng backend thử, xóa đúng DB được tạo; không dùng topic station01, không gửi Telegram và không điều khiển COM9.

Để kiểm chứng model thật, thêm `--integrated-models --backend-tests` và chọn thư mục report khác. Chế độ này bỏ import guard, bật cả hai provider `auto`, bắt buộc ba horizon nhiệt độ có nguồn model và kiểm tra phân tích/bias TV3 với nguồn tham chiếu live. Cả hai chế độ dùng cùng cơ chế cô lập DB/topic và cleanup; xem [hướng dẫn E2E](../../integration_tests/README.md).

VirtualStation là test double theo hợp đồng, kiểm tra nhận đúng thiết bị/topic và trạng thái còi 3 giây/LED 10 giây. Nó không phải giả lập CPU ESP8266, không chứng minh parser firmware giống hoàn toàn hoặc thời gian điện thực. Host tests C++ và kiểm tra phần cứng vẫn là các lớp bằng chứng riêng. `--dashboard` là kiểm tra trình duyệt tùy chọn; banner xác suất vượt ngưỡng không được hiểu là xác nhận thiết bị vật lý đã chạy.

## Còn chờ

Nghiệm thu trạm đủ cảm biến/tải/WiFi và nguồn/A0 trên phần cứng thật; artifact mưa đã hiệu chuẩn; chất lượng dự báo trên dữ liệu thật; Telegram thật khi được yêu cầu và có cấu hình. Không dùng dữ liệu tổng hợp hoặc DHT11 đơn lẻ để đánh dấu các mục này đạt.

# Hợp đồng dữ liệu v1 — trạm thời tiết

Phạm vi hiện tại: một backend worker, ESP8266 ADC 10-bit (backend cũng nhận ADC 12-bit cho ESP32), thời gian UTC, nhiệt độ °C, độ ẩm %, áp suất tại trạm hPa. Cấu hình/mẫu API là hợp đồng giữa firmware, backend, AI và Dashboard.

## Telemetry

Topic mặc định `weather/<device_id>/data`. `device_id` bắt buộc, gồm 1–50 ký tự ASCII chữ/số/`_`/`-`, khớp mã trạm trong topic. Các trường bắt buộc: `temperature`, `humidity`, `pressure` hữu hạn và `rain_detected` bằng 0/1. `rain_raw` có thể null hoặc số nguyên 0–4095; ESP8266 thực tế chỉ xuất 0–1023. Không dùng số giả thay trường thiếu/sai kiểu/NaN/Infinity. Mẫu đó bị loại và ghi lý do; không lưu DB hoặc phát WebSocket.

Giá trị hữu hạn ngoài khoảng cảm biến được giữ nguyên (không clamp) để kiểm tra sức khỏe. Chỉ loại giá trị vượt dung lượng cột DB. Inference dùng mẫu trong khoảng -40…85 °C, 0…100%, 300…1100 hPa giống firmware; không suy luận/kích hoạt ngoại vi khi mẫu mới nhất ngoài khoảng này. API forecast khi đó trả 409 `sensor_data_unusable`.

Nếu có `timestamp`, bắt buộc là ISO-8601 có timezone, được đổi UTC; timestamp lỗi hoặc quá tương lai (>5 giây) bị loại. Nếu không có, backend dùng thời điểm nhận. `timestamp_ms` là uptime, không phải UTC. Không gọi timestamp nhận là thời điểm đo chính xác.

Định danh mẫu có timestamp UTC là `(device_id, timestamp)`; hash lưu ở `message_key` có unique index, bản tin QoS 1 lặp không thêm bản ghi hoặc WebSocket mới. Mẫu cũ từ trước migration giữ nguyên. Với firmware chỉ có uptime, chỉ khử bản tin retransmit của phiên MQTT đang chạy bằng cache giới hạn; chưa cam kết exactly-once qua restart thiết bị/backend. Bước sau có thể bổ sung boot ID/sequence nếu cần mở rộng hợp đồng.

WebSocket chỉ phát sau khi DB commit thành công. MQTT subscribe có thể dùng tiền tố riêng trong môi trường E2E; cả `MQTT_TOPIC_PREFIX`, `MQTT_DATA_TOPIC` và topic alert phải đồng bộ để tách khỏi trạm thật.

## HTTP và Dashboard

- `/current`, `/history`, `/forecast` lọc đúng trạm. Forecast dùng cửa sổ 120 phút, không dùng timestamp tương lai; 404 `no_recent_measurements` khi không có mẫu. Mỗi horizon giữ `temperature_source=model|persistence|heuristic` và `rain_source=model|heuristic`.
- `GET /alerts/threshold` trả `{"threshold": 0.70}` từ DB hoặc cấu hình môi trường; POST trả `new_threshold` và cập nhật cùng giá trị mà API/tác vụ nền sử dụng.
- `GET /sensor-health?device_id=station01&window_minutes=360`: `status`, `checked_at`, `anomalies[{type,sensor,message,...}]`, `reason`. Không có mẫu hoặc mẫu mới nhất đã cũ thì `UNKNOWN`, không suy diễn thành cảm biến khỏe.
- `GET /benchmark?device_id=station01&source=open-meteo&hours=24`: `reference[]`, `latest_bias|null`, `metrics`, `reason`. Độ lệch là IoT trừ tham chiếu, ghép trung bình IoT ±5 phút quanh mốc tham chiếu, tối thiểu 3 mẫu/biến. Áp suất tham chiếu là surface pressure. Không có dữ liệu trả mảng rỗng/null, không dựng tham chiếu giả.
- Nguồn `open-meteo-15min` là bản tin hiện tại của crawler `--once`/`--loop` và là lựa chọn mặc định của Dashboard. `open-meteo` là lịch sử theo giờ và vẫn là mặc định API khi không truyền source; `openweather` được hỗ trợ riêng. Không trộn các nguồn tại cùng timestamp.

TV2/TV3 đã được hợp nhất từ `develop`. Mặc định `FORECAST_ENGINE_MODE=heuristic`, `ANALYTICS_ENGINE_MODE=disabled` để backend vẫn chạy độc lập; cài runtime inference rồi bật `auto` để dùng model/phân tích đã tích hợp. `/integrations` báo trạng thái cấu hình, không chứng nhận chất lượng model. Khi tắt analytics, sensor-health là UNKNOWN/`analytics_not_integrated`; benchmark trả raw reference thật nhưng `latest_bias=null`, `metrics={}`. `analysis_source` phân biệt chưa tích hợp/unavailable/external. Lỗi provider không làm hỏng toàn bộ API. Xem [hợp đồng bàn giao và chế độ độc lập](tv1_independent_handoff.md).

## Cảnh báo và AI

Topic `weather/<device_id>/alert`, `type=rain_warning`, `probability` 0–1, `forecast_minutes` 10/30/60, action `buzzer`, `led_blink`, `oled_message`. QoS 1, không retained. `mqtt_sent` chỉ có nghĩa broker đã ACK, chưa xác nhận relay/còi vật lý.

Ngưỡng dùng chung từ DB. `alert_triggered` là quyết định theo ngưỡng. Cooldown 180 giây/trạm/kênh của một worker, reset khi restart; chỉ đánh giá ngoại vi với mẫu mới trong 120 giây. Tác vụ nền 30 giây/lần.

Interface backend là `app.services.integrated_forecast.predict_forecast(recent_data, threshold)`, một trạm, cột device_id/timestamp/temperature/humidity/pressure/rain_detected/rain_raw. Adapter dùng `ml.inference_engine.get_engine().predict()` cho nhiệt độ và `inference.unified_forecast.predict_rain_forecast()` cho mưa; không nạp artifact nhiệt độ cũ trong `ai_engine`. TV2 yêu cầu ít nhất 90 phút thực, resample về 1 phút và tự kiểm tra gián đoạn/coverage; model mưa tối thiểu 61 phút, khuyến nghị 76 phút. Truy vấn 120 phút không bảo đảm chuỗi đủ liên tục để dùng model. Mỗi horizon ghi nguồn thực; nhiệt độ thiếu lịch sử/model dùng persistence nhưng vẫn giữ dự báo mưa hợp lệ. `FORECAST_ENGINE_MODE=heuristic` dành cho kiểm thử kỹ thuật có kết quả cố định, không chứng minh chất lượng model.

Output provider phải qua [JSON Schema](../contracts/forecast_provider.schema.json), kiểm tra hữu hạn/xác suất [0,1], timestamp có timezone và device khớp **trước actuation**. Backend tính lại quyết định ngưỡng. API thêm `forecast_engine=local_heuristic|external` và `fallback_reason` để phân biệt standalone, thiếu module, lỗi inference và output sai hợp đồng.

`forecast_engine=external` chỉ xác nhận adapter được gọi thành công. Kiểm tra thêm `temperature_model`, `temperature_confidence=normal|degraded|fallback`, `temperature_fallback_reason` và nguồn từng horizon. Provider cũ có thể bỏ metadata nhiệt độ (API trả null); không suy ra nguồn model từ trường vắng mặt. Banner dashboard báo xác suất đạt ngưỡng, không xác nhận MQTT đã gửi hay còi vật lý đã chạy.

## Nghiệm thu

Kiểm thử bộ phận khi thay đổi, chạy toàn bộ backend sau khi nhóm backend hoàn tất, rồi E2E trong DB/topic riêng. Lịch sử gieo sẵn là fixture, không coi là số đo thu thực. E2E khôi phục ngưỡng, dọn tài nguyên riêng và trả exit code lỗi khi fail. Không dùng 960 mẫu mô phỏng làm bằng chứng chất lượng dự báo khí tượng.

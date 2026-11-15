# Mốc 03 — Tiếp tục tích hợp khi BMP280 chưa đạt

Ngày: 04/11/2026. Nhánh: `feature/tv1-iot-backend`. Commit phần tích hợp được kiểm tra: `9b36fba` cùng các thay đổi phần cứng chưa commit đang có; không ghi đè chúng.

## Kết quả mới

Đã khởi động lại hai container phát triển có sẵn `weather_postgres_db` và `weather_mqtt_broker`, sau khi lượt E2E đầu dừng vì PostgreSQL chưa chạy. Lượt sau chạy `integration_tests/test_end_to_end.py --integrated-models` đạt **11/11 bước**.

Kiểm chứng MQTT → DB → API/WebSocket, loại bản tin sai/trùng, cảnh báo nền, cooldown, thay đổi ngưỡng, model nhiệt độ TV2 và phân tích TV3. Cả ba horizon nhiệt độ dùng XGBoost, confidence normal, không fallback. Dự báo mưa vẫn ghi nguồn heuristic vì chưa có artifact classifier mưa; không coi đó là model mưa đã nghiệm thu.

Báo cáo cục bộ: `personal/tv1/verification/20261104_continue_without_bmp_ready/e2e.json`. Fixture là dữ liệu tổng hợp. Trạm nhận cảnh báo cũng là giả lập; không kích board hay còi thật. Backend test đã dừng và DB tạm đã xóa; hai dịch vụ phát triển vẫn chạy. Lượt này không chạy lại toàn bộ suite backend hoặc kiểm tra trình duyệt.

## Có thể hoãn BMP không?

Có thể tiếp tục kiểm thử phần mềm, tích hợp provider, API, Dashboard và giao thức MQTT bằng dữ liệu tổng hợp tách riêng. Chưa thể nghiệm thu trạm thật đầy đủ hoặc đánh giá chất lượng dự báo bằng dữ liệu trạm khi áp suất chưa hợp lệ.

Hợp đồng telemetry hiện yêu cầu áp suất hữu hạn; firmware chính bỏ mẫu thiếu BMP. Không điền áp suất mặc định vào dữ liệu thật để vượt kiểm tra. Nếu cần lưu DHT11 trước khi có BMP, phải thiết kế riêng đường dữ liệu thiếu cảm biến và kiểm tra ảnh hưởng lên backend, Dashboard, analytics, model và cảnh báo trước khi bật.

## Trình tự tiếp theo

1. Giữ mốc phần mềm tích hợp đạt nêu trên; chỉ chạy lại E2E khi thay đổi có ảnh hưởng luồng này.
2. Chuẩn bị firmware chạy từng phần theo mạch hiện tại: DHT11 D5, relay D0, mưa DO D7, OLED D1/D2; thiếu BMP phải hiển thị rõ. Giữ dữ liệu chẩn đoán tách khỏi telemetry đầy đủ. Xác nhận lại việc hoàn trả dây OLED từ BMP trước khi nạp/chạy phần cứng.
3. Xác minh kết nối WiFi/MQTT, trạng thái online/offline và nhận lệnh trước; thử còi thật bằng lệnh chủ động có giới hạn thời gian sau khi xác nhận đấu nối. Chưa dùng dự báo giả lập để tự kích còi thật.
4. Bổ sung BMP đã đọc được dữ liệu hợp lệ; nghiệm thu riêng cảm biến rồi mới ghép lại bus I2C. Không lặp nguyên các lượt reset/thay chế độ đã thất bại nếu không có thay đổi phần cứng hoặc giả thuyết mới.
5. Chọn chính thức đường mưa DO hoặc AO. AO/A0 hiện chưa được xác minh điện áp. DO chỉ là trạng thái khô/ướt, không được gán thành ADC analog như thể đã đo.
6. Khi đủ dữ liệu hợp lệ mới nghiệm thu luồng trạm thật, mất mạng/phục hồi, cảnh báo và thu lịch sử thực liên tục trước khi đánh giá dự báo.

**Không nạp nguyên `main.cpp` lên mạch hiện tại:** D7 đang nối DO mưa nhưng main dùng D7 làm đầu ra LED; main dùng AO và nhiệt độ BMP. Bản chạy từng phần cần được triển khai, biên dịch và kiểm tra trước, chưa có trong mốc này.

BMP hiện chưa được xác định chắc là hỏng chip: đã nhận ID và đọc thanh ghi nhưng ADC nhiệt bằng 0, kể cả lượt dùng dây OLED. Cần đối chứng module hoặc đo nguồn để phân biệt lỗi module/header/tiếp xúc/nguồn. Giữ áp suất lỗi ngoài dữ liệu thật.

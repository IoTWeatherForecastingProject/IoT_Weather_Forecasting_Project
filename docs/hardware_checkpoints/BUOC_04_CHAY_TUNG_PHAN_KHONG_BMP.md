# Bước 04 — Chạy từng phần, chưa có BMP hợp lệ

Môi trường `esp8266_commissioning` chỉ build `firmware/src/commissioning.cpp`. Không thay chương trình trạm chính. Bản này đọc DHT11 D5, mưa DO D7, OLED D1/D2; relay D0 giữ tắt. Không đọc BMP hoặc A0, không subscribe cảnh báo thật, không có lệnh bật còi. Trạng thái điện trước setup cần quan sát riêng.

## Chuẩn bị khi đã rút USB

1. Tháo cả sáu dây khỏi module BMP. Các đầu dây rời không chạm nhau.
2. Trả OLED: VCC → 3V3 bên trái, GND → GND bên trái, SCK → hàng 20 chung D1, SDA → hàng 22 chung D2. Giữ dây cầu D1 → hàng 20 và D2 → hàng 22. Tọa độ áp dụng cho vị trí breadboard đã chụp; căn cứ nhãn chân nếu board đã di chuyển.
3. DHT11 OUT → D5, nguồn + → 3V3, − → GND.
4. Mưa DO → D7, VCC → 3V3, GND → GND; AO/A0 để rời. Giữ vị trí vít chỉnh khô HIGH, ướt LOW.
5. Relay IN → D0, jumper H. Nguồn giữ theo mốc 02. Dây đỏ còi tiếp tục tháo khỏi NO. Không nối hai thanh dương 3V3 và VIN với nhau.

## Cấu hình mạng

Điền `WIFI_SSID`, `WIFI_PASSWORD` trong `firmware/include/weather_config.h` (gitignore), dùng WiFi 2,4 GHz mà ESP có thể kết nối. Không gửi mật khẩu vào chat hoặc commit.

`MQTT_BROKER_HOST` là IPv4 WiFi/LAN của máy tính chạy Docker, không phải localhost/IP VMware/WSL. Cập nhật nếu máy đổi IP. Giữ tài khoản MQTT khớp broker. Máy tính và ESP phải có đường mạng đến nhau; mạng khách cách ly thiết bị có thể chặn kết nối.

## Build/nạp

```powershell
$env:PYTHONPATH = (Resolve-Path firmware/.pio/tools).Path
$env:PLATFORMIO_CORE_DIR = (Resolve-Path firmware/.pio/core).Path
& firmware/.venv/Scripts/python.exe -m platformio run --project-dir firmware --environment esp8266_commissioning
# Nạp sau khi xác nhận mạch và cổng thực tế:
& firmware/.venv/Scripts/python.exe -m platformio run --project-dir firmware --environment esp8266_commissioning --target upload --upload-port COM9
```

## Dữ liệu và lệnh chẩn đoán

Topic riêng, không khớp subscription `weather/+/data` của backend:

- `commissioning/<STATION_DEVICE_ID>/sample`: mỗi 5 giây, QoS 0, không retained, schema `commissioning.v1`.
- `commissioning/<STATION_DEVICE_ID>/status`: online retained và LWT offline.
- `commissioning/<STATION_DEVICE_ID>/command`: chỉ nhận `{"command":"ping","request_id":"<id mới>"}`. Không gửi retained.
- `commissioning/<STATION_DEVICE_ID>/reply`: event pong, đúng request_id, actuation_enabled false. Subscribe trước khi gửi; đối chiếu ID để tránh phản hồi cũ.

Mẫu ghi nguồn DHT11; nhiệt/ẩm null khi lỗi, pressure_hpa luôn null và pressure_status not_commissioned. Mưa có rain_source DO, rain_do_level và rain_detected; không gán DO thành rain_raw analog. Chưa đưa dữ liệu này vào DB/model/Dashboard của pipeline đầy đủ.

## Trình tự kiểm tra thực tế

1. UART 115200/OLED hiện TV1 PARTIAL CHECK, DHT hợp lệ, BMP NOT READY, Relay DISABLED; còi im, LED1 relay tắt.
2. WiFi/MQTT OK; thu tối thiểu ba mẫu MQTT mới với sequence/uptime tăng. UART không đủ để chứng minh publish thành công.
3. Gửi một ping có request_id mới, nhận pong tương ứng, không bật còi. LWT mất kết nối có độ trễ theo keepalive.
4. Khi mạng đạt mới thử khô/ướt tại cùng vị trí vít, chỉ làm ướt vạch đồng; ghi hai trạng thái qua MQTT.
5. Kiểm tra còi thật ở bước riêng bằng bản một xung đã có, sau khi xác nhận đấu dây.

Ngày 04/11/2026: bản mới biên dịch thành công. Chưa nạp hoặc nghiệm thu trên mạch. Cấu hình WiFi thay đổi cần build lại trước khi nạp.

## Kết quả nạp và kiểm tra mạng — 04/11/2026

Sau khi người dùng xác nhận đấu dây và điền WiFi, đã build/nạp `esp8266_commissioning` qua COM9, hash ghi flash được xác minh. Cấu hình cá nhân vẫn nằm trong file gitignore; không đưa mật khẩu vào báo cáo.

Thu đồng thời UART và MQTT trong 30 giây: **6/6 mẫu MQTT có DHT hợp lệ**, sequence và uptime tăng, WiFi/MQTT connected. Áp suất null/not_commissioned, actuation_enabled false, relay_command off. Mưa DO HIGH ở cả sáu mẫu, chưa thử ướt trong lượt này. Đã subscribe trước khi gửi một ping không retained có request_id mới; nhận pong không retained đúng ID và actuation_enabled false. Không gửi lệnh bật còi hoặc telemetry production.

Bằng chứng cục bộ: `personal/tv1/hardware_validation/20261104/commissioning_124747.json`. Kết quả này xác nhận đường mạng hai chiều và mẫu DHT tới MQTT; chưa xác nhận hiển thị trực quan, trạng thái tiếp điểm relay, khô/ướt qua MQTT, mất mạng/phục hồi hoặc DB/model của trạm thật. Đang chờ người dùng xác nhận OLED và LED1; bước sau là thử ướt có kiểm soát nếu hiển thị/relay bình thường.

Người dùng sau đó xác nhận OLED hiển thị đầy đủ và LED1 relay giữ tắt. Đã mở lượt ghi 45 giây riêng cho thử ướt, yêu cầu giữ nguyên biến trở và chỉ nhỏ nước lên vạch đồng. Chưa kết luận trạng thái ướt cho đến khi có dữ liệu MQTT và xác nhận thao tác.

Lượt 45 giây `commissioning_130115.json` chỉ ghi được trạng thái khô: 9/9 mẫu HIGH, DHT 9/9 hợp lệ. Người dùng sau đó xác nhận đã nhỏ nước, OLED WET và LED1 tắt. Lượt thu riêng sau xác nhận `commissioning_130540.json` kéo dài 20 giây: **4 mẫu MQTT, trong đó 2 mẫu LOW/rain_detected true và 2 mẫu HIGH/rain_detected false**, DHT 4/4 hợp lệ, sequence/uptime tăng, ping/pong đúng ID, relay_command off và actuation_enabled false. Đã nhận được trạng thái ướt qua đường cảm biến → ESP → MQTT nhưng chưa kết luận mức ướt ổn định; chưa có lượt xác nhận phục hồi khô sau lần làm ướt này. Không suy ra lượng mưa, độ chính xác khí tượng hoặc đường AO từ kết quả DO.

## Phục hồi khô và MQTT

Người dùng xác nhận đã lau khô, OLED DRY, COM9. Lượt `commissioning_130954.json` (20 giây) ghi **4/4 mẫu HIGH/rain_detected false**, DHT 4/4 hợp lệ, ping/pong đúng ID. Đã đối chiếu được chu trình DRY → WET → DRY qua MQTT với cùng yêu cầu giữ nguyên vít. Uptime vẫn tăng so với lượt trước, nên không dùng lượt này làm bằng chứng khởi động lại nguồn.

Tiếp theo đã dừng đúng container phát triển `weather_mqtt_broker`, chờ 12 giây rồi bật lại trong finally. Lượt `commissioning_131209.json` ghi UART MQTT offline và lỗi kết nối rc=-4 ở cuối cửa sổ. Đây chưa phải bằng chứng đã phục hồi trong chính cửa sổ đó. Sau khi xác nhận broker chạy lại, lượt `commissioning_131418.json` (20 giây) ghi **4/4 mẫu MQTT mới**, DHT hợp lệ, WiFi/MQTT connected, ping/pong đúng ID; sequence/uptime tăng so với trước gián đoạn. Không reset ESP, không nạp lại firmware hoặc gửi lệnh bật relay trong thử nghiệm. Không đo chính xác thời gian phục hồi và không coi đây là thử mất WiFi hay LWT.

Mốc đạt: DHT thật, OLED trực quan, mưa DO khô/ướt/khô, MQTT hai chiều và tự phục hồi khi broker trở lại. Firmware vẫn chỉ publish chẩn đoán, giữ relay tắt và áp suất null. Chưa nghiệm thu DB/model/Dashboard với dữ liệu trạm thiếu BMP. Bước phần mềm kế tiếp cần thiết kế đường nhận/hiển thị dữ liệu thiếu cảm biến có chất lượng rõ ràng; không đưa áp suất mặc định hoặc DO giả làm ADC vào hợp đồng telemetry đầy đủ.

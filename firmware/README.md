# MODULE 1: IOT HARDWARE & EMBEDDED FIRMWARE
## Trạm Đo Thời Tiết Cục Bộ Ngoài Trời (ESP8266 / ESP32)

> **Phụ trách chính:** 👤 **Thành viên 1 (IoT + Backend Engineer)**  
> **Phối hợp:** TV2 và TV3 hỗ trợ cơ khí hộp bảo vệ trạm đo ở Tuần 1.  
> **Các Task liên quan:** `IOT-01`, `IOT-02`, `IOT-03`, `IOT-04`, `IOT-05` (Xem chi tiết tại [TASK.md](../TASK.md)).

**Cấu hình đã chọn:** NodeMCU ESP8266 Amica, BMP280 đo nhiệt độ/áp suất, DHT11 đo độ ẩm, cảm biến mưa AO, OLED SH1106 1,3 inch, relay 5V đóng/cắt còi 5V và LED. Xem [danh sách cần mua](../docs/hardware_shopping_list.md). PlatformIO chọn `esp8266`/`nodemcuv2`.

---

## 1. Mục tiêu & Phạm vi Kỹ thuật

Xây dựng trạm đo ngoài trời có khả năng vận hành liên tục, ổn định trong môi trường thực tế:
1. Đọc nhiệt độ/áp suất từ **BMP280**, độ ẩm từ **DHT11** và trạng thái nước mưa từ **Rain Sensor**.
2. Lọc nhiễu tín hiệu trực tiếp trên vi điều khiển bằng bộ lọc trung bình trượt (**Moving Average Filter**).
3. Đóng gói JSON và truyền MQTT: PubSubClient publish telemetry ở **QoS 0**, subscribe cảnh báo ở **QoS 1**; tự kết nối lại khi mất mạng/broker.
4. Lắng nghe lệnh cảnh báo 2 chiều (**Closed-loop Actuation**) từ Backend để hiển thị cảnh báo lên màn hình **OLED SH1106**, kích hoạt **Còi Buzzer** và nhấp nháy **Đèn LED**.

---

## 2. Sơ đồ Đấu nối Chân (Pinout Wiring Diagram)

| Linh kiện | Loại giao tiếp | Chân trên Module | Chân ESP32 (Đề xuất) | Chân ESP8266 (NodeMCU) | Ghi chú |
|---|---|---|---|---|---|
| **BMP280** | I2C | VCC | 3.3V | 3.3V | Chọn module tương thích 3,3V |
| | | GND | GND | GND | Chung mass |
| | | SCL | GPIO 22 | D1 (GPIO 5) | Dùng điện trở kéo lên 3,3V trên module; chỉ bổ sung nếu thiếu |
| | | SDA | GPIO 21 | D2 (GPIO 4) | Địa chỉ I2C: `0x76` hoặc `0x77` |
| **Rain Sensor** | Analog / Digital | VCC | 3.3V | 3.3V | Module đã chọn hỗ trợ 3,3V |
| | | GND | GND | GND | Chung mass |
| | | AO (Analog) | GPIO 34 (ADC1_6) | A0 (ADC0) | Hiệu chỉnh ngưỡng và chiều khô/ướt theo số đo thực |
| | | DO (Digital) | Không dùng | Không dùng | Firmware chỉ đọc AO |
| **DHT11** | Digital | DATA | GPIO 14 | D5 (GPIO 14) | Cấp 3,3V; cảm biến trần cần điện trở kéo lên khoảng 10 kΩ |
| **OLED SH1106 1,3 inch** | I2C (Chung bus) | GND/VCC/SCL/SDA | GND/3,3V/GPIO 22/GPIO 21 | GND/3V3/D1/D2 | Địa chỉ I2C dự kiến `0x3C`; xác nhận bằng I2C scanner nếu cần |
| **Relay 5V → Buzzer 5V** | Digital Output / tiếp điểm | IN; COM–NO | GPIO 19 | D6 (GPIO 12) | D6 điều khiển IN, tiếp điểm đóng/cắt nguồn 5V cho còi. Xác minh relay nhận mức 3,3V; chỉnh HIGH/LOW trong `weather_config.h`. |
| **Status LED** | Digital Output | Anode (+) | GPIO 18 | D7 (GPIO 13) | Nối tiếp điện trở 220Ω - 330Ω |

Chỉ chân **AO** của module cảm biến mưa được firmware đọc. ESP8266 đọc ADC theo thang 0–1023. Chép mẫu `config.h.example` thành `weather_config.h`, rồi hiệu chỉnh `RAIN_ANALOG_THRESHOLD` và `RAIN_WET_IS_LOW` bằng log `[SENSOR] ... AO=...` lúc khô/ướt. Kiểm tra giới hạn điện áp A0 trước khi nối AO. BMP280 và DHT11 cần thông khí nhưng tránh mưa tạt; phần điện còn lại đặt trong hộp bảo vệ.

**Nguồn:** Cấp NodeMCU qua micro-USB 5V. BMP280, DHT11, OLED và module mưa tương thích 3,3V lấy từ chân 3V3; relay VCC và còi 5V lấy từ đường 5V USB qua chân VIN/VU **sau khi xác minh đường chân trên board** và nguồn USB đủ dòng. Nối 5V→COM relay, NO→cực dương còi, cực âm còi→GND. GND relay và các cảm biến nối chung GND ESP8266. Không cấp 5V cho GPIO hay chân 3V3; adapter 12V phải qua bộ hạ áp 5V.

---

## 3. Cấu trúc Thư mục Firmware

```text
firmware/
├── README.md               # Tài liệu hướng dẫn đấu nối, cấu hình và nạp code
├── platformio.ini          # Cấu hình PlatformIO (Dependencies, Board config)
├── include/
│   ├── config.h.example    # Mẫu để chép thành weather_config.h (được gitignore)
│   └── station_logic.h     # Lọc mẫu hợp lệ, ngưỡng mưa, thời gian relay/LED
├── src/
│   └── main.cpp            # Vòng lặp chính non-blocking, MQTT callback & state machine
└── test/
    ├── run_host_tests.py   # Chạy kiểm tra logic bằng g++ trên máy tính
    └── test_station_logic.cpp
```

---

## 4. Thiết kế Giao thức MQTT (MQTT Protocols)

### 4.1. Topics
- **Publish Dữ liệu cảm biến:** `weather/station01/data` (5 giây/lần, QoS 0, không retained).
- **Publish Trạng thái trạm:** `weather/station01/status` (LWT - Last Will and Testament: `online` / `offline`).
- **Subscribe Lệnh cảnh báo phản hồi:** `weather/station01/alert` (Backend gửi lệnh kích hoạt còi/đèn khi xác suất mưa cao).

### 4.2. Cấu trúc Payload JSON Gửi đi (`weather/station01/data`)
```json
{
  "device_id": "station01",
  "timestamp_ms": 15000,
  "temperature": 31.25,
  "humidity": 78.40,
  "pressure": 1005.82,
  "rain_raw": 900,
  "rain_detected": 0
}
```

`timestamp_ms` là thời gian từ khi khởi động, không phải UTC. Backend dùng thời điểm nhận gói để lưu `timestamp` UTC. `STATION_DEVICE_ID` là `station01`, độc lập với MQTT client ID. Telemetry không retained để tránh ghi lại mẫu cũ khi ingestion worker kết nối lại. Mẫu thiếu BMP280/DHT11 hoặc ngoài khoảng hợp lệ sẽ bị bỏ và xóa lịch sử lọc; mẫu đầu tiên khi phục hồi bắt đầu cửa sổ mới. Log vẫn in AO để hiệu chỉnh dù chưa gắn đủ cảm biến. BMP280 không tìm thấy sẽ được thử lại mỗi chu kỳ đo.

### 4.3. Cấu trúc Payload Nhận Cảnh báo (`weather/station01/alert`)
```json
{
  "type": "rain_warning",
  "probability": 0.85,
  "forecast_minutes": 30,
  "action": {
    "buzzer": true,
    "led_blink": true,
    "oled_message": "CANH BAO MUA (+30m: 85%)"
  }
}
```

---

## 5. Hướng dẫn Biên dịch & Nạp Firmware

### Cách 1: Sử dụng PlatformIO trong VS Code (Khuyến nghị)
1. Cài đặt Extension **PlatformIO IDE** trên VS Code.
2. Sao chép tệp mẫu cấu hình sang tệp chính thức:
   ```bash
   cp include/config.h.example include/weather_config.h
   ```
3. Mở `include/weather_config.h`, điền WiFi, IP và thông tin đăng nhập MQTT Broker. Nếu có `config.h` cũ, chuyển các thông số sang mẫu mới; không tiếp tục dùng tên chung `config.h` vì trùng header của toolchain ESP8266.
4. Kiểm tra board ESP8266 thực tế có phù hợp `nodemcuv2`; kết nối qua cáp USB dữ liệu rồi nhấn **PlatformIO: Build** và **PlatformIO: Upload**.
5. Mở **Serial Monitor** với tốc độ baud `115200` để quan sát log khởi động.

### Cách 2: Sử dụng Arduino IDE
1. Cài đặt board ESP32 hoặc ESP8266 qua Boards Manager.
2. Cài đặt các thư viện sau từ Library Manager:
   - `Adafruit BMP280 Library` và `DHT sensor library`
   - `PubSubClient` (Nick O'Leary)
   - `ArduinoJson` (Benoit Blanchon - phiên bản 6.x)
   - `Adafruit SH110X` & `Adafruit GFX Library`
3. Chép `src/main.cpp` thành `firmware.ino` trong thư mục sketch `firmware`, cùng `station_logic.h` và `weather_config.h`; chọn board NodeMCU 1.0 (ESP-12E Module). Khi dùng mẫu cấu hình thay cho file cá nhân, cũng chép `config.h.example` vào thư mục sketch.

### Kiểm tra trước khi nạp

Từ thư mục gốc dự án:

```bash
python firmware/test/run_host_tests.py
pio run --project-dir firmware --environment esp8266
```

Bài kiểm tra logic cần Python và g++; kiểm tra bộ lọc khi cảm biến lỗi/phục hồi, ngưỡng mưa hai chiều, lệnh cảnh báo lặp, tắt còi sau 3 giây và `millis()` quay vòng. Build dùng mẫu khi chưa tạo `weather_config.h` và không cần cắm board. Với PlatformIO, lệnh upload là `pio run --project-dir firmware --environment esp8266 --target upload`.

OLED được thử ở `0x3C`, rồi `0x3D`; BMP280 ở `0x76`, rồi `0x77`. Các địa chỉ, chu kỳ và GPIO chỉnh trong cấu hình. Nếu OLED khởi tạo thất bại, trạm tiếp tục đọc/gửi dữ liệu. Mỗi cảnh báo hợp lệ bật relay tối đa 3 giây, LED nháy trong 10 giây; đọc `action.buzzer`, `action.led_blink`, `action.oled_message`. Lệnh dành cho trạm khác bị bỏ; lệnh lặp khi cảnh báo còn chạy không kéo dài chu kỳ. Firmware hoãn thử kết nối lại broker trong chu kỳ cảnh báo. MQTT và driver cảm biến vẫn có thao tác đồng bộ, nên thời gian thực phải đo lại trên board.

---

## 6. Tiêu chí Nghiệm thu Hoàn thành (DoD của Module)

- [ ] Trạm khởi động, tự động kết nối WiFi và MQTT Broker thành công trong vòng < 15 giây.
- [ ] Dữ liệu nhiệt độ, độ ẩm, áp suất không bị nhảy giật bất thường (đã áp dụng Moving Average).
- [ ] Khi ngắt WiFi hoặc tắt Broker rồi bật lại, ESP tự động reconnect mà không cần bấm nút reset phần cứng.
- [ ] Khi gửi thử một payload JSON vào topic `weather/station01/alert`, relay đóng cấp nguồn cho còi trong khoảng 3 giây, LED chớp trong 10 giây và OLED hiện cảnh báo. Nếu module relay kích mức LOW, đặt `RELAY_ACTIVE_LEVEL LOW` trong `weather_config.h`.
- [ ] Ngắt DHT11/BMP280: không gửi mẫu cũ như mẫu mới; nối lại cảm biến và kiểm tra dữ liệu phục hồi. Ngắt OLED khi tắt nguồn rồi khởi động: trạm vẫn gửi telemetry.
- [ ] Gửi cảnh báo lặp và ngắt broker khi còi đang bật: đo lại relay tắt đúng thời gian, không bị giữ liên tục.

Build và host tests chưa chứng minh đường cấp nguồn, điện áp A0 hoặc độ ổn định khi nối đầy đủ phụ kiện; các mục nghiệm thu trên cần chạy với phần cứng thật.


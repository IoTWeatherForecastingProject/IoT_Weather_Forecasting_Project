# MODULE 1: IOT HARDWARE & EMBEDDED FIRMWARE
## Trạm Đo Thời Tiết Cục Bộ Ngoài Trời (ESP8266 / ESP32)

> **Phụ trách chính:** 👤 **Thành viên 1 (IoT + Backend Engineer)**  
> **Phối hợp:** TV2 và TV3 hỗ trợ cơ khí hộp bảo vệ trạm đo ở Tuần 1.  
> **Các Task liên quan:** `IOT-01`, `IOT-02`, `IOT-03`, `IOT-04`, `IOT-05` (Xem chi tiết tại [TASK.md](../TASK.md)).

**Trạm nhóm đang chuẩn bị:** ESP8266 hiện có, cùng DHT11, còi 5V, relay 1 kênh 5V và LED. Firmware chính vẫn cần BME280 để có dữ liệu áp suất, cảm biến mưa và OLED SSD1306. DHT11 chỉ dùng cho chương trình thử riêng; bản firmware này chưa đọc DHT11. Xem [danh sách cần mua](../docs/hardware_shopping_list.md). Mặc định PlatformIO đã chọn `esp8266`/`nodemcuv2`; kiểm tra đúng biến thể board thực tế trước khi nạp.

---

## 1. Mục tiêu & Phạm vi Kỹ thuật

Xây dựng trạm đo ngoài trời có khả năng vận hành liên tục, ổn định trong môi trường thực tế:
1. Đọc dữ liệu từ cảm biến áp suất/nhiệt/ẩm **BME280** và cảm biến phát hiện nước mưa (**Rain Sensor**).
2. Lọc nhiễu tín hiệu trực tiếp trên vi điều khiển bằng bộ lọc trung bình trượt (**Moving Average Filter**).
3. Đóng gói dữ liệu dạng JSON chuẩn và truyền về máy chủ qua giao thức **MQTT (QoS 1)** với cơ chế **Auto-reconnect** chống mất kết nối mạng.
4. Lắng nghe lệnh cảnh báo 2 chiều (**Closed-loop Actuation**) từ Backend để hiển thị cảnh báo lên màn hình **OLED SSD1306**, kích hoạt **Còi Buzzer** và nhấp nháy **Đèn LED**.

---

## 2. Sơ đồ Đấu nối Chân (Pinout Wiring Diagram)

| Linh kiện | Loại giao tiếp | Chân trên Module | Chân ESP32 (Đề xuất) | Chân ESP8266 (NodeMCU) | Ghi chú |
|---|---|---|---|---|---|
| **BME280** | I2C | VCC | 3.3V | 3.3V | Tuyệt đối không cắm 5V |
| | | GND | GND | GND | Chung mass |
| | | SCL | GPIO 22 | D1 (GPIO 5) | Kéo trở nội hoặc ngoài 4.7k |
| | | SDA | GPIO 21 | D2 (GPIO 4) | Địa chỉ I2C: `0x76` hoặc `0x77` |
| **Rain Sensor** | Analog / Digital | VCC | 3.3V / 5V | 3.3V | Cấp nguồn qua transistor nếu muốn tiết kiệm điện |
| | | GND | GND | GND | Chung mass |
| | | AO (Analog) | GPIO 34 (ADC1_6) | A0 (ADC0) | Đọc độ ướt (0: ướt sũng, 1023/4095: khô) |
| | | DO (Digital) | GPIO 35 | D5 (GPIO 14) | Tín hiệu logic (LOW khi có mưa) |
| **OLED SSD1306** | I2C (Chung bus) | SCL / SDA | GPIO 22 / 21 | D1 / D2 | Địa chỉ I2C: `0x3C` |
| **Relay 5V → Buzzer 5V** | Digital Output / tiếp điểm | IN; COM–NO | GPIO 19 | D6 (GPIO 12) | D6 điều khiển IN, tiếp điểm đóng/cắt nguồn 5V cho còi. Xác minh relay nhận mức 3,3V; chỉnh HIGH/LOW trong `config.h`. |
| **Status LED** | Digital Output | Anode (+) | GPIO 18 | D7 (GPIO 13) | Nối tiếp điện trở 220Ω - 330Ω |

Chỉ chân **AO** của module cảm biến mưa được firmware đọc; chân DO trong bảng chưa được dùng. ESP8266 đọc ADC theo thang 0–1023. Giá trị ngưỡng mẫu trong `config.h.example` cần hiệu chỉnh bằng số đo khô/ướt. Kiểm tra giới hạn điện áp A0 của board đang có trước khi nối AO. BME280 cần thông khí ngoài trời nhưng tránh mưa tạt; phần điện còn lại đặt trong hộp bảo vệ.

---

## 3. Cấu trúc Thư mục Firmware

```text
firmware/
├── README.md               # Tài liệu hướng dẫn đấu nối, cấu hình và nạp code
├── platformio.ini          # Cấu hình PlatformIO (Dependencies, Board config)
├── include/
│   ├── config.h.example    # Tệp mẫu cấu hình WiFi, MQTT, GPIO pins
│   ├── sensor_filters.h    # Thuật toán lọc trung bình trượt Moving Average
│   └── display_oled.h      # Hàm vẽ giao diện hiển thị OLED
├── src/
│   └── main.cpp            # Vòng lặp chính non-blocking, MQTT callback & state machine
└── docs/
    ├── schematic.pdf       # Sơ đồ nguyên lý mạch trạm đo
    └── enclosure_design.md # Hướng dẫn lắp ráp cơ khí hộp bảo vệ chống nước
```

---

## 4. Thiết kế Giao thức MQTT (MQTT Protocols)

### 4.1. Topics
- **Publish Dữ liệu cảm biến:** `weather/station01/data` (Publish định kỳ 5s - 10s một lần).
- **Publish Trạng thái trạm:** `weather/station01/status` (LWT - Last Will and Testament: `online` / `offline`).
- **Subscribe Lệnh cảnh báo phản hồi:** `weather/station01/alert` (Backend gửi lệnh kích hoạt còi/đèn khi xác suất mưa cao).

### 4.2. Cấu trúc Payload JSON Gửi đi (`weather/station01/data`)
```json
{
  "device_id": "station01",
  "timestamp": "2026-09-12T10:30:00Z",
  "temperature": 31.25,
  "humidity": 78.40,
  "pressure": 1005.82,
  "rain_raw": 1820,
  "rain_detected": 0
}
```

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
   cp include/config.h.example include/config.h
   ```
3. Mở `include/config.h` và điền tên WiFi, mật khẩu và IP của MQTT Broker máy tính nội bộ.
4. Kiểm tra board ESP8266 thực tế có phù hợp `nodemcuv2`; kết nối qua cáp USB dữ liệu rồi nhấn **PlatformIO: Build** và **PlatformIO: Upload**.
5. Mở **Serial Monitor** với tốc độ baud `115200` để quan sát log khởi động.

### Cách 2: Sử dụng Arduino IDE
1. Cài đặt board ESP32 hoặc ESP8266 qua Boards Manager.
2. Cài đặt các thư viện sau từ Library Manager:
   - `Adafruit BME280 Library`
   - `PubSubClient` (Nick O'Leary)
   - `ArduinoJson` (Benoit Blanchon - phiên bản 6.x trở lên)
   - `Adafruit SSD1306` & `Adafruit GFX Library`
3. Đổi tên `src/main.cpp` thành `firmware.ino` và mở bằng Arduino IDE để nạp.

---

## 6. Tiêu chí Nghiệm thu Hoàn thành (DoD của Module)

- [ ] Trạm khởi động, tự động kết nối WiFi và MQTT Broker thành công trong vòng < 15 giây.
- [ ] Dữ liệu nhiệt độ, độ ẩm, áp suất không bị nhảy giật bất thường (đã áp dụng Moving Average).
- [ ] Khi ngắt WiFi hoặc tắt Broker rồi bật lại, ESP tự động reconnect mà không cần bấm nút reset phần cứng.
- [ ] Khi gửi thử một payload JSON vào topic `weather/station01/alert`, relay đóng cấp nguồn cho còi trong khoảng 3 giây, LED chớp trong 10 giây và OLED hiện cảnh báo. Nếu module relay kích mức LOW, đặt `RELAY_ACTIVE_LEVEL LOW` trong `config.h`.


# MODULE 1: IOT HARDWARE & EMBEDDED FIRMWARE

**Chạy với mạch hiện tại khi BMP chưa đạt:** dùng môi trường `esp8266_commissioning` theo [bước 04](../docs/hardware_checkpoints/BUOC_04_CHAY_TUNG_PHAN_KHONG_BMP.md). Bản này đọc DHT11/mưa DO, giữ relay D0 tắt và dùng topic chẩn đoán riêng; không nạp bản trạm chính dùng AO/D7 LED lên mạch đang nối DO ở D7.

## Trạm Đo Thời Tiết Cục Bộ Ngoài Trời (ESP8266 / ESP32)

> **Phụ trách chính:** 👤 **Thành viên 1 (IoT + Backend Engineer)**  
> **Phối hợp:** TV2 và TV3 hỗ trợ cơ khí hộp bảo vệ trạm đo ở Tuần 1.  
> **Các Task liên quan:** `IOT-01`, `IOT-02`, `IOT-03`, `IOT-04`, `IOT-05` (Xem chi tiết tại [TASK.md](../TASK.md)).

**Cấu hình đã chọn:** NodeMCU ESP8266 Amica, BMP280 đo nhiệt độ/áp suất, DHT11 đo độ ẩm, cảm biến mưa AO, OLED SH1106 1,3 inch, relay 5V đóng/cắt còi 5V và LED. Xem [danh sách cần mua](../docs/hardware_shopping_list.md). PlatformIO chọn `esp8266`/`nodemcuv2`.

**Mốc hiện tại:** [Mốc 02 — breadboard, relay D0, 03/11/2026](../docs/hardware_checkpoints/MOC_02_BREADBOARD_RELAY_D0_2026-11-03.md).

**Mốc đấu dây cũ đã thử để xem lại:** [Mốc 01 — trước khi thêm module áp suất, 03/11/2026](../docs/hardware_checkpoints/MOC_01_DAU_DAY_DA_THU_2026-11-03.md). Mốc này dùng mưa **DO → D7**, AO/A0 để rời và firmware `esp8266_rain_do`; cần đọc đúng mốc khi khôi phục mạch thử.

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
| **Relay 5V → Buzzer 5V** | Digital Output / tiếp điểm | IN; COM–NO | GPIO 19 | D0 (GPIO 16) | D0 điều khiển IN, tiếp điểm đóng/cắt nguồn 5V cho còi. Xác minh relay nhận mức 3,3V; chỉnh HIGH/LOW trong `weather_config.h`. |
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
3. Chép `src/main.cpp` thành `firmware.ino` trong thư mục sketch `firmware`, cùng `station_logic.h`, `board_wiring.h`, `bmp_quality.h` và `weather_config.h`; chọn board NodeMCU 1.0 (ESP-12E Module). Khi dùng mẫu cấu hình thay cho file cá nhân, cũng chép `config.h.example` vào thư mục sketch.

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

## Thử DHT11 riêng khi chưa đủ cảm biến

Môi trường `esp8266_dht11` chỉ đọc DHT11 trên D5/GPIO14 và in JSON UART 115200 mỗi 2,5 giây. Không publish telemetry thiếu áp suất/mưa; giữ relay D0 LOW từ setup. Xác nhận VCC/DATA/GND theo đúng module trước khi đấu, tắt nguồn USB khi đổi dây. Bài thử là bước riêng, chưa phải nghiệm thu trạm đầy đủ.

```powershell
pio run --project-dir firmware --environment esp8266_dht11
# Chỉ upload sau khi đã kiểm tra sơ đồ chân/cổng và lưu firmware cũ:
pio run --project-dir firmware --environment esp8266_dht11 --target upload --upload-port COM9
```

Nếu PlatformIO đã được cài trong cache cục bộ của dự án, có thể chạy bằng môi trường sẵn có:

```powershell
$env:PYTHONPATH = (Resolve-Path firmware/.pio/tools).Path
$env:PLATFORMIO_CORE_DIR = (Resolve-Path firmware/.pio/core).Path
& firmware/.venv/Scripts/python.exe -m platformio run --project-dir firmware --environment esp8266_dht11
```

Đừng ghi đè firmware đang dùng trước khi có bản sao lưu nếu cần phục hồi. Môi trường `esp8266` vẫn chỉ build `main.cpp`; môi trường thử chỉ build `dht11_check.cpp`.

## Thử relay riêng cùng DHT11

Môi trường `esp8266_relay` build `src/relay_check.cpp`, UART 115200. Chỉ dùng cho module đã xác nhận đầu vào tương thích mức 3,3 V với jumper H: D6/GPIO12 → IN; DHT11 giữ D5/GPIO14. Ngắt USB khi đổi dây và tháo hoàn toàn dây thử nối IN với DC+ trước khi nối GPIO. Nguồn cuộn hút đi qua DC+/DC−, không lấy từ GPIO; NO/COM/NC và còi để rời trong bài thử này.

```powershell
pio run --project-dir firmware --environment esp8266_relay
```

Sau khi xác nhận dây và sao lưu firmware cũ mới upload môi trường này. Khi `setup()` chạy, D6 được đặt LOW; firmware không bảo đảm trạng thái điện trong giai đoạn trước `setup()`. Gửi `STATUS` kèm newline để đọc trạng thái, `RUN` kèm newline để chạy đúng ba chu kỳ HIGH 3 giây / LOW 5 giây, cuối lượt giữ LOW. `STOP` ngắt lượt và đặt LOW. RUN chỉ được chấp nhận một lần mỗi lần khởi động; reset cho phép một lượt mới nhưng không tự chạy. DHT11 tiếp tục được đọc mỗi 2,5 giây. JSON RELAY ghi **lệnh GPIO**, cần quan sát LED/tiếng đóng nhả độc lập; log không xác nhận tiếp điểm hay độ chính xác cảm biến. Không có MQTT hoặc dữ liệu áp suất/mưa giả.

Khi còi đã nối qua COM/NO, dùng môi trường `esp8266_buzzer_single`: cùng chương trình nhưng đặt `RELAY_CHECK_SINGLE_PULSE=1`, giới hạn ngay trong firmware chỉ một xung HIGH khoảng 3 giây cho mỗi lần khởi động. Nó vẫn chờ `RUN`, tự về LOW và từ chối RUN lặp. OLED không được cập nhật trong bài thử này. Sau bài thử cần chọn lại đúng môi trường trước khi thử OLED/mưa hoặc áp suất.

Môi trường `esp8266_buzzer_d0` dùng cùng giới hạn một xung nhưng chọn `RELAY_CHECK_GPIO=16`: relay IN → **D0/GPIO16** (a15 theo vị trí breadboard đã chụp), DHT11 vẫn D5. D6 cũ được giữ LOW trong setup để chuyển dây có kiểm soát. Khi thu log bằng `run_relay_check.py`, truyền `--expected-gpio 16` cùng đường dẫn binary tương ứng. Ngày 03/11/2026 đã xác nhận còi kêu, relay/LED1 bật rồi tắt trong xung 3000 ms, DHT11 6/6 mẫu hợp lệ và không reset. Cấu hình trạm chính cùng bài thử DHT11/OLED/mưa/áp suất hiện dùng relay D0 theo `board_wiring.h`. `esp8266_relay` và `esp8266_buzzer_single` vẫn là bài thử D6 lịch sử; không dùng chúng để kích relay đang nối D0.

## Thử OLED riêng

Môi trường `esp8266_oled` chỉ build `oled_check.cpp`: OLED VCC → 3V3, GND → GND, SCK/SCL → D1/GPIO5, SDA → D2/GPIO4. Tắt USB khi đấu dây. Relay có jumper H và IN → D0/GPIO16 được giữ LOW từ setup; không có lệnh kích còi, WiFi/MQTT hoặc số đo giả. Quét I2C, chọn địa chỉ 0x3C/0x3D rồi dùng driver SH1106 128×64 để vẽ chữ, bộ đếm, khung đủ bốn cạnh và chấm chuyển động.

```powershell
pio run --project-dir firmware --environment esp8266_oled
# Chỉ nạp sau khi xác nhận dây và cổng thực tế:
pio run --project-dir firmware --environment esp8266_oled --target upload --upload-port COM9
```

UART 115200 có sự kiện `i2c_ack`, `init`, `frame`. ACK hoặc driver_ready không chứng minh ảnh hiển thị hoặc định danh silicon: cần người dùng xác nhận trực quan không lệch/cắt/rác. Thử ngày 02/11/2026 đã thấy ACK 0x3C, 12 frame tăng sau reset và người dùng xác nhận hiển thị đầy đủ/còi im. Đây là thử OLED riêng, chưa nghiệm thu ghép đủ cảm biến.

## Thử tín hiệu số của cảm biến mưa

Môi trường `esp8266_rain_do` chỉ build `rain_do_check.cpp`, giữ relay D0 ở LOW và hiển thị trạng thái D7 trên OLED. Với module HW-103 v0.12 đã chụp ảnh, nối VCC → 3V3, GND → GND, DO → D7/GPIO13, tấm dò → giắc hai chân của module; để AO và A0 rời. Không dùng môi trường này làm chương trình trạm: ở `main.cpp`, D7 là chân LED trạng thái và dữ liệu mưa lấy từ AO/A0.

```powershell
pio run --project-dir firmware --environment esp8266_rain_do
# Chỉ nạp khi đã xác nhận dây và đúng cổng:
pio run --project-dir firmware --environment esp8266_rain_do --target upload --upload-port COM9
```

OLED ghi `D7 HIGH (1)` hoặc `D7 LOW (0)` và số lần đổi `Changes`; UART 115200 in JSON `RAIN_DO` mỗi 250 ms. Điều chỉnh biến trở từng nấc nhỏ để tấm dò khô cho HIGH, nước nối qua các vạch đồng cho LOW **ở cùng một vị trí vít**. Ngày 02/11/2026, người dùng xác nhận được hai trạng thái sau chỉnh ngưỡng. COM9 ghi 21 mẫu LOW liên tiếp lúc ướt trước lượt chỉnh cuối và 21 mẫu HIGH liên tiếp lúc khô sau lượt chỉnh cuối; không có log UART của lượt ướt sau cùng. Relay được giữ OFF trong toàn bộ bài thử. Kết quả chỉ xác nhận đường DO; chưa đo điện áp AO/A0 hoặc hiệu chỉnh trị số analog cho chương trình trạm.

## Nhận dạng module áp suất qua I2C

Môi trường `esp8266_pressure` build `pressure_check.cpp`, giữ relay D0 ở LOW, quét địa chỉ 0x76/0x77 và đọc mã chip ở thanh ghi 0xD0. Nó chỉ dùng thư viện BMP280 để đọc nhiệt độ/áp suất khi ID là `0x58`; ID `0x60` được báo là BME280 và cần driver thích hợp ở bước sau. OLED vẫn chia sẻ D1/D2 và hiện kết quả. Không có WiFi/MQTT, đọc AO hoặc kích còi.

Rút USB trước khi đấu dây. Theo **ký hiệu trên chính module GY-BM E/P280**, nối VCC → 3V3, GND → GND, SCL → D1/GPIO5, SDA → D2/GPIO4, CSB → 3V3, SDO → GND. Không suy ra thứ tự từ góc nhìn mặt trước/mặt sau vì bị đảo trái–phải. Trên chip Bosch, CSB ở mức cao chọn I2C và SDO ở mức thấp chọn 0x76; module thực tế vẫn phải được xác nhận bằng mã chip. Dùng 3V3, không cấp 5V. Kiểm tra mối hàn không chập nhau trước khi cắm USB.

```powershell
pio run --project-dir firmware --environment esp8266_pressure
# Chỉ nạp sau khi xác nhận dây và cổng thực tế:
pio run --project-dir firmware --environment esp8266_pressure --target upload --upload-port COM9
```

UART 115200 in `identity`, `bmp_init`, `sample` hoặc `not_found`. Nếu không tìm thấy chip, kiểm tra lại dây nguồn, SDA/SCL, CSB/SDO và mối hàn lúc đã rút USB; không gán một giá trị áp suất giả. Đây là bài thử nhận dạng/đọc sơ bộ, chưa phải hiệu chuẩn độ chính xác hoặc nghiệm thu trạm đầy đủ.

Bản chẩn đoán ghi thêm `registers`, `soft_reset`, `mode_probe` và mức `relay_observed_level`. Nó reset chip, chờ NVM với timeout, thử forced x1/x1 rồi chạy normal nhiệt x2/áp suất x16. Bản thử BMP riêng trước đây dùng `range_ok=false` và OLED `INVALID READING`; bản kết hợp hiện tại dùng `pressure_valid=false` và `BMP P: INVALID`. `bmp_ready=true` chỉ cho biết driver đã khởi tạo. `Relay cmd: OFF` là lệnh, không xác nhận tiếp điểm. Thử ngày 03/11/2026 nhận ID 0x58/0x76 nhưng ADC nhiệt sau đo luôn 0, chưa đạt; chi tiết cục bộ ở `personal/tv1/hardware_validation/20261103/PRESSURE_RESULT.md`.

Cập nhật bài đọc kết hợp theo yêu cầu người dùng: môi trường `esp8266_pressure` hiện đọc **nhiệt độ/độ ẩm từ DHT11 D5**, áp suất từ BMP280, chu kỳ 2,5 giây. JSON `SENSORS` ghi rõ nguồn; `PRESSURE` tiếp tục ghi các thanh ghi chẩn đoán. `pressure_valid` kiểm tra riêng BMP; khi chưa đạt, `pressure_hpa=null`, trị số tính được chỉ nằm ở `pressure_candidate_hpa` và OLED ghi `BMP P: INVALID`. `bmp_temperature_c` là nhiệt độ nội bộ dùng để kiểm tra khả năng bù áp suất, không thay thế nhiệt độ DHT11 đang hiển thị. Lượt 03/11/2026: DHT11 9/9 lần đọc được, áp suất 0/9 mẫu hợp lệ. Bài này không publish telemetry hoặc kích relay.

Kiểm tra chất lượng hiện dùng `bmp_quality.h` trong cả bài thử và `main.cpp`: loại lỗi đọc thanh ghi, kênh đo bị tắt, ADC mặc định `0x80000` và giá trị ADC zero/bão hòa trước khi xét dải số. Dữ liệu reset từng bù thành 23,36°C/680,21 hPa dù chưa có phép đo; trường hợp này đã được thêm vào kiểm thử hồi quy. Firmware chính loại mẫu và xóa lịch sử lọc theo cơ chế hiện có; bản chính chưa được nạp lên mạch DO hiện tại.

## OLED của trạm DO hiện tại

Môi trường đang chạy trên NodeMCU là `esp8266_station_do` (`commissioning.cpp`). OLED 128×64 hiển thị bằng tiếng Anh: trạng thái MQTT `ONLINE/OFFLINE`, nhiệt độ từ DHT11, độ ẩm `RH`, áp suất `P` từ BMP280, trạng thái tấm dò `RAIN: DRY/WET`, và xác suất mưa dự báo `RAIN FCST +10M/+30M/+60M: n%`. Dòng `RAIN: WET` là tín hiệu đo tại tấm dò; dòng `RAIN FCST` là kết quả dự báo của backend. Mốc hiện trên màn là mốc có xác suất lớn nhất trong ba mốc dự báo, ưu tiên +30 phút nếu bằng nhau như logic cảnh báo.

Backend gửi bản tin JSON ngắn đến `weather/{device_id}/forecast` khi có mẫu đo mới hợp lệ và đã kết nối MQTT. Bản tin không được lưu lại trên broker; firmware hiển thị `RAIN FCST: WAITING` trước khi nhận bản tin hoặc khi bản tin đã quá 90 giây. Khởi động lại backend và nạp lại firmware đều cần thiết khi thay đổi giao thức này. Lệnh cảnh báo còi vẫn đi qua topic `weather/{device_id}/alert` riêng.

Module RGB 4 chân loại common GND trong ảnh của trạm có sẵn điện trở từng kênh (`R 471`, `G 271`, `B 271`). Bản firmware hiện dùng R→D8/GPIO15, G→TX/GPIO1, B→D4/GPIO2, GND→GND chung. D6 đã bỏ vì tiếp xúc breadboard không ổn định. Màu đỏ ưu tiên khi DO mưa ở LOW; nếu khô, màu xanh dương sáng khi bản tin dự báo mới nhất đạt ngưỡng backend; xanh lá sáng khi dự báo còn mới và dưới ngưỡng. Mất MQTT hoặc dự báo quá 90 giây khiến đèn tắt nếu không mưa. Thời gian chờ cảnh báo còi không chi phối màu đèn. TX là chân UART0 dùng để nạp và in log: đèn xanh lá có thể nháy trong lúc khởi động/nạp, và firmware này không in log USB nữa nhưng vẫn gửi mẫu chẩn đoán qua MQTT. Nếu upload gặp lỗi khi RGB đã nối, tháo riêng dây G khỏi TX lúc đã rút USB rồi nạp lại. GPIO15 phải LOW và GPIO2 phải HIGH khi ESP8266 khởi động; B→D4 đã được thử khởi động và nạp thành công với module này. Không nối RGB vào VIN/5V hoặc đấu dây khi USB còn cấp điện.


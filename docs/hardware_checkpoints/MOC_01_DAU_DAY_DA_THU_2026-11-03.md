# Mốc 01 — Cách đấu dây đã thử trước khi thêm module áp suất

> Mốc lịch sử dùng relay D6. Cách đấu hiện tại đã chuyển relay sang D0: xem [Mốc 02](MOC_02_BREADBOARD_RELAY_D0_2026-11-03.md). Để khôi phục đúng mốc D6 bằng mã hiện tại, dùng môi trường `esp8266_rain_do_legacy_d6`.

Ngày lưu: **03/11/2026**, giờ Việt Nam. Người dùng xác nhận mạch vẫn giữ nguyên sau các bài thử trước; **module áp suất đã hàn chân nhưng chưa nối vào mạch**, breadboard chưa được dùng để bố trí lại.

Đây là mốc để đấu lại NodeMCU ESP8266 + DHT11 + OLED + module mưa DO + relay/còi. Các phần đã được thử theo từng chương trình riêng. Chương trình đang nạp gần nhất là **`esp8266_rain_do`**, chỉ kiểm tra OLED/mưa và giữ relay tắt; chưa phải chương trình trạm đầy đủ.

## 1. Nguồn và cách đọc tên chân

- NodeMCU nhận nguồn qua cổng **micro-USB**; cổng máy tính đã dùng là **COM9**. COM có thể đổi khi chuyển máy hoặc cổng USB.
- Đọc tên in trên NodeMCU: **D1, D2, D5, D6, D7, 3V3, GND, VIN**. D1 không phải GPIO1.
- Các chân 3V3 của board thuộc cùng đường nguồn 3,3 V; các chân GND thuộc cùng đường mass. Các module dùng chung GND với NodeMCU.
- Rút USB trước khi đấu/chuyển dây. Dùng 3V3 cho DHT11, OLED và module mưa. Nguồn 5 V của relay/còi đi theo đường VIN đã dùng trong bài thử cũ.
- Mốc này ghi các điểm cần nối điện; chưa ấn định số hàng/lỗ trên breadboard.

## 2. DHT11 — giữ D5

Module ba chân. Theo ảnh mặt có vỏ xanh hướng về người nhìn, chân cắm hướng xuống: bên trái là `+`, giữa là `OUT`, bên phải là `−`. Ưu tiên ký hiệu trên chính module nếu đổi góc nhìn.

- DHT11 `+` → NodeMCU **3V3**.
- DHT11 `OUT` (chân giữa) → NodeMCU **D5 / GPIO14**.
- DHT11 `−` → NodeMCU **GND**.

Đã thử bằng `esp8266_dht11`: tổng 86/86 mẫu hợp lệ qua các lượt đọc, reset, khum tay và phục hồi. Đây là thử chức năng/phản ứng, chưa hiệu chuẩn độ chính xác.

## 3. OLED 1,3 inch — D1/D2

Module ghi `1.30 IIC Ver 3.1`. Nhìn mặt màn hình theo ảnh cũ, dãy chân ghi `GND VCC SCK SDA`.

- OLED `GND` → NodeMCU **GND**.
- OLED `VCC` → NodeMCU **3V3**.
- OLED `SCK` (SCL) → NodeMCU **D1 / GPIO5**.
- OLED `SDA` → NodeMCU **D2 / GPIO4**.

Đã thấy I²C **0x3C**, hiển thị đủ chữ, bộ đếm, khung bốn cạnh và chấm chạy bằng driver SH1106 128×64. Driver hoạt động chưa đồng nghĩa đã xác minh độc lập mã silicon.

## 4. Cảm biến mưa HW-103 v0.12 — dùng DO trên D7

Dựa theo chữ in trên bo xanh, nối:

- Module mưa `VCC` → NodeMCU **3V3**.
- Module mưa `GND` → NodeMCU **GND**.
- Module mưa `DO` → NodeMCU **D7 / GPIO13**.
- Module mưa `AO` → **để rời**.
- NodeMCU `A0` → **để rời**.
- Hai chân của tấm dò → giắc hai chân dành cho tấm dò trên bo xanh, qua hai dây; không phân cực.

Người dùng đã chỉnh biến trở để **cùng một vị trí vít** cho kết quả: tấm dò khô → **HIGH**, nước nối qua vạch đồng → **LOW**. Giữ vị trí vít hiện tại. Góc vít cụ thể chưa được đo hoặc ghi ảnh nên nếu bị xoay, cần chỉnh lại theo hai trạng thái này.

COM9 đã ghi 21 mẫu LOW liên tiếp ở lượt ướt trước lần chỉnh cuối, và 21 mẫu HIGH liên tiếp ở lượt khô sau lần chỉnh cuối. Việc phân biệt khô/ướt tại ngưỡng cuối do người dùng xác nhận trên OLED. Chưa kiểm tra điện áp AO/A0, chưa hiệu chỉnh số đo analog hoặc lượng mưa.

## 5. Relay CW-025 và còi 5 V — giữ D6, jumper H

Relay dùng Songle `SRD-05VDC-SL-C`. Nhóm đầu vào ghi `DC+ DC− IN`; nhóm tiếp điểm ghi `NO COM NC`. Nhìn đúng chữ trên bo vì hai đầu có thể bị đảo trái–phải khi xoay.

Nguồn và điều khiển:

- NodeMCU **VIN** → relay **DC+**.
- NodeMCU **GND** → relay **DC−**.
- NodeMCU **D6 / GPIO12** → relay **IN**.
- Jumper chọn kích mức → **H**.
- **Không nối cầu IN với DC+.** Dây cầu đó chỉ từng dùng ở bước thử tay và đã được tháo trước khi nối D6.

Tiếp điểm cấp nguồn cho còi:

- Relay **DC+** → relay **COM** bằng một dây cầu.
- Relay **NO** → dây **đỏ (+)** của còi.
- Dây **đen (−)** của còi → relay **DC− / GND**.
- Relay **NC** → **để rời**.

Với jumper H: D6 HIGH ra lệnh bật relay/còi; D6 LOW ra lệnh tắt. Đã thử ba chu kỳ relay đóng/nhả và một lượt cấp còi khoảng 3 giây; người dùng xác nhận tiếng tách, LED1 đỏ và còi bật rồi ngừng. Chưa đo điện áp/dòng nguồn hoặc độ ổn định dài hạn.

## 6. Phần chưa nối trong mốc này

- Module áp suất GY-BM E/P280: **toàn bộ sáu chân để rời**, dù đã hàn header. Chưa xác định BMP280 hay BME280 bằng mã chip.
- Không có LED rời trên D7; **D7 đang dành cho DO của cảm biến mưa**.
- AO của module mưa, A0 của NodeMCU và NC của relay đều để rời.
- Các hướng dẫn thêm áp suất và bố trí breadboard là kế hoạch sau mốc này, chưa được coi là cách đấu đã chạy thử.

## 7. Chương trình dùng để khôi phục đúng trạng thái gần nhất

Chọn môi trường PlatformIO **`esp8266_rain_do_legacy_d6`** (tương đương cấu hình `esp8266_rain_do` ở thời điểm lưu mốc), nguồn `firmware/src/rain_do_check.cpp`, tốc độ UART **115200**. Chỉ nạp sau khi dây đã khớp mốc này và xác nhận cổng COM thực tế.

```powershell
$env:PYTHONPATH = (Resolve-Path firmware/.pio/tools).Path
$env:PLATFORMIO_CORE_DIR = (Resolve-Path firmware/.pio/core).Path
& firmware/.venv/Scripts/python.exe -m platformio run --project-dir firmware --environment esp8266_rain_do_legacy_d6 --target upload --upload-port COM9
```

Sau khi khởi động:

- OLED hiện `TV1 RAIN DO TEST`, mức D7, `Changes`, `AO: DISCONNECTED`, `Relay: OFF` và thời gian.
- D7 được đặt INPUT; mỗi lần mức thay đổi, `Changes` tăng. Bộ đếm về đầu sau reset.
- D6 được đặt LOW khi chương trình vào setup; không tự kích còi. Trạng thái trong giai đoạn trước setup không được chương trình bảo đảm.
- DHT11 vẫn nối dây nhưng chương trình này không đọc DHT11; không có WiFi/MQTT.

**Không nạp môi trường mặc định `esp8266` với cách đấu D7 hiện tại:** chương trình trạm chính đang dùng D7 làm đầu ra LED, còn mốc này dùng D7 làm đầu vào DO. Chương trình trạm chính cũng yêu cầu áp suất và mưa AO, hai phần chưa được nghiệm thu ở mốc này.

## 8. Trình tự đấu lại về mốc này

1. Rút USB. Đối chiếu tên chân trên từng module.
2. Nối 3V3/GND cho DHT11, OLED và module mưa.
3. Nối OLED D1/D2, DHT11 D5, mưa DO D7; để AO/A0 rời.
4. Nối nguồn/điều khiển relay, kiểm tra jumper H và mạch COM–NO–còi theo mục 5.
5. Kiểm tra đầu dây không chạm chân bên cạnh; giữ module áp suất rời.
6. Cắm USB. Nếu firmware còn là `esp8266_rain_do`, đối chiếu màn hình theo mục 7. Chỉ cần nạp lại khi firmware đã thay đổi.

## 9. Hồ sơ đối chiếu trong dự án

- DHT11: `personal/tv1/hardware_validation/20261027/DHT11_RESULT.md`.
- Relay: `personal/tv1/hardware_validation/20261027/RELAY_RESULT.md`.
- Còi: `personal/tv1/hardware_validation/20261027/BUZZER_RESULT.md`.
- OLED: `personal/tv1/hardware_validation/20261102/OLED_RESULT.md`.
- Mưa DO: `personal/tv1/hardware_validation/20261102/RAIN_DO_RESULT.md`.
- Bản chụp chương trình thử và mã SHA256: `personal/tv1/hardware_validation/checkpoints/MOC_01_20261103/`.

Các hồ sơ trong `personal/` được lưu cục bộ và có thể không xuất hiện khi clone repository trên máy khác. Tài liệu này đã ghi đủ cách đấu và giới hạn kết quả để xem lại độc lập.

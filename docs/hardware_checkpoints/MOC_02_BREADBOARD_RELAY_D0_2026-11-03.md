# Mốc 02 — Breadboard, relay dùng D0

Ngày lưu: **03/11/2026**, giờ Việt Nam. NodeMCU đã cắm trên breadboard, USB ở đầu hàng 1, anten gần hàng 15. Module áp suất đã hàn chân nhưng **chưa xác nhận nối vào mạch**. Mốc trước khi bố trí breadboard là [Mốc 01](MOC_01_DAU_DAY_DA_THU_2026-11-03.md).

## Nguồn trên breadboard

- NodeMCU **3V3/a1 → thanh + bên trái**: nguồn 3,3 V của OLED, DHT11 và module mưa.
- NodeMCU **GND/a2 → thanh − bên trái**: GND của các module trên.
- NodeMCU **VIN/j1 → thanh + bên phải**: nguồn relay và còi.
- NodeMCU **GND cạnh VIN/j2 → thanh − bên phải**: GND relay và còi.
- Hai chân GND trên NodeMCU đã chung mass, không bắt buộc thêm cầu giữa hai thanh âm.
- **Không nối hai thanh dương với nhau.** Chúng mang hai mức nguồn khác nhau.
- Các đầu cắm thanh nguồn sử dụng cùng đoạn phía trên; không mặc định thanh nguồn nối xuyên suốt chiều dài breadboard.

Tên hàng/lỗ áp dụng đúng vị trí NodeMCU đã chụp trong phiên này. Khi tháo và cắm board sang vị trí khác, phải đối chiếu lại **chữ trên NodeMCU**.

## Các module đã nối

**DHT11:** `+ → 3V3 bên trái`, `− → GND bên trái`, `OUT giữa → D5/a8`.

**OLED:** `VCC → 3V3 bên trái`, `GND → GND bên trái`, `SCK → D1/a14`, `SDA → D2/a13`. Địa chỉ đã dùng là 0x3C, driver SH1106 128×64.

**Mưa HW-103:** `VCC → 3V3 bên trái`, `GND → GND bên trái`, `DO → D7/a6`. Hai dây tấm dò nối giắc hai chân của module. **AO và A0 để rời.** Giữ ngưỡng đã chỉnh: khô HIGH, ướt LOW. Không nối LED rời vào D7 khi D7 đang nhận DO.

**Relay/còi:**

- `IN → D0/a15 (GPIO16)`, jumper **H**.
- `DC+ → thanh + bên phải`.
- `DC− → thanh − bên phải`.
- `COM → thanh + bên phải`.
- `NO → dây đỏ còi`.
- `Dây đen còi → thanh − bên phải`.
- `NC để rời`. D6 để trống. Không nối IN với bất kỳ thanh nguồn nào trong cấu hình điều khiển bằng D0.

## Bằng chứng đã có

- Sau khi chuyển lên breadboard, DHT11 từng cắm nhầm OUT vào D8 làm ROM báo `waiting for host`. Chuyển về D5 đã khôi phục chương trình.
- Với tấm dò khô, để yên: 33 mẫu mưa HIGH liên tiếp, bộ đếm không tăng; OLED driver sẵn sàng và chương trình giữ relay LOW.
- Thử D6 trên breadboard: không có phản ứng relay/còi theo người dùng dù UART ghi đúng xung và đọc lại mức HIGH. Kích tay IN từ VIN và từ 3V3 đều làm còi kêu. **Chưa xác định nguyên nhân ở D6; không kết luận chân hỏng.**
- Chuyển IN sang **D0**: xung HIGH **3000 ms**, rồi LOW; GPIO đọc lại đúng, STOP được xác nhận, RUN lặp bị từ chối. Người dùng xác nhận **còi kêu rồi ngừng, relay đóng/nhả và LED1 đỏ bật/tắt đúng**.
- Trong lượt D0: DHT11 **6/6 mẫu hợp lệ**, nhiệt độ 32,1–32,8°C, độ ẩm 65%; không thấy reset.

Đây là kiểm tra chức năng từng phần và sau bố trí lại, chưa đo điện áp/dòng, chưa hiệu chuẩn cảm biến, chưa nghiệm thu WiFi/MQTT hoặc trạm đầy đủ. Độ ổn định dài hạn và giai đoạn khởi động trước setup còn phải kiểm tra khi nghiệm thu cả trạm.

## Firmware phù hợp

- **`esp8266_buzzer_d0`**: bài thử đã chạy trên board, chờ RUN, tối đa một xung 3 giây mỗi lần khởi động; OLED không được khởi tạo nên có thể tối. Cuối lượt giữ D0 LOW.
- **`esp8266_rain_do`**: OLED/mưa DO, giữ relay D0 LOW theo `board_wiring.h`.
- **`esp8266_pressure`**: chương trình nhận dạng áp suất, giữ relay D0 LOW; chỉ nạp sau khi xác nhận dây module mới.
- Mẫu cấu hình trạm chính và cấu hình cá nhân đã chuyển relay sang D0. **Chưa nạp trạm chính với mốc này**: main vẫn dùng D7 làm LED, mưa AO/A0 và áp suất; các phần đó chưa khớp cấu hình DO hiện tại.
- `esp8266_relay`, `esp8266_buzzer_single` giữ D6 để tái hiện bài thử lịch sử. Không chọn chúng để kích còi đang nối D0.

Nếu cần nạp lại đúng bài thử còi:

```powershell
$env:PYTHONPATH = (Resolve-Path firmware/.pio/tools).Path
$env:PLATFORMIO_CORE_DIR = (Resolve-Path firmware/.pio/core).Path
& firmware/.venv/Scripts/python.exe -m platformio run --project-dir firmware --environment esp8266_buzzer_d0 --target upload --upload-port COM9
```

Lệnh nạp không tự chạy xung. Chỉ gửi RUN khi đã chuẩn bị quan sát. Tốc độ UART 115200, GPIO được báo phải là **16**. COM9 có thể đổi khi chuyển máy/cổng USB.

## Bước tiếp theo chưa thuộc mốc đã đạt

Rút USB trước khi thêm áp suất. Dự kiến chia D1 qua hàng 20 và D2 qua hàng 22 phía a–e: `a14→a20`, OLED SCK ở b20, áp suất SCL ở c20; `a13→a22`, OLED SDA ở b22, áp suất SDA ở c22. Áp suất VCC/CSB lấy 3V3 bên trái, GND/SDO lấy GND bên trái. Cần xác nhận đấu xong rồi mới nạp `esp8266_pressure` để đọc ID chip. Không cấp module áp suất từ thanh + VIN bên phải.

Hồ sơ cục bộ: `personal/tv1/hardware_validation/20261103/breadboard_buzzer_d0/buzzer_load_trial.json`, log cùng tên và `hardware_status.json`. Bản chụp mã nguồn và mã SHA256 của firmware đã chạy (không kèm binary): `personal/tv1/hardware_validation/checkpoints/MOC_02_20261103/`. Thư mục personal không được bảo đảm có trong bản clone repository.

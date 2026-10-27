# Danh sách phần cứng cho một trạm thời tiết

Cập nhật ngày 27/10/2026 theo những linh kiện người dùng đã xác nhận. Link Shopee bên dưới là **link tham khảo để chọn đúng chủng loại**, không phải đơn hàng đã được xác nhận về giá, tồn kho hay biến thể. Kiểm tra lại ảnh, thông số và lựa chọn phân loại trước khi thanh toán. Giá là khoảng dự trù, không gồm phí vận chuyển.

## Đã có — không mua lại

| Số lượng | Linh kiện | Vai trò và lưu ý |
| --- | --- | --- |
| 1 | ESP8266, chưa xác định chính xác biến thể board | Vi điều khiển Wi-Fi. Firmware hiện chọn môi trường `esp8266`, loại board trong PlatformIO là `nodemcuv2`; kiểm tra tên và chân thực tế trước khi cắm dây. |
| 1 | DHT11 | Dùng thử nhiệt độ và độ ẩm. Firmware chính vẫn đọc BME280; DHT11 không đo áp suất nên không đủ cho mô hình dự báo đầy đủ. |
| 1 | Buzzer 5V có dây | Còi cảnh báo. Thử nguồn 5V để xác định loại còi chủ động; nếu chỉ là loại thụ động thì cần sửa phần phát âm. |
| 1 | Module relay 1 kênh, cuộn hút 5V `SRD-05VDC-SL-C` | Đóng/cắt đường cấp 5V cho còi. Xác minh các chân VCC/GND/IN, COM/NO/NC và mức kích HIGH/LOW trên chính module; chữ 5V trên relay chỉ xác nhận điện áp cuộn hút, không chứng minh ngõ IN nhận mức 3,3V. |
| Nhiều | LED | Dùng một LED đỏ để cảnh báo, phần còn lại dự phòng. |

## Cần mua cho trạm hoạt động đúng mục tiêu dự án

| SL | Linh kiện và tiêu chí chọn | Giá dự trù | Link tham khảo |
| --- | --- | ---: | --- |
| 1 bộ | Cảm biến mưa có **tấm dò + module AO/DO + dây nối**, chạy được ở 3,3V. Code đọc **AO**, không dùng DO. | 15–35 nghìn ₫ | [Tìm cảm biến mưa trên Shopee](https://shopee.vn/search?keyword=c%E1%BA%A3m%20bi%E1%BA%BFn%20m%C6%B0a%20AO%20DO%203.3V) |
| 1 | Module **BME280** I2C đo nhiệt độ, độ ẩm, áp suất; ưu tiên đã hàn chân. Tránh chọn biến thể BMP280 trong cùng tin đăng. | 90–160 nghìn ₫ | [Ví dụ BME280 trên Shopee](https://shopee.vn/GY-BME280-3.3-BME280-5V-3.3V-C%E1%BA%A3m-bi%E1%BA%BFn-k%E1%BB%B9-thu%E1%BA%ADt-s%E1%BB%91-Nhi%E1%BB%87t-%C4%91%E1%BB%99-%C4%90%E1%BB%99-%E1%BA%A9m-M%C3%B4-%C4%91un-c%E1%BA%A3m-bi%E1%BA%BFn-%C3%A1p-su%E1%BA%A5t-kh%C3%AD-quy%E1%BB%83n-I2C-SPI-1.8-5V-i.148048328.42866181978) |
| 1 | OLED **SSD1306 0,96 inch, 128×64, I2C 4 chân**, hỗ trợ 3,3V; code dùng địa chỉ `0x3C`. | 50–80 nghìn ₫ | [Ví dụ OLED trên Shopee](https://shopee.vn/M%C3%A0n-h%C3%ACnh-OLED-0.96-inch-I2C-SSD1306-128x64-giao-ti%E1%BA%BFp-I2C-4-ch%C3%A2n-VCC-GND-SCL-SDA-d%C3%B9ng-cho-Arduino-ESP32-STM32-i.1723076079.51514172829) |
| 1–2 | Breadboard MB-102 830 lỗ. Một số board ESP8266 bản rộng cần hai breadboard đặt cạnh nhau. | 30–45 nghìn ₫/cái | [Tìm breadboard trên Shopee](https://shopee.vn/list/testboard) |
| 1–2 bộ | Dây Dupont 20 cm: đực–đực, đực–cái và cái–cái tùy đầu chân của cảm biến/relay. | 20–50 nghìn ₫/bộ | [Ví dụ dây Dupont trên Shopee](https://shopee.vn/D%C3%A2y-Dupont-10cm-20CM-30CM-40-Pin-Dupont-N%E1%BB%91i-%C4%90%E1%BA%A7u-%C4%90%E1%BB%B1c-C%C3%A1i-DIY-i.1038054123.19991090543) |
| 1 gói | Điện trở **220–330 Ω** cho LED; thêm **10 kΩ** nếu DHT11 là cảm biến trần chưa có điện trở kéo lên. | 5–15 nghìn ₫ | [Tìm gói điện trở trên Shopee](https://shopee.vn/search?keyword=%C4%91i%E1%BB%87n%20tr%E1%BB%9F%20220%20ohm%20330%20ohm%2010k) |
| 1 | Cáp USB **có truyền dữ liệu**, đúng cổng trên board ESP8266 đang có. | 20–50 nghìn ₫ | [Tìm cáp USB trên Shopee](https://shopee.vn/search?keyword=c%C3%A1p%20micro%20usb%20truy%E1%BB%81n%20d%E1%BB%AF%20li%E1%BB%87u) |
| 1 | Adapter USB 5V, tối thiểu 1A, dùng cho board và relay; tận dụng sạc sẵn có nếu phù hợp. | 30–80 nghìn ₫ | [Tìm nguồn 5V trên Shopee](https://shopee.vn/search?keyword=ngu%E1%BB%93n%20usb%205v%202a) |
| 1 | Dây nguồn/đầu chia **5V–GND có đầu siết vít** để cấp 5V riêng cho module relay và còi. Chỉ dùng chân 5V/VU trên ESP8266 nếu đã xác minh board có chân này và nguồn đủ dòng. | 15–35 nghìn ₫ | [Tìm đầu cấp 5V USB trên Shopee](https://shopee.vn/search?keyword=usb%205v%20%C4%91%E1%BA%A7u%20ra%20terminal%20v%C3%ADt) |

**Tối thiểu để thử mưa trên bàn:** cảm biến mưa, breadboard, dây, điện trở LED và cáp/nguồn nếu chưa có; DHT11 có thể dùng để thử đo nhiệt độ, độ ẩm qua một chương trình thử riêng. **Để chạy firmware chính và dữ liệu dự báo đầy đủ:** cần thêm BME280 và OLED như bảng trên. DHT11 trở thành cảm biến dự phòng, không phải thay thế BME280 trong bản hoàn chỉnh. Nếu phải mua mỗi món một đơn vị và chưa có phụ kiện nào, dự trù khoảng **275–550 nghìn ₫** cho bộ trong nhà; tùy chọn nhiều breadboard/dây làm tổng cao hơn.

## Chỉ mua khi lắp ngoài trời

| SL | Linh kiện | Giá dự trù | Link tham khảo |
| --- | --- | ---: | --- |
| 1 | Hộp nhựa ABS có gioăng, cỡ khoảng **150×100×70 mm** hoặc lớn hơn tùy board và relay; nên thử bố trí trước khi đặt mua. | 60–120 nghìn ₫ | [Tìm hộp chống nước trên Shopee](https://shopee.vn/list/h%E1%BB%99p%20ch%E1%BB%91ng%20n%C6%B0%E1%BB%9Bc) |
| 2–3 | Đầu siết cáp chống nước PG7/PG9 theo đường kính dây thực tế. | 10–30 nghìn ₫/bộ | [Tìm đầu siết cáp trên Shopee](https://shopee.vn/search?keyword=%C4%91%E1%BA%A7u%20si%E1%BA%BFt%20c%C3%A1p%20PG7) |
| 1 | Board hàn lỗ hoặc đế cố định, đầu nối vít, ốc/trụ đỡ; thay breadboard khi vận hành dài ngày. | 20–50 nghìn ₫ | [Tìm board hàn lỗ trên Shopee](https://shopee.vn/search?keyword=board%20h%C3%A0n%20l%E1%BB%97%20pcb) |
| 1 | Chụp che nắng/mưa **có thông khí** cho BME280; có thể tự làm. | 20–60 nghìn ₫ | [Tìm chụp che cảm biến trên Shopee](https://shopee.vn/search?keyword=ch%E1%BB%A5p%20che%20c%E1%BA%A3m%20bi%E1%BA%BFn%20nhi%E1%BB%87t%20%C4%91%E1%BB%99%20ngo%C3%A0i%20tr%E1%BB%9Di) |

Tấm dò mưa đặt nơi hứng mưa và thoát nước; module xử lý, ESP8266, relay và buzzer đặt trong vùng được bảo vệ. BME280 cần thông khí, không nhốt kín trong hộp điện. Bộ cảm biến mưa dạng tấm xác định có nước trên tấm, **không đo lượng mưa theo mm**.

Phần lắp ngoài trời dự trù thêm khoảng **110–260 nghìn ₫**, tùy hộp và cách cố định.

## Kiểm tra trước khi nối điện

1. Xác nhận chính xác biến thể ESP8266 và mức điện áp **A0** của board. ADC của chip ESP8266 là khoảng 0–1 V, nhưng một số board NodeMCU có chia áp trên board; không nối AO 3,3V/5V vào A0 khi chưa kiểm tra.
2. Cấp cảm biến mưa ở **3,3V** nếu module hỗ trợ; nếu chỉ hoạt động 5V, cần chia áp/đổi mức cho AO hoặc chọn module 3,3V. Đọc giá trị khô và ướt rồi chỉnh `RAIN_ANALOG_THRESHOLD` trong `firmware/include/config.h`. Nếu module cho giá trị ướt *cao hơn* giá trị khô, cần đảo điều kiện so sánh trong firmware.
3. Kiểm tra relay nhận được mức điều khiển **3,3V** từ D6. Chọn HIGH/LOW trên jumper và cập nhật `RELAY_ACTIVE_LEVEL`. Nguồn 5V đi qua tiếp điểm **COM–NO** tới còi, không đi qua GPIO; nối GND chung phần điều khiển khi module yêu cầu.
4. Buzzer chủ động 5V sẽ kêu khi cấp 5V trực tiếp. Firmware bật relay **một lần trong 3 giây**, LED tiếp tục nháy trong 10 giây. Nếu còi thụ động cần phần phát xung riêng.
5. BME280 nối 3,3V, GND, SDA→D2, SCL→D1; OLED chia sẻ bus I2C. LED nối D7 qua điện trở; relay IN nối D6. Kiểm tra `config.h` trước khi nạp.

MQTT broker, cơ sở dữ liệu, backend, AI và dashboard có thể chạy trên máy tính hiện có; không cần mua máy chủ để thử dự án. Chưa thể xác nhận giá cuối cùng hay tồn kho Shopee tại thời điểm thanh toán.

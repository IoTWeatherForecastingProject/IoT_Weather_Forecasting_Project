# Danh sách phần cứng cho một trạm thời tiết

Cập nhật ngày 27/10/2026 theo những linh kiện người dùng đã xác nhận. Link Shopee bên dưới là **link tham khảo để chọn đúng chủng loại**, không phải đơn hàng đã được xác nhận về giá, tồn kho hay biến thể. Kiểm tra lại ảnh, thông số và lựa chọn phân loại trước khi thanh toán. Giá là khoảng dự trù, không gồm phí vận chuyển.

## Đã có — không mua lại

| Số lượng | Linh kiện | Vai trò và lưu ý |
| --- | --- | --- |
| 1 | ESP8266 NodeMCU Amica | Vi điều khiển Wi-Fi đã chạy lab. Firmware chọn `esp8266`/`nodemcuv2`. |
| 1 | DHT11 | Đo độ ẩm trong firmware chính; BMP280 đo nhiệt độ và áp suất. |
| 1 | Buzzer 5V có dây | Còi cảnh báo. Thử nguồn 5V để xác định loại còi chủ động; nếu chỉ là loại thụ động thì cần sửa phần phát âm. |
| 1 | Module relay 1 kênh, cuộn hút 5V `SRD-05VDC-SL-C` | Đóng/cắt đường cấp 5V cho còi. Xác minh các chân VCC/GND/IN, COM/NO/NC và mức kích HIGH/LOW trên chính module; chữ 5V trên relay chỉ xác nhận điện áp cuộn hút, không chứng minh ngõ IN nhận mức 3,3V. |
| Nhiều | LED | Dùng một LED đỏ để cảnh báo, phần còn lại dự phòng. |
| 1 | Breadboard cỡ MB-102 830 lỗ | Tận dụng để thử trên bàn; kiểm tra lỗ cắm, tính liên tục thanh nguồn. Chỉ bổ sung breadboard nếu thiếu chỗ. |
| Nhiều | Điện trở than và điện trở màng kim loại | Đo/tách 220–330 Ω cho LED; khoảng 10 kΩ cho DHT11 trần. Chưa xác nhận từng giá trị bằng ảnh. |
| Nhiều | Diode 1N4007 | Dự phòng; cấu hình relay module hiện tại không yêu cầu gắn thêm diode rời. |
| 1 | LCD ký tự 16×2 có module I2C | Dự phòng. Firmware chính dùng SH1106; dùng LCD cần driver khác và kiểm tra điện áp pull-up SDA/SCL, có thể cần chuyển mức 3,3V↔5V. |
| 1 | Adapter 12V–1A | Chỉ tận dụng qua bộ hạ áp xuống 5V; không cắm trực tiếp vào NodeMCU/còi/relay 5V. |

## Cần mua cho trạm hoạt động đúng mục tiêu dự án

| SL | Linh kiện và tiêu chí chọn | Giá dự trù | Link tham khảo |
| --- | --- | ---: | --- |
| 1 bộ | Cảm biến mưa có **tấm dò + module AO/DO + dây nối**, chạy được ở 3,3V. Code đọc **AO**, không dùng DO. | 15–35 nghìn ₫ | [Tìm cảm biến mưa trên Shopee](https://shopee.vn/search?keyword=c%E1%BA%A3m%20bi%E1%BA%BFn%20m%C6%B0a%20AO%20DO%203.3V) |
| 1 | Module **BMP280** I2C 3,3V đo nhiệt độ và áp suất, ưu tiên đã hàn chân; kiểm tra đúng chip BMP280. | 19–50 nghìn ₫ | [Tìm BMP280 3,3V trên Shopee](https://shopee.vn/search?keyword=GY-BMP280%203.3V) |
| 1 | OLED **SH1106 1,3 inch, 128×64, I2C 4 chân**, hỗ trợ 3,3V; chân GND/VCC/SCL/SDA; firmware dùng địa chỉ `0x3C`. Chọn đúng biến thể SH1106. | Khoảng 75 nghìn ₫ theo ảnh người dùng gửi | [Tìm OLED SH1106 1,3 inch trên Shopee](https://shopee.vn/search?keyword=OLED%201.3%20inch%20SH1106%20I2C%20128x64) |
| 2 bó | Dây Dupont 20 cm: **1 bó đực–đực + 1 bó đực–cái**, tận dụng dây đang có trước. Đầu cái nối chân đực module, đầu đực nối breadboard/ổ cái. Cái–cái chỉ cần khi nối trực tiếp hai hàng chân đực. | 20–50 nghìn ₫/bộ | [Ví dụ dây Dupont trên Shopee](https://shopee.vn/D%C3%A2y-Dupont-10cm-20CM-30CM-40-Pin-Dupont-N%E1%BB%91i-%C4%90%E1%BA%A7u-%C4%90%E1%BB%B1c-C%C3%A1i-DIY-i.1038054123.19991090543) |
| Chỉ khi thiếu | Điện trở **220–330 Ω** cho LED, **10 kΩ** cho DHT11 trần; kiểm tra gói sẵn có trước. Chia áp A0 chọn sau khi xác minh board và AO. | 5–15 nghìn ₫ | [Tìm gói điện trở trên Shopee](https://shopee.vn/search?keyword=%C4%91i%E1%BB%87n%20tr%E1%BB%9F%20220%20ohm%20330%20ohm%2010k) |
| 1 | Cáp USB **có truyền dữ liệu**, đúng cổng trên board ESP8266 đang có. | 20–50 nghìn ₫ | [Tìm cáp USB trên Shopee](https://shopee.vn/search?keyword=c%C3%A1p%20micro%20usb%20truy%E1%BB%81n%20d%E1%BB%AF%20li%E1%BB%87u) |
| 1 | Adapter USB 5V, tối thiểu 1A, dùng cho board và relay; tận dụng sạc sẵn có nếu phù hợp. | 30–80 nghìn ₫ | [Tìm nguồn 5V trên Shopee](https://shopee.vn/search?keyword=ngu%E1%BB%93n%20usb%205v%202a) |
| Tùy chọn | Dây/đầu chia 5V–GND nếu không tiện lấy đường 5V USB từ chân VIN/VU của NodeMCU. | 15–35 nghìn ₫ | [Tìm đầu cấp 5V USB trên Shopee](https://shopee.vn/search?keyword=usb%205v%20%C4%91%E1%BA%A7u%20ra%20terminal%20v%C3%ADt) |

**Để chạy firmware chính:** cần BMP280, cảm biến mưa và OLED; DHT11, relay, còi và ESP8266 đang có được sử dụng lại. Nếu đã có cáp USB/nguồn 5V và phụ kiện lắp ráp, không cần mua lại. Nguồn USB 5V cần đủ dòng cho cả NodeMCU, relay, còi và phần còn lại; ưu tiên nguồn 5V 2A có chất lượng. Chỉ lấy 5V từ chân VIN/VU nếu đã xác minh chân đó nối với đường 5V USB trên đúng board và đường cấp chịu được dòng tải. Adapter 12V–1A hiện có chỉ dùng qua bộ hạ áp DC-DC xuống 5V.

## Chỉ mua khi lắp ngoài trời

| SL | Linh kiện | Giá dự trù | Link tham khảo |
| --- | --- | ---: | --- |
| 1 | Hộp nhựa ABS có gioăng, cỡ khoảng **150×100×70 mm** hoặc lớn hơn tùy board và relay; nên thử bố trí trước khi đặt mua. | 60–120 nghìn ₫ | [Tìm hộp chống nước trên Shopee](https://shopee.vn/list/h%E1%BB%99p%20ch%E1%BB%91ng%20n%C6%B0%E1%BB%9Bc) |
| 2–3 | Đầu siết cáp chống nước PG7/PG9 theo đường kính dây thực tế. | 10–30 nghìn ₫/bộ | [Tìm đầu siết cáp trên Shopee](https://shopee.vn/search?keyword=%C4%91%E1%BA%A7u%20si%E1%BA%BFt%20c%C3%A1p%20PG7) |
| 1 | Board hàn lỗ hoặc đế cố định, đầu nối vít, ốc/trụ đỡ; thay breadboard khi vận hành dài ngày. | 20–50 nghìn ₫ | [Tìm board hàn lỗ trên Shopee](https://shopee.vn/search?keyword=board%20h%C3%A0n%20l%E1%BB%97%20pcb) |
| 1 | Chụp che nắng/mưa **có thông khí** cho BMP280 và DHT11; có thể tự làm. | 20–60 nghìn ₫ | [Tìm chụp che cảm biến trên Shopee](https://shopee.vn/search?keyword=ch%E1%BB%A5p%20che%20c%E1%BA%A3m%20bi%E1%BA%BFn%20nhi%E1%BB%87t%20%C4%91%E1%BB%99%20ngo%C3%A0i%20tr%E1%BB%9Di) |

Tấm dò mưa đặt nơi hứng mưa và thoát nước; module xử lý, ESP8266, relay và buzzer đặt trong vùng được bảo vệ. BMP280 và DHT11 cần thông khí, không nhốt kín trong hộp điện. Bộ cảm biến mưa dạng tấm xác định có nước trên tấm, **không đo lượng mưa theo mm**.

Phần lắp ngoài trời dự trù thêm khoảng **110–260 nghìn ₫**, tùy hộp và cách cố định.

## Kiểm tra trước khi nối điện

1. Xác nhận chính xác biến thể ESP8266 và mức điện áp **A0** của board. ADC của chip ESP8266 là khoảng 0–1 V, nhưng một số board NodeMCU có chia áp trên board; không nối AO 3,3V/5V vào A0 khi chưa kiểm tra.
2. Cấp cảm biến mưa ở **3,3V** nếu module hỗ trợ; nếu chỉ hoạt động 5V, cần chia áp/đổi mức cho AO hoặc chọn module 3,3V. Đọc giá trị khô và ướt rồi chỉnh `RAIN_ANALOG_THRESHOLD` trong `firmware/include/weather_config.h`. Nếu module cho giá trị ướt *cao hơn* giá trị khô, cần đảo điều kiện so sánh trong firmware.
3. Kiểm tra relay nhận được mức điều khiển **3,3V** từ D6. Chọn HIGH/LOW trên jumper và cập nhật `RELAY_ACTIVE_LEVEL`. Nguồn 5V đi qua tiếp điểm **COM–NO** tới còi, không đi qua GPIO; nối GND chung phần điều khiển khi module yêu cầu.
4. Buzzer chủ động 5V sẽ kêu khi cấp 5V trực tiếp. Firmware bật relay **một lần trong 3 giây**, LED tiếp tục nháy trong 10 giây. Nếu còi thụ động cần phần phát xung riêng.
5. BMP280 nối 3,3V, GND, SDA→D2, SCL→D1; OLED SH1106 3,3V nối GND→GND, VCC→3V3, SCL→D1, SDA→D2 và chia sẻ bus I2C. DHT11 3,3V nối DATA→D5, thêm kéo lên 10 kΩ nếu là cảm biến trần. LED nối D7 qua điện trở; relay IN nối D6. Kiểm tra `weather_config.h` trước khi nạp.
6. Cấp NodeMCU qua micro-USB 5V. Nếu lấy 5V USB từ chân VIN/VU để cấp relay VCC và còi, xác nhận đường chân thực tế và thử điện áp khi cả relay/còi hoạt động. 5V→COM relay, NO→cực dương còi, cực âm còi→GND; nối GND relay với GND NodeMCU. Không cấp relay/còi từ chân 3V3 và không đưa 12V trực tiếp vào board.

MQTT broker, cơ sở dữ liệu, backend, AI và dashboard có thể chạy trên máy tính hiện có; không cần mua máy chủ để thử dự án. Chưa thể xác nhận giá cuối cùng hay tồn kho Shopee tại thời điểm thanh toán.

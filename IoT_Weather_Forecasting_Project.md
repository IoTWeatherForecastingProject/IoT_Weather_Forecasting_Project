# IoT Local Weather Monitoring & Short-Term Forecasting

## 1. Thông tin dự án

| Hạng mục | Nội dung |
|---|---|
| **Tên đề tài** | Xây dựng hệ thống IoT giám sát và dự báo thời tiết cục bộ ngắn hạn bằng Time Series Forecasting |
| **Tên tiếng Anh** | IoT-Based Local Weather Monitoring and Short-Term Forecasting System |
| **Lĩnh vực** | Internet of Things (IoT), Time Series Forecasting, Machine Learning |
| **Đối tượng** | Dữ liệu thời tiết cục bộ theo thời gian |
| **Quy mô nhóm** | 3 thành viên |
| **Mục tiêu chính** | Thu thập dữ liệu thời tiết bằng thiết bị IoT và dự báo nhiệt độ, khả năng mưa trong ngắn hạn |
| **Đầu ra chính** | Thiết bị IoT, hệ thống lưu trữ dữ liệu, mô hình dự báo và dashboard |

---

## 2. Tổng quan dự án

Dự án xây dựng một hệ thống IoT có khả năng **thu thập, truyền, lưu trữ, phân tích và dự báo dữ liệu thời tiết cục bộ theo thời gian thực**.

Thiết bị ESP32 kết nối với các cảm biến thời tiết để thu thập các thông số như:

- Nhiệt độ
- Độ ẩm
- Áp suất khí quyển
- Trạng thái/khả năng có mưa

Dữ liệu được truyền qua WiFi bằng giao thức MQTT đến hệ thống backend và được lưu trữ dưới dạng dữ liệu chuỗi thời gian.

Từ dữ liệu lịch sử, hệ thống xây dựng các mô hình Time Series Forecasting để:

1. Dự báo nhiệt độ trong các khoảng thời gian tiếp theo.
2. Ước lượng xác suất xảy ra mưa trong các khoảng thời gian tiếp theo.

Kết quả được hiển thị trên dashboard cùng với dữ liệu thời tiết hiện tại và lịch sử. Khi xác suất mưa vượt một ngưỡng định trước, hệ thống có thể gửi cảnh báo và kích hoạt thiết bị cảnh báo trên ESP32.

---

# 3. Vấn đề cần giải quyết

Các trạm thời tiết chuyên nghiệp thường có hệ thống cảm biến và mô hình dự báo phức tạp. Trong phạm vi đồ án, mục tiêu không phải xây dựng một hệ thống dự báo khí tượng quy mô lớn mà tập trung vào:

> **Giám sát và dự báo thời tiết cục bộ trong khoảng thời gian ngắn dựa trên dữ liệu cảm biến và dữ liệu lịch sử.**

Hệ thống cần giải quyết các vấn đề:

- Làm thế nào để thu thập dữ liệu thời tiết tự động?
- Làm thế nào để truyền dữ liệu cảm biến theo thời gian thực?
- Làm thế nào để lưu trữ dữ liệu theo timeline?
- Làm thế nào để biến dữ liệu cảm biến thành dữ liệu phù hợp cho Machine Learning?
- Làm thế nào để dự báo nhiệt độ trong tương lai?
- Làm thế nào để ước lượng khả năng mưa?
- Làm thế nào để đánh giá độ chính xác của mô hình?
- Làm thế nào để đưa kết quả dự báo trở lại ứng dụng IoT?

---

# 4. Mục tiêu dự án

## 4.1. Mục tiêu tổng quát

Xây dựng một hệ thống IoT hoàn chỉnh có khả năng thu thập dữ liệu thời tiết tại một khu vực, lưu trữ dữ liệu theo thời gian và sử dụng các mô hình Time Series Forecasting để dự báo thời tiết cục bộ trong ngắn hạn.

## 4.2. Mục tiêu cụ thể

### IoT

- Sử dụng ESP8266 làm thiết bị thu thập dữ liệu.
- Kết nối các cảm biến thời tiết với ESP8266.
- Thu thập dữ liệu theo chu kỳ định trước.
- Kết nối WiFi.
- Truyền dữ liệu bằng MQTT.

### Backend và dữ liệu

- Tiếp nhận dữ liệu từ MQTT.
- Lưu trữ dữ liệu thời tiết.
- Quản lý timestamp và dữ liệu chuỗi thời gian.
- Cung cấp API cho dashboard và mô hình dự báo.

### Machine Learning

- Tiền xử lý dữ liệu.
- Phân tích xu hướng thời tiết.
- Xây dựng mô hình dự báo nhiệt độ.
- Xây dựng mô hình dự báo/ước lượng xác suất mưa.
- So sánh mô hình với baseline.
- Đánh giá hiệu năng dự báo.

### Dashboard

- Hiển thị dữ liệu thời tiết hiện tại.
- Hiển thị dữ liệu lịch sử.
- Hiển thị biểu đồ.
- Hiển thị nhiệt độ dự báo.
- Hiển thị xác suất mưa dự báo.
- Hiển thị cảnh báo.

---

# 5. Phạm vi dự án

## 5.1. Trong phạm vi

Hệ thống tập trung vào **short-term local forecasting**.

Các mốc dự báo đề xuất:

- +10 phút
- +30 phút
- +60 phút

Các thông số chính:

- Temperature
- Humidity
- Atmospheric pressure
- Rain indicator / rain-related measurement

Hệ thống cung cấp:

- Realtime monitoring
- Historical data
- Temperature forecasting
- Rain probability forecasting
- Alerting

## 5.2. Ngoài phạm vi

Không đặt mục tiêu:

- Dự báo thời tiết toàn thành phố/quốc gia.
- Dự báo thời tiết nhiều ngày với độ chính xác như dịch vụ khí tượng chuyên nghiệp.
- Mô phỏng vật lý khí quyển.
- Thu thập tất cả các thông số khí tượng.
- Xây dựng mô hình khí tượng quy mô lớn.

Điều này giúp phạm vi phù hợp với một nhóm 3 người.

---

# 6. Kiến trúc hệ thống

```text
┌───────────────────────────────────────────────────────────┐
│                    LOCAL WEATHER STATION                  │
│                                                           │
│   ┌──────────┐   ┌──────────┐   ┌────────────┐           │
│   │ BME280   │   │ Rain     │   │ Optional   │           │
│   │ Temp     │   │ Sensor   │   │ Sensors    │           │
│   │ Humidity │   │          │   │            │           │
│   │ Pressure │   │          │   │            │           │
│   └────┬─────┘   └────┬─────┘   └─────┬──────┘           │
│        └───────────────┴───────────────┘                  │
│                        │                                  │
│                   ┌────▼────┐                             │
│                   │  ESP8266│                             │
│                   └────┬────┘                             │
└────────────────────────┼──────────────────────────────────┘
                         │ WiFi
                         │ MQTT
                         ▼
                ┌─────────────────┐
                │   MQTT Broker   │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │    Backend      │
                │  Data Ingestion │
                │      API        │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │    Database     │
                │  Time-series    │
                │      Data       │
                └────────┬────────┘
                         │
              ┌──────────┴───────────┐
              │                      │
              ▼                      ▼
      ┌───────────────┐      ┌────────────────┐
      │ ML Forecasting│      │    Dashboard   │
      │               │      │                │
      │ Temperature   │      │ Realtime       │
      │ Rain Prob.    │      │ Historical     │
      └───────┬───────┘      │ Forecast       │
              │              │ Alert          │
              └──────┬───────┘
                     ▼
             ┌─────────────────┐
             │ Forecast Result │
             └────────┬────────┘
                      │
                      │ MQTT / API
                      ▼
                ┌─────────────┐
                │    ESP32    │
                │ LED/Buzzer  │
                │ OLED        │
                └─────────────┘
```

---

# 7. Hardware

## 7.1. ESP8266

ESP8266 là bộ điều khiển trung tâm của thiết bị IoT.

Nhiệm vụ:

- Đọc dữ liệu cảm biến.
- Tiền xử lý đơn giản.
- Kết nối WiFi.
- Gửi dữ liệu qua MQTT.
- Nhận lệnh cảnh báo.
- Điều khiển LED, buzzer hoặc OLED.

## 7.2. BME280

BME280 được sử dụng để đo:

- Temperature
- Humidity
- Atmospheric pressure

Giao tiếp có thể sử dụng I2C.

## 7.3. Rain Sensor

Rain sensor cung cấp tín hiệu liên quan đến trạng thái có nước/mưa tại vị trí cảm biến.

Cần lưu ý rằng rain sensor giá rẻ chủ yếu phù hợp cho **phát hiện mưa tại điểm đo**, không phải đo lượng mưa khí tượng chính xác.

## 7.4. Thiết bị đầu ra

Có thể sử dụng:

- LED
- Buzzer
- OLED display

Mục đích là tạo phản hồi trực quan khi hệ thống dự báo khả năng mưa cao.

---

# 8. Luồng dữ liệu IoT

```text
Sensor
   ↓
ESP8266 reads data
   ↓
Validate sensor values
   ↓
Create JSON payload
   ↓
Publish MQTT
   ↓
MQTT Broker
   ↓
Backend
   ↓
Database
```

Ví dụ payload:

```json
{
  "device_id": "weather-station-01",
  "timestamp": "2026-09-09T10:30:00+07:00",
  "temperature": 31.4,
  "humidity": 78.2,
  "pressure": 1005.8,
  "rain": 0
}
```

---

# 9. MQTT Design

## 9.1. Topic

Có thể tổ chức topic:

```text
weather/station01/data
weather/station01/status
weather/station01/alert
```

## 9.2. Publish

ESP32 publish:

```text
weather/station01/data
```

## 9.3. Subscribe

ESP32 subscribe:

```text
weather/station01/alert
```

Backend có thể publish cảnh báo:

```text
weather/station01/alert
```

Ví dụ:

```json
{
  "type": "rain_warning",
  "probability": 0.84,
  "forecast_minutes": 30
}
```

---

# 10. Database Design

Dữ liệu thời tiết cần được lưu cùng timestamp.

Ví dụ bảng:

```text
weather_measurements
--------------------
id
device_id
timestamp
temperature
humidity
pressure
rain
created_at
```

Ví dụ:

| timestamp | temperature | humidity | pressure | rain |
|---|---:|---:|---:|---:|
| 10:00 | 31.2 | 72 | 1008 | 0 |
| 10:05 | 31.4 | 74 | 1007 | 0 |
| 10:10 | 31.1 | 77 | 1006 | 1 |
| 10:15 | 30.7 | 80 | 1005 | 1 |

Dữ liệu này tạo thành **multivariate time series** vì có nhiều biến thay đổi theo thời gian.

---

# 11. Time Series Forecasting

## 11.1. Khái niệm

Time Series Forecasting là quá trình sử dụng dữ liệu trong quá khứ để dự đoán giá trị trong tương lai.

Ví dụ:

```text
t-30   t-20   t-10    t       t+10   t+20   t+30
31.8   31.5   31.4   31.2      ?      ?      ?
```

Model học từ dữ liệu trước thời điểm `t` để dự báo các giá trị sau `t`.

---

# 12. Dự báo nhiệt độ

Bài toán:

> Dự báo nhiệt độ tại các thời điểm +10, +30 và +60 phút.

Ví dụ:

```text
Current temperature = 31.2°C

Forecast:
+10 min → 31.0°C
+30 min → 30.4°C
+60 min → 29.6°C
```

## Input features

Có thể sử dụng:

- Temperature hiện tại
- Humidity hiện tại
- Pressure hiện tại
- Temperature lag
- Humidity lag
- Pressure lag
- Rolling mean
- Rolling standard deviation
- Time of day
- Day of week

Ví dụ:

```text
temperature(t-1)
temperature(t-2)
temperature(t-3)

humidity(t-1)
humidity(t-2)
humidity(t-3)

pressure(t-1)
pressure(t-2)
pressure(t-3)
```

---

# 13. Dự báo khả năng mưa

Đây là bài toán khác với dự báo nhiệt độ.

Thay vì chỉ trả về:

```text
Rain = Yes / No
```

hệ thống nên hướng tới:

```text
Rain probability = 0.82
```

tương đương:

```text
82% probability of rain
```

Sau đó có thể phân loại:

```text
0–30%   → Low
30–70%  → Medium
70–100% → High
```

## Input

Có thể sử dụng:

- Temperature
- Humidity
- Pressure
- Rain sensor
- Historical rain state
- Humidity trend
- Pressure trend
- Temperature trend
- Time-related features

## Output

```text
P(rain in next 30 minutes)
```

Ví dụ:

```text
Current:
Humidity = 82%
Pressure = 1004 hPa

Prediction:
Rain probability in 30 min = 84%
```

---

# 14. Feature Engineering

Feature engineering là bước quan trọng để biến dữ liệu cảm biến thành các đặc trưng có ích cho mô hình.

## 14.1. Lag features

Ví dụ:

```text
temperature_lag_1
temperature_lag_2
temperature_lag_3
```

## 14.2. Difference

```text
temperature_diff_10m
pressure_diff_10m
humidity_diff_10m
```

Giúp model biết thông số đang:

- tăng
- giảm
- ổn định

## 14.3. Rolling statistics

Ví dụ:

```text
temperature_mean_30m
temperature_std_30m
humidity_mean_30m
pressure_mean_30m
```

## 14.4. Time features

```text
hour
minute
day_of_week
```

Thời tiết có tính chu kỳ theo thời gian trong ngày nên các feature này có thể hữu ích.

---

# 15. Mô hình Machine Learning

Không nên bắt đầu bằng một mô hình quá phức tạp.

## 15.1. Baseline

Đối với nhiệt độ:

```text
Prediction(t+1) = Temperature(t)
```

Đây là baseline để so sánh.

## 15.2. Mô hình chính

Có thể thử:

- Linear Regression
- Random Forest
- XGBoost

Random Forest/XGBoost phù hợp để xây dựng phiên bản chính vì dễ triển khai và giải thích hơn LSTM.

## 15.3. Mô hình mở rộng

Nếu thời gian cho phép:

- LSTM
- GRU

Mục đích là so sánh mô hình Deep Learning với các mô hình Machine Learning truyền thống.

---

# 16. Chia dữ liệu Train/Test

Không được random shuffle dữ liệu time series một cách tùy tiện vì có thể gây **data leakage**.

Nên chia theo thời gian:

```text
Past
│
├─────────────── Train ───────────────┤
│
├──────── Validation ────────┤
│
├──── Test ────┤
Future
```

Ví dụ:

```text
70% → Train
15% → Validation
15% → Test
```

hoặc sử dụng **walk-forward validation** nếu có đủ thời gian.

---

# 17. Đánh giá mô hình

## 17.1. Temperature Forecasting

Các metric:

### MAE

```text
MAE = Mean Absolute Error
```

Đơn vị có thể là °C.

Ví dụ:

```text
MAE = 0.65°C
```

có nghĩa sai số tuyệt đối trung bình khoảng 0.65°C.

### RMSE

Dùng để phạt mạnh hơn các sai số lớn.

### R²

Đánh giá mức độ giải thích biến thiên của dữ liệu.

## 17.2. Rain Probability

Có thể sử dụng:

- Accuracy
- Precision
- Recall
- F1-score
- ROC-AUC

Ngoài ra, vì hệ thống trả về xác suất nên nên cân nhắc đánh giá **calibration** của probability.

---

# 18. Dashboard

Dashboard có thể gồm các khu vực:

```text
┌──────────────────────────────────────────────┐
│             LOCAL WEATHER                    │
├──────────────────────────────────────────────┤
│                                              │
│ Temperature    Humidity      Pressure        │
│ 31.2 °C        78 %          1005 hPa        │
│                                              │
├──────────────────────────────────────────────┤
│ Temperature History                          │
│                                              │
│      ────────╮                               │
│  ───╯        ╰──────                         │
│                                              │
├──────────────────────────────────────────────┤
│ Short-Term Forecast                          │
│                                              │
│ Time       Temperature     Rain Probability  │
│ +10 min      31.0°C             30%          │
│ +30 min      30.4°C             62%          │
│ +60 min      29.6°C             84%          │
│                                              │
├──────────────────────────────────────────────┤
│ Status: ⚠ HIGH RAIN PROBABILITY              │
└──────────────────────────────────────────────┘
```

---

# 19. Alert System

Một rule đơn giản:

```text
IF rain_probability >= 70%
THEN
    send rain warning
```

Luồng:

```text
ML Model
   ↓
Rain Probability = 84%
   ↓
Threshold = 70%
   ↓
WARNING
   ↓
MQTT
   ↓
ESP32
   ↓
LED + Buzzer + OLED
```

Có thể cấu hình threshold thay vì hard-code.

---

# 20. Backend

Backend chịu trách nhiệm:

- Nhận dữ liệu từ MQTT.
- Validate dữ liệu.
- Lưu dữ liệu.
- Cung cấp REST API.
- Cung cấp dữ liệu cho dashboard.
- Gọi model dự báo.
- Trả về forecast.
- Quản lý cảnh báo.

API dự kiến:

```text
GET /api/weather/current
GET /api/weather/history
GET /api/weather/forecast
GET /api/weather/status
```

---

# 21. Công nghệ đề xuất

## Hardware

- ESP32
- BME280
- Rain Sensor
- OLED
- LED
- Buzzer

## Communication

- WiFi
- MQTT

## Backend

- Python
- FastAPI

## Data

- PostgreSQL

## Machine Learning

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost (optional)
- PyTorch/TensorFlow (optional nếu làm LSTM)

## Frontend

- HTML/CSS/JavaScript hoặc framework web phù hợp với năng lực nhóm

---

---

# 22. Kế hoạch triển khai

## Phase 1 — Research

- Tìm hiểu IoT.
- Tìm hiểu ESP32.
- Tìm hiểu sensor.
- Tìm hiểu MQTT.
- Tìm hiểu Time Series Forecasting.

## Phase 2 — Hardware Prototype

- Kết nối ESP32.
- Đọc sensor.
- Kiểm tra dữ liệu.
- Kết nối WiFi.
- Publish MQTT.

## Phase 3 — Data Pipeline

```text
ESP32
→ MQTT
→ Backend
→ Database
```

Hoàn thành pipeline trước khi làm Machine Learning.

## Phase 4 — Data Collection

- Thu thập dữ liệu liên tục.
- Kiểm tra missing values.
- Phát hiện outliers.
- Đồng bộ timestamp.
- Chuẩn hóa sampling interval.

## Phase 5 — ML

- Xây dựng baseline.
- Feature engineering.
- Train model nhiệt độ.
- Train model mưa.
- Đánh giá.
- So sánh model.

## Phase 6 — Dashboard

- Realtime data.
- Historical chart.
- Forecast chart.
- Rain probability.
- Alert.

## Phase 7 — Integration

```text
ESP32
→ MQTT
→ Backend
→ Database
→ ML
→ Forecast
→ Dashboard
→ MQTT
→ ESP32 Alert
```

## Phase 8 — Testing

Kiểm thử:

- Sensor failure.
- WiFi disconnect.
- MQTT disconnect.
- Missing data.
- Invalid sensor values.
- Model response.
- Alert threshold.
- Dashboard realtime update.

---

# 23. Kịch bản demo

## Scenario 1 — Monitoring

ESP8266 gửi:

```text
Temperature = 31.4°C
Humidity = 76%
Pressure = 1006 hPa
Rain = 0
```

Dashboard cập nhật realtime.

## Scenario 2 — Forecast

Hệ thống lấy dữ liệu lịch sử và trả về:

```text
+10 min → 31.0°C / 25%
+30 min → 30.3°C / 63%
+60 min → 29.5°C / 84%
```

## Scenario 3 — Rain alert

Khi:

```text
Rain probability = 84%
Threshold = 70%
```

hệ thống:

```text
Backend
   ↓
MQTT
   ↓
ESP32
   ↓
Buzzer ON
LED ON
OLED: "RAIN WARNING"
```

---

# 24. Các rủi ro kỹ thuật

## 24.1. Thiếu dữ liệu

Nếu chỉ thu thập dữ liệu trong vài ngày, dataset có thể chưa đủ đại diện.

### Giải pháp

- Sử dụng historical weather dataset để huấn luyện ban đầu.
- Đồng thời thu thập dữ liệu thực tế bằng ESP32.
- Sau đó đánh giá model trên dữ liệu thực tế.

## 24.2. Sensor giá rẻ

Rain sensor có thể bị ảnh hưởng bởi:

- nước đọng
- bụi
- độ ẩm
- vị trí đặt sensor

Do đó không nên coi nó là thiết bị đo lượng mưa chính xác.

## 24.3. Data leakage

Không random dữ liệu time series một cách tùy tiện.

## 24.4. Model overfitting

Model có thể hoạt động tốt trên dataset nhưng kém trên dữ liệu thực tế.

Cần đánh giá bằng dữ liệu ở khoảng thời gian chưa từng xuất hiện trong training.

---

# 25. Tiêu chí đánh giá thành công

Dự án được xem là hoàn thành khi:

### Hardware

- ESP8266 đọc được dữ liệu.
- Sensor hoạt động ổn định.
- ESP8266 kết nối WiFi.

### Communication

- Dữ liệu được truyền qua MQTT.
- Backend nhận được dữ liệu.

### Database

- Dữ liệu được lưu cùng timestamp.
- Có thể truy vấn lịch sử.

### Machine Learning

- Có baseline.
- Có model dự báo nhiệt độ.
- Có model dự báo xác suất mưa.
- Có metric đánh giá.
- Có kết quả test.

### Application

- Dashboard hiển thị dữ liệu realtime.
- Hiển thị dữ liệu lịch sử.
- Hiển thị forecast.
- Có rain alert.

### Integration

Toàn bộ pipeline hoạt động:

```text
Sensor
→ ESP8266
→ MQTT
→ Backend
→ Database
→ ML
→ Forecast
→ Dashboard / Alert
```

---

# 26. MVP và phần mở rộng

## MVP — Bắt buộc

- ESP8266
- BME280
- Rain Sensor
- WiFi
- MQTT
- Database
- Temperature forecasting
- Rain probability forecasting
- Dashboard cơ bản
- Alert

## Extension — Chỉ làm nếu còn thời gian

- LSTM/GRU.
- Thêm cảm biến ánh sáng.
- Thêm tốc độ gió.
- Multi-step forecasting nâng cao.
- Weather map.
- Mobile application.
- Cloud deployment.
- Model retraining tự động.
- Anomaly detection.
- So sánh dữ liệu sensor với nguồn thời tiết bên ngoài.

Không nên đưa toàn bộ extension vào scope bắt buộc.

---

# 27. Kết quả kỳ vọng

Sau khi hoàn thành, hệ thống có thể:

1. Tự động thu thập dữ liệu thời tiết.
2. Truyền dữ liệu theo thời gian thực.
3. Lưu trữ dữ liệu lịch sử.
4. Phân tích xu hướng thời tiết.
5. Dự báo nhiệt độ trong ngắn hạn.
6. Ước lượng xác suất mưa trong ngắn hạn.
7. Hiển thị kết quả trực quan.
8. Cảnh báo người dùng khi khả năng mưa cao.

Ví dụ:

```text
Current Weather
────────────────────────
Temperature : 31.2°C
Humidity    : 78%
Pressure    : 1005 hPa

Forecast
────────────────────────
+10 min : 31.0°C | Rain 25%
+30 min : 30.4°C | Rain 62%
+60 min : 29.6°C | Rain 84%

Status
────────────────────────
⚠ HIGH POSSIBILITY OF RAIN
```

---

# 28. Định hướng học thuật

Dự án kết hợp ba nhóm kiến thức:

```text
                 PROJECT
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
      IoT           Data          AI
       │             │            │
    ESP8266         Database      ML
    Sensor        Time Series   Forecast
    MQTT          Processing    Evaluation
       │             │            │
       └─────────────┴────────────┘
                    │
                    ▼
             Weather Forecast
```

Giá trị chính của dự án không nằm ở việc tạo ra một cảm biến nhiệt độ, mà nằm ở việc xây dựng **một pipeline IoT hoàn chỉnh từ sensing → communication → storage → forecasting → decision → actuation**.

---

# 29. Kết luận

Đề tài phù hợp với nhóm 3 người nếu giới hạn ở **dự báo thời tiết cục bộ trong ngắn hạn**.

Hai bài toán Machine Learning chính:

```text
1. Temperature Forecasting
   → dự báo nhiệt độ tại +10 / +30 / +60 phút

2. Rain Probability Forecasting
   → dự báo xác suất mưa tại +10 / +30 / +60 phút
```

Kiến trúc tổng thể:

```text
ESP8266 + Sensors
       ↓
      WiFi
       ↓
      MQTT
       ↓
    Backend
       ↓
   PostgreSQL
       ↓
Time Series Processing
       ↓
Forecasting Models
       ↓
Temperature + Rain Probability
       ↓
Dashboard
       ↓
Alert
       ↓
ESP8266
```

Mục tiêu của đồ án là tạo ra một **prototype IoT có khả năng hoạt động end-to-end**, đồng thời chứng minh bằng thực nghiệm rằng dữ liệu thời tiết lịch sử có thể được sử dụng để xây dựng mô hình dự báo ngắn hạn.

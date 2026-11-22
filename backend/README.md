# MODULE 2: DATA INGESTION, STORAGE & BACKEND API SERVER
## Máy Chủ Thu Thập Dữ Liệu, CSDL Chuỗi Thời Gian & REST/WebSocket API

> **Phụ trách chính:** 👤 **Thành viên 1 (IoT + Backend Engineer)**  
> **Phối hợp:** TV2 (kết nối DB lấy dữ liệu huấn luyện), TV3 (kết nối WebSocket và API lên Dashboard).  
> **Các Task liên quan:** `BE-01`, `BE-02`, `BE-03`, `BE-04`, `BE-05`, `BE-06` (Xem chi tiết tại [TASK.md](../TASK.md)).

---

## 1. Mục tiêu Kỹ thuật

Xây dựng hạ tầng Backend hiệu năng cao, chịu lỗi và có khả năng phục vụ theo thời gian thực:
1. **MQTT Data Ingestion Worker:** Chạy nền lắng nghe liên tục stream dữ liệu cảm biến từ topic `weather/+/data`, xác thực định dạng và lưu vào PostgreSQL.
2. **Time-Series Database:** Tối ưu hóa bảng CSDL `weather_measurements` với Composite Index `(device_id, timestamp DESC)` để các truy vấn cửa sổ trượt (Sliding Window) chạy dưới **10ms**.
3. **Hệ thống REST API (FastAPI):** Cung cấp các endpoint truy vấn thời tiết hiện tại, dữ liệu lịch sử phân trang và dữ liệu dự báo.
4. **Kênh WebSocket Thời gian thực:** Đẩy tức thời (Push notification) mỗi bản ghi thời tiết mới nhận được xuống Dashboard SCADA mà không cần client phải polling liên tục.
5. **Vòng lặp Cảnh báo Phản hồi 2 Chiều (Closed-loop Engine):** Khi mô hình AI dự báo xác suất mưa $\ge 70\%$, Backend tự động:
   - Bắn lệnh MQTT xuống trạm IoT (topic `weather/station01/alert`) để kích hoạt còi hú và đèn chớp.
   - Gửi tin nhắn cảnh báo có định dạng qua Telegram Bot đến người dùng.

---

## 2. Cấu trúc Thư mục Backend

```text
backend/
├── README.md               # Tài liệu hướng dẫn cài đặt và vận hành Backend
├── requirements.txt        # Danh sách thư viện Python cần thiết
├── requirements-inference.txt # Runtime tùy chọn cho artifacts TV2 đã bàn giao
├── Dockerfile              # File cấu hình đóng gói Docker image
├── .env.example            # Tệp mẫu biến môi trường (Database, MQTT, Telegram)
├── migrations/
│   └── 001_init_schema.sql # Script SQL khởi tạo bảng và chỉ mục tối ưu
├── app/
│   ├── main.py             # Entry point FastAPI, quản lý Lifespan & WebSocket
│   ├── config.py           # Cấu hình Pydantic BaseSettings đọc từ .env
│   ├── db/
│   │   ├── session.py      # Quản lý Database Connection Pool (Async/Sync)
│   │   └── models.py       # SQLAlchemy Models (weather_measurements, alert_logs)
│   ├── schemas/
│   │   └── weather.py      # Pydantic Schemas validate dữ liệu vào/ra
│   ├── ingestion/
│   │   └── mqtt_worker.py  # Thread/Daemon lắng nghe MQTT và ghi vào DB
│   ├── services/
│   │   ├── alert_service.py # Xử lý vòng lặp phản hồi 2 chiều & Telegram Bot
│   │   ├── forecast_client.py # Kiểm tra output và fallback an toàn
│   │   └── integrated_forecast.py # Ghép nhiệt độ ml/ với xác suất mưa ai_engine/
│   └── api/
│       └── endpoints.py    # REST API routes (/current, /history, /forecast...)
└── tests/
    └── test_api.py         # Kiểm thử tự động API endpoints
```

---

## 3. Thiết kế CSDL Chuỗi Thời Gian (Database Schema)

Bảng `weather_measurements`:
```sql
CREATE TABLE IF NOT EXISTS weather_measurements (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temperature NUMERIC(5, 2) NOT NULL,
    humidity NUMERIC(5, 2) NOT NULL,
    pressure NUMERIC(6, 2) NOT NULL,
    rain_raw INTEGER,
    rain_detected SMALLINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Composite Index cực kỳ quan trọng cho truy vấn cửa sổ trượt
CREATE INDEX idx_weather_device_timestamp 
ON weather_measurements (device_id, timestamp DESC);
```

---

## 4. Danh sách REST API Endpoints

| Phương thức | Endpoint | Mô tả | Đầu ra mẫu |
|---|---|---|---|
| `GET` | `/api/weather/current` | Lấy bản ghi thời tiết mới nhất của trạm | `{ "temperature": 31.2, "humidity": 78, "pressure": 1005.8 }` |
| `GET` | `/api/weather/history?limit=100` | Lấy dữ liệu lịch sử để vẽ biểu đồ | Mảng JSON các điểm dữ liệu gần nhất |
| `GET` | `/api/weather/forecast` | Dự báo từ lịch sử 120 phút của một trạm; 404 nếu không có mẫu gần đây | `plus_10m`, `plus_30m`, `plus_60m` (nhiệt độ, nguồn nhiệt độ, xác suất và nguồn mưa), metadata lịch sử và ngưỡng |
| `POST` | `/api/weather/alerts/threshold` | Cập nhật ngưỡng cảnh báo mưa 2 chiều | `{ "threshold": 0.65, "status": "updated" }` |
| `GET` | `/api/weather/alerts/threshold` | Đọc ngưỡng từ DB hoặc cấu hình mặc định `RAIN_ALERT_THRESHOLD` (giá trị ngoài [0, 1] hoặc không hợp lệ dùng mặc định); `/forecast` dùng đúng ngưỡng này để kích hoạt cảnh báo | `{ "threshold": 0.70, "source": "db", "updated_at": "..." }` |
| `GET` | `/api/weather/sensor-health?device_id=station01&window_minutes=360` | Sức khỏe cảm biến trong cửa sổ `[now - window, now]` (10–1440 phút, UTC); bỏ qua bản ghi có timestamp tương lai | `{ "device_id": "station01", "status": "OK", "checked_at": "...", "window_minutes": 360, "n_records": 30, "anomalies": [], "frozen_sensors": [], "rain_drift": false, "reason": null }` |
| `GET` | `/api/weather/benchmark?device_id=station01&source=open-meteo&hours=24` | Chuỗi tham chiếu trong `[now - hours, now]` (1–168 giờ, bỏ qua timestamp tương lai) và sai số IoT − tham chiếu tại mốc mới nhất; mẫu IoT dùng để tính sai số cũng bỏ qua timestamp tương lai; cần migration 002 | `{ "device_id": "station01", "source": "open-meteo", "hours": 24, "reference": [{ "timestamp": "...", "temperature": 30.0, "humidity": 75.0, "pressure": 1008.0 }], "latest_bias": { "temp_bias_c": 1.5, "hum_bias_percent": null, "press_bias_hpa": null, "reference_timestamp": "...", "n_iot": 5 } }` |
| `GET` | `/api/health` | Kiểm tra trạng thái Database & MQTT | `{ "database": "connected", "mqtt": "online" }` |
| `WebSocket`| `/ws/weather/live` | Stream đẩy dữ liệu realtime mỗi 5s | Đẩy payload JSON ngay khi nhận từ MQTT |

`/benchmark` chấp nhận `open-meteo` (lịch sử theo giờ, mặc định API), `open-meteo-15min` (bản tin hiện tại của crawler `--once`/`--loop`, mặc định Dashboard) và `openweather`. Chọn nguồn tường minh khi cần so sánh dữ liệu live; API không trộn các nguồn.

---

### Hành vi `/api/weather/forecast` (BE-05)

- Lấy **toàn bộ mẫu trong 120 phút gần nhất tính đến thời điểm gọi**, không giới hạn 30 bản ghi. Cửa sổ này đủ cho yêu cầu tối thiểu 90 phút của model nhiệt độ TV2 và có khoảng dự phòng theo chu kỳ gửi mẫu. Chỉ dùng một trạm, sắp xếp thời gian từ cũ đến mới và bỏ mẫu có timestamp tương lai.
- Truyền `?device_id=station01` để chọn trạm. Nếu không truyền, chọn trạm có mẫu mới nhất trong cửa sổ 120 phút; lịch sử của các trạm khác không được trộn vào inference.
- Nếu trạm không có mẫu trong cửa sổ này, trả **404** với `detail.code = "no_recent_measurements"`. API không tạo dự báo từ số liệu mặc định khi DB trống hoặc chỉ còn dữ liệu cũ.
- Đọc `rain_alert_threshold` từ `system_config` trước khi gọi AI; nếu chưa có cấu hình DB thì dùng `RAIN_ALERT_THRESHOLD` trong môi trường. Ngưỡng này dùng chung cho inference, `alert_triggered` và AlertService. `rain_level` vẫn là các mức mô tả cố định Low/Medium/High của inference.
- Mỗi horizon `plus_10m`, `plus_30m`, `plus_60m` có `rain_source` bằng `model` hoặc `heuristic`. Giữ nguồn riêng từng horizon; thiếu model/lịch sử một horizon không làm mất dự báo model hợp lệ của horizon khác. Fallback cục bộ cũng trả `rain_source=heuristic`.
- Với `FORECAST_ENGINE_MODE=auto`, adapter gọi `ml.inference_engine.get_engine()` để chạy artifacts `ml/models/*_h{10,30,60}min.joblib`, đồng thời gọi hàm rain-only của TV3. Nó không dùng model nhiệt độ cũ trong `ai_engine/saved_models/`. `temperature_source=model|persistence|heuristic` ở từng horizon và `temperature_model`, `temperature_confidence`, `temperature_fallback_reason` ở cấp phản hồi giúp phân biệt model thật với persistence khi lịch sử thiếu/gián đoạn.
- Phản hồi bổ sung `history_window_minutes`, `history_span_minutes`, `history_measurements` và `rain_alert_threshold` để kiểm tra đầu vào. `history_span_minutes` chỉ là khoảng cách giữa mẫu đầu/cuối, không chứng minh chuỗi liên tục hoặc model đủ feature.
- Model mưa hiện cần tối thiểu 61 phút lịch sử, khuyến nghị 76 phút. Khi thiếu lịch sử hoặc weights, inference có thể dùng heuristic; **HTTP 200 không chứng minh đang chạy model đã huấn luyện**.

Trạm dùng DO gửi `rain_raw = null`. Model nhiệt độ có `rain_raw` trong schema cần số đo AO. Để thử model nhiệt độ không dùng AO, chạy từ thư mục gốc với CSV số đo thật của một trạm, đã bỏ các lượt thử phần cứng:

```powershell
& backend/.venv/Scripts/python.exe -m ml.train_station_temperature station.csv --test-start 2026-11-15T04:15:00Z --candidate-dir ml/data/station-model
```

Lệnh so sánh MAE trên dữ liệu giữ riêng theo thời gian với phương án giữ nhiệt độ gần nhất. Nó chỉ lưu ứng viên ở các mốc có MAE thấp hơn. Sau khi kiểm định đủ dữ liệu, có thể cấu hình `FORECAST_ENGINE_MODE=auto` và `TEMPERATURE_MODEL_DIR` là đường dẫn tuyệt đối tới thư mục model và schema đã duyệt. Khi chưa có model phù hợp, dự báo nhiệt độ giữ số đo gần nhất và API ghi `temperature_source=persistence`.

Chế độ `FORECAST_ENGINE_MODE=regional_vvts` dùng artifact `ai_engine/saved_models/vvts_forecast.joblib` và bản tin Tân Sơn Nhất từ [Aviation Weather Center](https://aviationweather.gov/data/api/) cho trạm trong `REGIONAL_FORECAST_DEVICE_ID` (mặc định `station01`). Nó cần môi trường inference và HTTPS đi ra. API ghi `forecast_scope=VVTS`, thời gian bản tin và thời điểm dự báo của từng mốc. Mốc +10 phút, bản tin quá cũ, hoặc mốc đã qua được trả về là chưa có dữ liệu. API có thể trả dự báo khu vực ngay cả khi IoT offline. Backend gửi xác suất hợp lệ lên OLED theo MQTT hiện có, với `threshold_reached=false` vì dữ liệu sân bay chỉ phục vụ hiển thị. Cảnh báo khi tấm dò báo ướt do firmware xử lý tại chỗ.

Chế độ `FORECAST_ENGINE_MODE=station_inputs` dùng riêng số đo PostgreSQL của trạm được yêu cầu. Mốc +30 và +60 phút dùng `station_input_forecast.joblib`. Mốc +10 phút dùng `station_short_forecast.joblib`, được đánh giá trên quan trắc NEA Singapore. Cả hai dùng trung vị số đo trong 5 phút ở từng mốc đầu vào. API ghi `forecast_engine=station_inputs`, `forecast_scope=station` và `forecast_reference_at` bằng thời điểm mẫu mới nhất đã dùng. Khi thiếu lịch sử +10 phút, nhiệt độ giữ ở số đo mới nhất và xác suất mưa chưa có dữ liệu. Khi số đo mới nhất đã cũ, dự báo được bỏ qua. Backend chọn xác suất hợp lệ lớn nhất từ các mốc do mô hình tính; nếu đạt ngưỡng đang áp dụng, gửi cảnh báo qua MQTT với cooldown hiện có và cập nhật trạng thái màu LED qua bản tin forecast. Mốc chưa có xác suất từ mô hình không kích cảnh báo.

Các bài kiểm thử hợp đồng BE-05 dùng DB SQLite riêng, không sửa dữ liệu hay ngưỡng trên PostgreSQL đang thu thập:

```powershell
# Chạy từ thư mục backend
& .venv/Scripts/python.exe -m pytest -q tests/test_forecast.py
```

### Cảnh báo hai chiều và tác vụ nền (BE-06)

- API `/forecast` và tác vụ nền dùng chung `services/weather_forecast.py`, cùng ngưỡng DB và MQTT client đang chạy trong `app.state.mqtt_worker`.
- Tác vụ nền tự chạy theo lifespan FastAPI, mặc định **30 giây/lần**, không cần mở Dashboard. DB và inference chạy ở thread riêng; lỗi một trạm không dừng đánh giá các trạm khác. Khi shutdown, tác vụ dừng trước MQTT worker.
- Chỉ phát lệnh từ mẫu mới trong **120 giây** gần nhất. Vẫn có thể xem dự báo từ lịch sử cũ hơn trong cửa sổ 120 phút, nhưng không kích hoạt ngoại vi từ dữ liệu đó. `/api/health` có `alert_monitor_running` để kiểm tra tác vụ.
- Topic mặc định là `weather/{device_id}/alert`, thay `{device_id}` bằng đúng mã trạm. Cấu hình cũ `weather/station01/alert` được nhận diện như mẫu mặc định để không gửi nhầm cảnh báo trạm mô phỏng tới `station01`. Topic tùy chỉnh khác vẫn được giữ nguyên; có thể dùng `{device_id}` trong mẫu tùy chỉnh.
- Gửi QoS 1, **không retained**. `mqtt_sent=true` chỉ sau khi nhận PUBACK trong thời gian chờ; publish bị từ chối, mất kết nối hoặc hết thời gian đều ghi false. PUBACK chứng minh broker đã nhận, chưa chứng minh còi/relay vật lý đã chạy.
- Cooldown mặc định **180 giây theo từng trạm và từng kênh**. API và tác vụ nền không thể đồng thời phát hai lệnh cho cùng trạm. Kênh thất bại được thử lại mà không gửi lặp kênh đã thành công. Các lần bị cooldown không tạo log cảnh báo mới.
- `alert_logs.notes` ghi trạng thái kênh (`acknowledged`, `failed`, `unavailable`, `cooldown`, `disabled`). `alert_triggered` trong forecast là quyết định theo xác suất/ngưỡng, không phải biên nhận gửi thành công.
- Banner Dashboard dùng `rain_alert_threshold` trong chính response dự báo để tránh hiển thị ngưỡng cũ của trình duyệt. Banner chỉ báo xác suất đạt ngưỡng; không khẳng định còi đã chạy hoặc thông báo đã gửi.
- Telegram chỉ chạy khi được bật và có token/chat ID. Kiểm tra cả HTTP status và trường `ok` của Telegram; lỗi HTTP không ghi token vào log. Các bài test tự động dùng mock, không gửi tin thật.

Cấu hình trong `.env` (file mẫu đã cập nhật):

```ini
MQTT_ALERT_TOPIC=weather/{device_id}/alert
ALERT_COOLDOWN_SECONDS=180
ALERT_MQTT_ACK_TIMEOUT_SECONDS=2
ALERT_MONITOR_ENABLED=true
ALERT_EVALUATION_INTERVAL_SECONDS=30
ALERT_MAX_DATA_AGE_SECONDS=120
```

Cooldown hiện lưu trong bộ nhớ của **một tiến trình**, phù hợp lệnh uvicorn một worker của dự án; trạng thái được đặt lại khi restart. Cần lưu trạng thái/khóa dùng chung trước khi chạy nhiều worker hoặc nhiều instance. Chu kỳ 30 giây là thời gian chờ đánh giá tối đa thông thường, ngoài thời gian inference và gửi lệnh; đây không phải cam kết phản hồi dưới 2 giây từ lúc dữ liệu thay đổi.

Kiểm thử ACK, cooldown, mất kết nối, thử lại, không chặn event loop và vòng đời tác vụ:

```powershell
& .venv/Scripts/python.exe -m pytest -q tests/test_alerts.py tests/test_forecast_monitor.py tests/test_forecast.py
```

---

## 5. Hướng dẫn Cài đặt & Khởi chạy Cục bộ

### Bước 1: Chuẩn bị Môi trường Ảo
```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Danh sách cơ bản có cả `psycopg` 3 (driver mặc định cho URL `postgresql://` trên SQLAlchemy 2.1) và `psycopg2` cho cấu hình driver tường minh cũ. Không cần thay URL PostgreSQL hiện có khi cài mới.

Để chạy model đã bàn giao, dùng **Python 3.12 trở lên** và cài thêm runtime trong cùng môi trường:

```powershell
# Chạy từ backend
& .venv/Scripts/python.exe -m pip install -r requirements-inference.txt
```

Runtime inference cố định `scikit-learn==1.9.1` và `xgboost==3.4.1`, khớp phiên bản ghi trong artifacts hiện có. File này chỉ cài các thư viện dùng để suy luận; PyTorch, plotting và công cụ huấn luyện nằm trong `ml/requirements.txt`. `ml` nạp từng module theo nhu cầu nên import inference không kéo theo các công cụ huấn luyện. Khi thay artifacts bằng bản train mới, cần cập nhật phiên bản runtime và chạy lại kiểm thử tích hợp trước khi sử dụng.

### Bước 2: Thiết lập Biến Môi trường
Sao chép `.env.example` thành `.env`:
```bash
cp .env.example .env
```
Chỉnh sửa thông số trong `.env` cho phù hợp:
```ini
DATABASE_URL=postgresql://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
RAIN_ALERT_THRESHOLD=0.70
```

Giữ `FORECAST_ENGINE_MODE=heuristic` và `ANALYTICS_ENGINE_MODE=disabled` để chạy độc lập. Sau khi cài runtime và kiểm tra tích hợp, bật từng phần trong `backend/.env`:

```ini
FORECAST_ENGINE_MODE=auto
ANALYTICS_ENGINE_MODE=auto
```

`auto` cho forecast kích hoạt adapter TV2 + TV3; `auto` cho analytics kích hoạt kiểm tra cảm biến và bias. Thiếu weights mưa vẫn trả `rain_source=heuristic`; bật `auto` không tự tạo weights hoặc xác nhận độ chính xác mô hình.

### Bước 3: Chạy Database Migration
Đảm bảo PostgreSQL đang chạy. Backend mặc định áp dụng các migration còn thiếu trước khi chạy MQTT worker (`AUTO_MIGRATE=true`). Mỗi migration có checksum, transaction và khóa để tránh chạy đồng thời; không sửa file SQL đã áp dụng. Docker khởi tạo DB mới từ toàn bộ thư mục migrations. Với DB hiện hữu, có thể chạy thủ công từ gốc dự án:

```powershell
& backend/.venv/Scripts/python.exe backend/scripts/migrate.py
```

Migration 002 thêm dữ liệu tham chiếu; 003 thêm khóa khử bản tin lặp dạng nullable nên giữ nguyên lịch sử cũ. Runner không xóa volume hoặc bản ghi cũ. `AUTO_MIGRATE=false` dùng khi migration được quản lý riêng trong triển khai.

### Bước 4: Khởi chạy FastAPI Server & Ingestion
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Mở tài liệu API tự động (Swagger UI): `http://localhost:8000/docs`
- Kiểm tra kênh WebSocket: kết nối tới `ws://localhost:8000/ws/weather/live`

### Đóng gói Docker từ thư mục gốc dự án

Image dùng Python 3.12. Build context phải là thư mục gốc để mang theo cả `backend/`, `ml/` và các module TV3:

```bash
# Image chạy độc lập, giữ mặc định heuristic/disabled
docker build -f backend/Dockerfile -t weather-backend .

# Image có runtime suy luận và artifacts nhiệt độ đã bàn giao
docker build -f backend/Dockerfile --build-arg INSTALL_INFERENCE=true -t weather-backend:inference .
```

Dockerfile sao chép rõ các thư mục chương trình và artifacts, không sao chép `.env` hay môi trường ảo. Truyền cấu hình lúc chạy bằng `--env-file backend/.env`; khi bật model dùng image `:inference` và đặt hai chế độ `auto` như trên. Cấu hình `DATABASE_URL` và `MQTT_BROKER_HOST` phải trỏ tới địa chỉ DB/broker truy cập được từ container. Với PostgreSQL/Mosquitto chạy trên máy Docker Desktop, địa chỉ là `host.docker.internal`; `localhost` trong container chỉ trỏ lại container backend. Compose hiện tại khởi chạy DB và MQTT, chưa tự khởi chạy backend.

Kiểm tra đường suy luận thực với artifacts đã bàn giao (từ thư mục `backend`):

```powershell
& .venv/Scripts/python.exe -m pytest -q -m integrated_model
```

Nhóm test này bắt buộc model thật chạy thành công khi đủ lịch sử, kiểm tra fallback có lý do khi thiếu lịch sử và xác nhận package không import các công cụ huấn luyện ngoài ý muốn. Kiểm thử không đánh giá độ chính xác dự báo ngoài thực tế.

---

## 6. Tiêu chí Hoàn thành (Definition of Done)

- [ ] Ingestion Worker nhận message từ MQTT và ghi vào PostgreSQL mà không rò rỉ kết nối (Connection leak).
- [ ] API `/api/weather/current` và `/api/weather/history` phản hồi dưới 50ms.
- [ ] Kênh WebSocket tự động đẩy dữ liệu cho nhiều client cùng lúc (Broadcast).
- [ ] Khi giả lập dữ liệu xác suất mưa cao $\ge 70\%$, Backend tự động bắn lệnh MQTT xuống `weather/station01/alert` và gửi thông báo Telegram trong vòng < 2 giây.
- [ ] Vượt qua toàn bộ unit test trong `tests/test_api.py`.



## Hợp đồng telemetry và API Dashboard

Xem [hợp đồng dữ liệu v1](../docs/architecture/data_contract.md). Mẫu thiếu trường bắt buộc/sai kiểu/NaN/Infinity bị loại; giá trị hữu hạn bất thường giữ nguyên cho chẩn đoán, không clamp. Inference bỏ mẫu ngoài khoảng firmware và trả 409 `sensor_data_unusable` nếu mẫu mới nhất không dùng được. WebSocket chỉ phát sau commit thành công.

Mẫu có timestamp UTC khử trùng bằng unique `message_key`; firmware chỉ gửi uptime khử retransmit trong cache phiên, chưa cam kết exactly-once qua restart. Topic phải khớp device ID. `MQTT_TOPIC_PREFIX` mặc định `weather`; khi dùng namespace riêng cần đổi đồng bộ DATA/ALERT topics.

Ba API dành cho Dashboard có thuật toán TV3 tích hợp tùy chọn:

- `GET /api/weather/alerts/threshold`: đọc ngưỡng DB hoặc fallback cấu hình môi trường.
- `GET /api/weather/sensor-health?device_id=station01&window_minutes=360`: mặc định UNKNOWN/chưa tích hợp; sau khi opt-in provider SA-03 mới có phân tích. Không có dữ liệu/dữ liệu cũ vẫn là UNKNOWN.
- `GET /api/weather/benchmark?device_id=station01&source=open-meteo&hours=24`: trả tham chiếu thật; mặc định bias null/metrics rỗng. Sau khi opt-in provider SA-04 mới tính bias IoT trừ tham chiếu.

`FORECAST_ENGINE_MODE=heuristic` và `ANALYTICS_ENGINE_MODE=disabled` tiếp tục là mặc định để chạy độc lập. Hướng dẫn E2E có DB và MQTT namespace riêng: [integration_tests](../integration_tests/README.md).

## Chế độ độc lập TV1

Giữ `FORECAST_ENGINE_MODE=heuristic` và `ANALYTICS_ENGINE_MODE=disabled` (mặc định) khi chỉ cần chạy phần TV1. Backend khởi động mà không cần import các thư mục AI/phân tích; `/api/weather/integrations` báo trạng thái cấu hình. Sensor-health trả UNKNOWN/chưa tích hợp, benchmark giữ dữ liệu tham chiếu thật và để bias null. Forecast có `forecast_engine`, `fallback_reason`, `temperature_source` và `rain_source` từng horizon; heuristic không phải mô hình đã đánh giá độ chính xác.

Bật `auto` sau khi cài runtime và chạy nhóm kiểm thử `integrated_model`; output AI được kiểm tra giá trị hữu hạn, xác suất, device và timezone **trước** khi xét cảnh báo. Tài liệu và schema bàn giao: [tv1_independent_handoff.md](../docs/architecture/tv1_independent_handoff.md).


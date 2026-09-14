# KẾ HOẠCH TRIỂN KHAI BACKEND THEO TỪNG GIAI ĐOẠN (STAGE IMPLEMENTATION PLAN)
## Dành cho: Thành viên 1 (IoT + Backend Engineer)
**Dự án:** IoT Local Weather Monitoring & Short-Term Forecasting System  
**Không gian lưu trữ:** `personal/tv1/backend_implementation_stages.md`  
**Phiên bản:** 1.0.0 | **Ngày lập:** 2026-09-12  

---

## 1. TỔNG QUAN & NGUYÊN TẮC BẮT BUỘC (CORE PRINCIPLES & GOVERNANCE)

Tài liệu này đóng vai trò là kim chỉ nam kỹ thuật (Technical Roadmap) chi tiết từng bước để **Thành viên 1 (TV1)** triển khai, hoàn thiện, tối ưu hóa và kiểm thử toàn bộ hệ thống Backend.

### 1.1. Phạm vi trách nhiệm cốt lõi của TV1 (Scope of Responsibilities)
Căn cứ theo [TASK.md](../../TASK.md) và [docs/architecture/system_architecture.md](../../docs/architecture/system_architecture.md):
- **Hạ tầng kết nối & CSDL:** Cấu hình MQTT Broker Mosquitto (`BE-01`), Thiết kế tối ưu CSDL Time-series PostgreSQL (`BE-02`).
- **Data Ingestion:** Xây dựng Worker chạy ngầm lắng nghe stream MQTT và ghi vào DB thời gian thực (`BE-03`).
- **Tầng Giao diện Lập trình (API & WebSocket):** Phát triển REST API và kênh WebSocket Live đẩy dữ liệu tức thời xuống SCADA Dashboard (`BE-04`).
- **Tích hợp Trí tuệ Nhân tạo:** Xây dựng cầu nối gọi mô hình dự báo chuỗi thời gian của TV2 & TV3 (`BE-05`).
- **Hệ thống Cảnh báo Khép kín 2 Chiều (Closed-loop Actuation):** Tự động bắn lệnh MQTT xuống trạm IoT (hú còi, nháy LED) và gửi tin nhắn Telegram Bot khi phát hiện xác suất mưa $\ge 70\%$ (`BE-06`).
- **Phối hợp tích hợp liên thông:** Đảm bảo trạm IoT (`IOT-04`, `IOT-05`) kết nối thông suốt với Backend và hỗ trợ kiểm thử toàn chuỗi (`SYS-01`, `SYS-02`, `SYS-03`).

### 1.2. Các quy chuẩn kỹ thuật bắt buộc phải tuân thủ (Coding & Git Standards)
Căn cứ theo [CONTRIBUTING.md](../../CONTRIBUTING.md):

1. **Chiến lược phân nhánh Git (Branching):**
   - Không commit trực tiếp lên `main` hay `develop`.
   - Mọi giai đoạn phát triển phải tạo nhánh từ `develop` theo định dạng:
     `feature/tv1-<ten-tinh-nang>` hoặc `bugfix/tv1-<ten-loi>`.
   - Trước khi mở PR, đồng bộ từ `develop` về local nhánh tính năng để giải quyết xung đột (conflict).
2. **Quy chuẩn Commit Message:**
   - Cú pháp: `<type>(<scope>): <mo ta ngan gon> [MA-TASK]`
   - Ví dụ:
     - `feat(db): optimize connection pool and sliding window query [BE-02]`
     - `feat(ingestion): add thread-safe db session and reconnect logic [BE-03]`
     - `feat(alert): implement alert cooldown and telegram formatting [BE-06]`
3. **Quy chuẩn lập trình Python:**
   - **PEP 8:** Kiểm tra định dạng code trước khi commit.
   - **Type Annotations:** Mọi hàm xử lý và endpoint đều phải khai báo kiểu dữ liệu rõ ràng:
     ```python
     def evaluate_and_trigger(device_id: str, rain_probability: float, horizon_minutes: int, threshold: float | None = None) -> bool:
     ```
   - **Logging thay vì `print()`:** Tuyệt đối không dùng `print()`. Bắt buộc sử dụng `logger = logging.getLogger(...)` với các cấp độ `DEBUG`, `INFO`, `WARNING`, `ERROR`.
   - **Xử lý Ngoại lệ (Exception Handling):** Bắt exception cụ thể (`psycopg2.OperationalError`, `paho.mqtt.MQTTException`, `httpx.HTTPError`), không dùng `except Exception: pass`.
   - **Timestamp chuẩn UTC:** Mọi mốc thời gian lưu vào PostgreSQL đều phải là UTC ISO-8601 (`timestamptz`). Dashboard sẽ chuyển đổi sang GMT+7 khi hiển thị.
4. **Bảo mật (Security & Secret Management):**
   - Tuyệt đối không hardcode mật khẩu DB, Telegram Token hay Broker password trong mã nguồn. Toàn bộ đọc qua biến môi trường từ file `.env` (thông qua `app/config.py`).
   - File `.env` đã được cấu hình trong `.gitignore`.

---

## 2. HIỆN TRẠNG CODEBASE & CÁC KHOẢNG TRỐNG CẦN HOÀN THIỆN

### 2.1. Phân tích hiện trạng
Trong thư mục `backend/app/`, khung cấu trúc cơ bản đã được thiết lập:
- `app/main.py`: Khung FastAPI app, `ConnectionManager` WebSocket, vòng đời `lifespan`.
- `app/config.py`: Đọc cấu hình từ `.env` bằng `pydantic-settings`.
- `app/db/session.py` & `models.py`: Kết nối SQLAlchemy, model `WeatherMeasurement`, `AlertLog`, `SystemConfig`.
- `app/schemas/weather.py`: Pydantic Schemas đầu vào/ra.
- `app/ingestion/mqtt_worker.py`: Thread lắng nghe MQTT, ghi CSDL và gọi callback broadcast.
- `app/services/alert_service.py`: Đánh giá ngưỡng, gửi MQTT alert, gửi Telegram và ghi log.
- `app/services/forecast_client.py`: Import `ai_engine` với fallback heuristic dựa trên chênh lệch khí áp ($\Delta P$) và độ ẩm ($\Delta H$).
- `app/api/endpoints.py`: Endpoints `/current`, `/history`, `/forecast`, `/alerts/threshold`.

### 2.2. Các khoảng trống kỹ thuật (Gaps) cần giải quyết để đạt chuẩn sản phẩm
1. **Quản lý Session & Thread-Safety trong MQTT Worker:** Worker chạy ngầm trên luồng riêng của `paho-mqtt`. Cần đảm bảo việc mở/đóng `SessionLocal()` không gây nghẽn kết nối (connection leaks) khi nhận dữ liệu dồn dập (5-10s/lần).
2. **Khả năng tự phục hồi khi mất kết nối CSDL (DB Resilience):** Nếu CSDL PostgreSQL khởi động sau hoặc tạm thời rớt mạng, Backend và Ingestion Worker không được crash mà phải có cơ chế retry / reconnect an toàn.
3. **Cơ chế chống spam cảnh báo (Alert Debouncing & Cooldown):** Hiện tại mỗi khi gọi `/forecast` mà xác suất mưa $\ge 70\%$, `AlertService` sẽ kích hoạt còi hú và gửi Telegram ngay lập tức. Nếu Dashboard poll liên tục mỗi 15-30s, còi và Telegram sẽ bị spam dồn dập. Cần xây dựng **Cooldown Mechanism** (ví dụ: chỉ cảnh báo lại sau tối thiểu 3-5 phút đối với cùng 1 thiết bị).
4. **Bảo mật MQTT Broker & Đo đạc QoS (BE-01):** Broker Mosquitto hiện đang cấu hình `allow_anonymous true`. Cần hoàn thiện file cấu hình có user/password và thực nghiệm đo đạc độ trễ/tỉ lệ mất gói giữa QoS 0 và QoS 1 theo yêu cầu của `BE-01`.
5. **Đồng bộ Schema Migration:** Đảm bảo migration `migrations/001_init_schema.sql` có thể tự động chạy hoặc có script kiểm tra tính toàn vẹn của bảng và Composite Index.
6. **Bộ kiểm thử tự động (Unit & Integration Tests):** Bổ sung các bài test chuyên sâu cho WebSocket connection drops, MQTT worker payload parsing errors, alert cooldown logic.

---

## 3. BẢN ĐỒ CÁC GIAI ĐOẠN TRIỂN KHAI (STAGE BREAKDOWN)

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 0: Chuẩn bị Môi trường, Docker & Hạ tầng Cơ sở                             │
│ (Docker-compose, PostgreSQL, Mosquitto, .env, Virtualenv)                        │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 1 [BE-02]: CSDL Time-Series & Tối ưu hóa Truy vấn Cửa sổ trượt              │
│ (PostgreSQL 15, Composite Index, SQLAlchemy Session, Query < 10ms)               │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 2 [BE-01, BE-03]: MQTT Broker Hardening & Ingestion Worker Chịu lỗi        │
│ (Mosquitto Auth, Khảo sát QoS 0 vs QoS 1, Thread-safe Worker, Auto-reconnect)    │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 3 [BE-04]: Hệ thống REST API Phân trang & Kênh WebSocket Live Broadcast    │
│ (Endpoints /current, /history, WebSocket Manager, CORS, Swagger Docs)             │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 4 [BE-05]: Tích hợp AI Inference Engine & Quản lý Cấu hình Động             │
│ (Sliding Window 30 điểm, Contract với TV2/TV3, Heuristic Fallback, /threshold)   │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 5 [BE-06]: Vòng lặp Điều khiển 2 Chiều Closed-loop & Telegram Alert Bot     │
│ (Alert Cooldown/Debounce, MQTT Actuation xuống ESP, Telegram Markdown, Audit Log)│
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 6 [SYS-01, SYS-02, SYS-03]: Kiểm thử Tích hợp Toàn chuỗi (E2E) & Chịu lỗi   │
│ (Hardware Simulation, 3 Kịch bản Demo, Stress Test, Đo lường SLA & Metrics)      │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│ STAGE 7 [SYS-04]: Đóng gói Tài liệu Kỹ thuật & Chuẩn bị Báo cáo Đồ án            │
│ (Backend README, API Docs, Số liệu thực nghiệm chương TV1, PR Merge)             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. CHI TIẾT TỪNG GIAI ĐOẠN TRIỂN KHAI (STAGE SPECIFICATIONS)

---

### GIAI ĐOẠN 0: Chuẩn bị Môi trường & Hạ tầng Cơ sở (Base Infrastructure Setup)

#### 1. Mục tiêu
- Thiết lập môi trường chạy cục bộ chuẩn xác, đảm bảo các container Docker hoạt động ổn định và các biến môi trường được cấu hình đồng bộ.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `develop` (chuẩn bị) $\rightarrow$ tạo nhánh `feature/tv1-env-setup`
- **Commit:** `chore(backend): setup python venv and environment variables [BE-01]`

#### 3. Các bước thực hiện
1. **Tạo môi trường ảo Python và cài đặt dependencies:**
   ```bash
   cd backend
   python -m venv .venv
   # Kích hoạt trên Windows:
   .venv\Scripts\activate
   # Cài đặt thư viện:
   pip install -r requirements.txt
   ```
2. **Khởi tạo file `.env` từ `.env.example`:**
   ```bash
   cp .env.example .env
   ```
   Cấu hình thông số trong `backend/.env`:
   ```ini
   HOST=0.0.0.0
   PORT=8000
   DEBUG=True
   ALLOWED_ORIGINS=["*"]

   DATABASE_URL=postgresql://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db
   ASYNC_DATABASE_URL=postgresql+asyncpg://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db

   MQTT_BROKER_HOST=localhost
   MQTT_BROKER_PORT=1883
   MQTT_CLIENT_ID=fastapi_backend_worker
   MQTT_USERNAME=weather_admin
   MQTT_PASSWORD=weather_secure_pass_2026
   MQTT_DATA_TOPIC=weather/+/data
   MQTT_ALERT_TOPIC=weather/station01/alert

   RAIN_ALERT_THRESHOLD=0.70
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_CHAT_ID=
   ENABLE_TELEGRAM_NOTIFICATIONS=False
   ```
3. **Khởi động Docker Containers:**
   Tại thư mục gốc:
   ```bash
   docker-compose up -d
   docker-compose ps
   ```
   *Yêu cầu:* Cả `weather_mqtt_broker` và `weather_postgres_db` đều ở trạng thái `Up (healthy)`.

#### 4. Checklist nghiệm thu Stage 0
- [x] Container PostgreSQL lắng nghe cổng `5432` thành công (đã khởi tạo 3 bảng).
- [x] Container Mosquitto lắng nghe cổng `1883` (TCP) và `9001` (WebSocket) thành công.
- [x] Python `.venv` kích hoạt không sinh lỗi thiếu thư viện (đã verify qua pytest).

---

### GIAI ĐOẠN 1: CSDL Chuỗi Thời Gian & Tối Ưu Truy Vấn (Task BE-02)

#### 1. Mục tiêu
- Hoàn thiện schema CSDL thời gian thực, đảm bảo cơ chế đánh Composite Index hoạt động hiệu quả giúp truy vấn 30-100 bản ghi phục vụ Dashboard và AI Inference đạt độ trễ $< 10$ms.
- Hoàn thiện kết nối SQLAlchemy Session Pool chịu lỗi cao, tự động khôi phục kết nối.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-db-optimization-be02`
- **Commit:**
  - `feat(db): verify schema migration and composite indexes [BE-02]`
  - `refactor(db): implement robust session pool with pre-ping [BE-02]`

#### 3. Các file tác động
- `backend/migrations/001_init_schema.sql`
- `backend/app/db/session.py`
- `backend/app/db/models.py`
- `backend/app/config.py`

#### 4. Hướng dẫn triển khai kỹ thuật

##### Bước 1.1: Kiểm tra tính toàn vẹn Schema & Composite Index
Kiểm tra file `backend/migrations/001_init_schema.sql`:
- Bảng `weather_measurements` phải lưu `timestamp TIMESTAMPTZ` (UTC).
- Chỉ mục kết hợp `idx_weather_device_timestamp` trên `(device_id, timestamp DESC)`.
- Bảng `alert_logs` phục vụ giám sát vòng lặp 2 chiều.
- Bảng `system_config` lưu ngưỡng cảnh báo cấu hình động.

Kiểm tra trực tiếp trên DB bằng lệnh:
```bash
docker exec -it weather_postgres_db psql -U weather_admin -d weather_db -c "\d weather_measurements"
docker exec -it weather_postgres_db psql -U weather_admin -d weather_db -c "\di"
```

##### Bước 1.2: Tối ưu Connection Pool trong `app/db/session.py`
- Thiết lập `pool_pre_ping=True` để tự động kiểm tra tính khả dụng của connection trước khi trả về từ pool (chống lỗi ngắt kết nối do idle timeout).
- Thêm `pool_recycle=1800` (recycle sau 30 phút) và xử lý lỗi kết nối dịu dàng (graceful degradation) để app không bị sập nếu DB khởi động chậm.

```python
# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings
import logging

logger = logging.getLogger("weather_backend.db")
Base = declarative_base()

try:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.error("Loi khoi tao Database Engine: %s", e)
    SessionLocal = None
```

##### Bước 1.3: Đo lường hiệu năng truy vấn (Benchmark Latency)
Tạo script chèn 10,000 bản ghi mẫu vào DB và đo lường thời gian thực thi của câu lệnh:
```sql
EXPLAIN ANALYZE 
SELECT * FROM weather_measurements 
WHERE device_id = 'station01' 
ORDER BY timestamp DESC 
LIMIT 30;
```
*Tiêu chí:* Kết quả `Execution Time` phải nhỏ hơn **5ms** nhờ `Index Scan using idx_weather_device_timestamp`.

#### 5. Checklist nghiệm thu Stage 1
- [x] Schema và index được tạo đầy đủ trong container PostgreSQL.
- [x] Truy vấn cửa sổ trượt 30 bản ghi gần nhất chạy dưới 10ms (Thực tế đạt ~0.64ms, Execution Time: 0.105ms).
- [x] `session.py` có cơ chế `pool_pre_ping`, `pool_recycle` và không rò rỉ session.

---

### GIAI ĐOẠN 2: MQTT Broker Hardening & Ingestion Worker Chịu Lỗi (Tasks BE-01, BE-03)

#### 1. Mục tiêu
- Cấu hình bảo mật Mosquitto Broker, thiết lập xác thực user/password.
- Thực nghiệm đo lường QoS 0 vs QoS 1 để đưa vào báo cáo đồ án (Yêu cầu của `BE-01`).
- Hoàn thiện `MQTTIngestionWorker` chạy nền ổn định: parse payload JSON chuẩn, validate dữ liệu, gán timestamp UTC, ghi DB an toàn theo luồng (thread-safe), tự động kết nối lại khi broker rớt.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-mqtt-ingestion-be01-be03`
- **Commit:**
  - `feat(mqtt): configure broker authentication and topic security [BE-01]`
  - `feat(ingestion): harden mqtt worker with thread-safe db session [BE-03]`
  - `test(mqtt): add latency and packet-loss benchmark for QoS 0 vs QoS 1 [BE-01]`

#### 3. Các file tác động
- `docker/mosquitto/config/mosquitto.conf`
- `backend/app/ingestion/mqtt_worker.py`
- `backend/app/config.py`

#### 4. Hướng dẫn triển khai kỹ thuật

##### Bước 2.1: Cấu hình Mosquitto Broker bảo mật (BE-01)
Tạo tệp mật khẩu cho Mosquitto trong container hoặc cập nhật `docker/mosquitto/config/mosquitto.conf`:
- Bật xác thực người dùng (hoặc duy trì chế độ an toàn cho dev có password file).
- Đảm bảo cấu hình hỗ trợ đồng thời cổng `1883` (cho ESP32/Worker) và `9001` (WebSocket nếu cần).
```conf
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd

listener 9001
protocol websockets
allow_anonymous false

persistence true
persistence_location /mosquitto/data/
log_dest stdout
log_dest file /mosquitto/log/mosquitto.log
```
*Lưu ý cho dev:* Có thể tạo user bằng lệnh:
```bash
docker exec -it weather_mqtt_broker mosquitto_passwd -b -c /mosquitto/config/passwd weather_admin weather_secure_pass_2026
```

##### Bước 2.2: Báo cáo thực nghiệm so sánh QoS 0 vs QoS 1 (Yêu cầu BE-01)
Viết một script kiểm thử ngắn (hoặc sử dụng `integration_tests/simulate_iot_device.py`) để đo:
1. **Độ trễ truyền nhận (Latency):** Thời gian từ khi thiết bị publish tới khi worker nhận được.
2. **Độ tin cậy khi mạng chập chờn:** Tỉ lệ rơi gói tin khi ngắt kết nối mạng 5 giây.
3. **Kết luận kỹ thuật:** QoS 1 đảm bảo gói tin thời tiết không bị mất (At least once), phù hợp cho việc lưu trữ chuỗi thời gian phân tích AI và lệnh cảnh báo khẩn cấp `weather/station01/alert`.

##### Bước 2.3: Hoàn thiện `app/ingestion/mqtt_worker.py` (BE-03)
Đảm bảo các nguyên tắc sau:
- **Thread-safe DB Session:** Mỗi khi có message đến, mở `db = SessionLocal()` trong khối `try...finally: db.close()`. Tránh dùng chung một session xuyên suốt vòng đời worker.
- **Data Validation & Sanitization:** Kiểm tra các trường `temperature`, `humidity`, `pressure`. Nếu giá trị bất thường vượt ngưỡng vật lý (ví dụ: nhiệt độ $> 80^\circ$C hoặc $< -20^\circ$C do sensor lỗi), ghi log cảnh báo nhưng vẫn ghi nhận trạng thái vào DB hoặc xử lý ngoại lệ an toàn.
- **Timestamp chuẩn hóa:** Sử dụng `datetime.now(timezone.utc)`.
- **Auto-reconnect:** `paho-mqtt` loop tự động quản lý reconnect, bổ sung logging rõ ràng tại `on_disconnect`.

```python
# app/ingestion/mqtt_worker.py
def _on_message(self, client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)
        
        device_id = str(data.get("device_id", "station01"))
        temp = float(data.get("temperature", 0.0))
        hum = float(data.get("humidity", 0.0))
        press = float(data.get("pressure", 0.0))
        rain_raw = data.get("rain_raw")
        rain_detected = int(data.get("rain_detected", 0))

        # Lưu DB an toàn
        if SessionLocal:
            db = SessionLocal()
            try:
                record = WeatherMeasurement(
                    device_id=device_id,
                    timestamp=datetime.now(timezone.utc),
                    temperature=temp,
                    humidity=hum,
                    pressure=press,
                    rain_raw=rain_raw,
                    rain_detected=rain_detected
                )
                db.add(record)
                db.commit()
            except Exception as dbe:
                db.rollback()
                logger.error("[MQTT WORKER] Loi ghi DB: %s", dbe)
            finally:
                db.close()

        # Bắn WebSocket broadcast
        if self.broadcast_callback:
            self.broadcast_callback({
                "device_id": device_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperature": temp,
                "humidity": hum,
                "pressure": press,
                "rain_raw": rain_raw,
                "rain_detected": rain_detected
            })
    except Exception as e:
        logger.error("[MQTT WORKER] Parse error payload: %s", e)
```

#### 5. Checklist nghiệm thu Stage 2
- [x] Broker Mosquitto kết nối có xác thực, từ chối client không có credentials (rc=5 khi anonymous).
- [x] Báo cáo / số liệu so sánh định lượng QoS 0 vs QoS 1 sẵn sàng đưa vào báo cáo đồ án.
- [x] Ingestion Worker chạy ổn định, parse JSON không bị crash khi nhận payload rác hoặc thiếu trường.
- [x] Dữ liệu được ghi thành công vào bảng `weather_measurements` và đẩy qua callback.

---

### GIAI ĐOẠN 3: REST API & Kênh WebSocket Live Broadcast (Task BE-04)

#### 1. Mục tiêu
- Xây dựng hoàn chỉnh các REST API: `/api/weather/current`, `/api/weather/history`, `/api/health`.
- Tối ưu hóa kênh WebSocket `/ws/weather/live`: broadcast đồng thời cho nhiều kết nối Dashboard, quản lý đóng mở kết nối, không crash khi client ngắt kết nối đột ngột.
- Hỗ trợ đầy đủ CORS cho Dashboard SCADA của TV3.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-rest-websocket-api-be04`
- **Commit:**
  - `feat(api): implement /current and /history with pagination [BE-04]`
  - `feat(websocket): optimize live broadcast manager with safe disconnect [BE-04]`

#### 3. Các file tác động
- `backend/app/main.py`
- `backend/app/api/endpoints.py`
- `backend/app/schemas/weather.py`

#### 4. Hướng dẫn triển khai kỹ thuật

##### Bước 3.1: Hoàn thiện REST Endpoints trong `app/api/endpoints.py`
- `GET /api/weather/current`: Trả về dữ liệu mới nhất. Nếu DB rỗng, trả về fallback an toàn (HTTP 200) có cờ `status: "waiting_data"` để Dashboard không bị vỡ giao diện.
- `GET /api/weather/history`:
  - Query parameters: `device_id: Optional[str]`, `limit: int = 50` (tối đa 1000), `start_time: Optional[datetime]`, `end_time: Optional[datetime]`.
  - Sắp xếp: Query theo `ORDER BY timestamp DESC LIMIT :limit`, sau đó đảo ngược danh sách (`reversed(records)`) trước khi trả về để frontend vẽ đồ thị thời gian từ trái qua phải.
- `GET /api/health`: Kiểm tra sức khỏe hệ thống: trạng thái DB connection, trạng thái MQTT broker connection, số lượng client WebSocket đang theo dõi.

##### Bước 3.2: Tối ưu hóa `ConnectionManager` trong `app/main.py`
Xử lý các ngoại lệ khi client mất kết nối đột ngột mà không kịp gửi cờ đóng (Dead connection):
```python
async def broadcast(self, message: dict):
    text = json.dumps(message)
    dead_connections = []
    for connection in list(self.active_connections):
        try:
            await connection.send_text(text)
        except Exception as e:
            logger.warning("[WEBSOCKET] Phat hien ket noi hong: %s", e)
            dead_connections.append(connection)
    for dead in dead_connections:
        self.disconnect(dead)
```

##### Bước 3.3: Swagger UI Documentation & Response Validation
- Kiểm tra tính hợp lệ của Pydantic schema tại `http://localhost:8000/docs`.
- Xác nhận các kiểu dữ liệu float được làm tròn hợp lý (2 chữ số thập phân cho nhiệt độ/độ ẩm/áp suất).

#### 5. Checklist nghiệm thu Stage 3
- [x] Endpoint `/api/weather/current` phản hồi $< 30$ms (Thực tế benchmark 100 requests đạt trung bình ~12.70ms, p95 13.44ms, có fallback an toàn với cờ `status: "waiting_data"`).
- [x] Endpoint `/api/weather/history` hỗ trợ phân trang (`limit`, `offset`), lọc theo thiết bị (`device_id`) và khoảng thời gian (`start_time`, `end_time`), tự động sắp xếp theo thứ tự thời gian tăng dần (cũ -> mới) phục vụ vẽ đồ thị SCADA.
- [x] Kênh WebSocket `/ws/weather/live` hỗ trợ broadcast đồng thời đa kết nối (đã kiểm thử 5 clients đồng thời), tự động dọn dẹp các dead connections an toàn mà không làm nghẽn async event loop.
- [x] Mở Swagger UI tại `/docs` hiển thị đầy đủ schema OpenAPI, tags metadata và mô tả tiếng Việt chi tiết, chuẩn hóa validation làm tròn 2 chữ số thập phân cho các chỉ số float.

---

### GIAI ĐOẠN 4: Tích Hợp AI Inference Engine & Quản Lý Cấu Hình Động (Task BE-05)

#### 1. Mục tiêu
- Xây dựng endpoint `GET /api/weather/forecast` lấy cửa sổ trượt 30 điểm đo gần nhất từ CSDL, chuyển tiếp sang module suy luận của TV2 & TV3.
- Xây dựng cơ chế Heuristic Fallback thông minh khi chưa có file weights model hoặc khi module AI đang huấn luyện.
- Xây dựng endpoint `POST /api/weather/alerts/threshold` cho phép Dashboard cập nhật ngưỡng cảnh báo mưa lưu vào bảng `system_config`.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-forecast-integration-be05`
- **Commit:**
  - `feat(forecast): integrate unified inference engine with heuristic fallback [BE-05]`
  - `feat(config): implement dynamic threshold update endpoint [BE-05]`

#### 3. Các file tác động
- `backend/app/services/forecast_client.py`
- `backend/app/api/endpoints.py`
- `backend/app/schemas/weather.py`

#### 4. Hướng dẫn triển khai kỹ thuật

##### Bước 4.1: Thống nhất Contract Giao tiếp với TV2 & TV3
Theo phân công trong `TASK.md`, TV2 & TV3 cung cấp hàm `predict_forecast(recent_df: pd.DataFrame) -> dict`:
- **Đầu vào:** `DataFrame` chứa tối thiểu 30 dòng, có các cột: `temperature`, `humidity`, `pressure`, `rain_raw`, `rain_detected`.
- **Đầu ra:** Dictionary chuẩn hóa:
  ```json
  {
    "device_id": "station01",
    "generated_at": "2026-09-12T13:45:00Z",
    "current_temperature": 31.2,
    "current_humidity": 78.0,
    "current_pressure": 1006.5,
    "plus_10m": { "temperature_c": 31.0, "rain_probability": 0.25, "rain_level": "Low" },
    "plus_30m": { "temperature_c": 30.5, "rain_probability": 0.72, "rain_level": "High" },
    "plus_60m": { "temperature_c": 29.8, "rain_probability": 0.85, "rain_level": "High" },
    "alert_triggered": true,
    "alert_message": "Canh bao xac suat mua cao trong 30-60 phut toi!"
  }
  ```

##### Bước 4.2: Hoàn thiện Heuristic Fallback trong `app/services/forecast_client.py`
Khi TV2 chưa xuất xưởng model hoặc môi trường test thiếu thư viện scikit-learn/xgboost, hàm fallback tự động phân tích:
- **Tốc độ tụt áp ($\Delta P$):** $P_t - P_{t-5}$. Nếu $\Delta P \le -1.0$ hPa $\rightarrow$ Xác suất mưa tăng thêm 35%.
- **Tốc độ tăng ẩm ($\Delta H$):** $H_t - H_{t-5}$. Nếu $\Delta H \ge 5.0\%$ hoặc $H_t > 80\% \rightarrow$ Xác suất mưa tăng thêm 30%.
- Giúp hệ thống luôn luôn hoạt động thông suốt trong các buổi demo thử nghiệm mà không bị gián đoạn.

##### Bước 4.3: Quản lý Ngưỡng Cảnh báo Động (`system_config`)
- Khi người dùng điều chỉnh thanh trượt trên Web SCADA (ví dụ từ 70% xuống 60%), Dashboard gọi `POST /api/weather/alerts/threshold`.
- API kiểm tra $0.0 \le \text{threshold} \le 1.0$, lưu vào DB và cập nhật biến trong cache bộ nhớ để giảm tải truy vấn DB ở các lần dự báo tiếp theo.

#### 5. Checklist nghiệm thu Stage 4
- [ ] Endpoint `/api/weather/forecast` trả về đúng định dạng JSON 3 mốc thời gian (+10m, +30m, +60m).
- [ ] Cơ chế Fallback Heuristic hoạt động trơn tru khi không tìm thấy `ai_engine`.
- [ ] Cập nhật ngưỡng qua `/api/weather/alerts/threshold` thành công và ghi nhận vào bảng `system_config`.

---

### GIAI ĐOẠN 5: Vòng Lặp Điều Khiển 2 Chiều Closed-Loop & Bot Telegram (Task BE-06)

#### 1. Mục tiêu
- Xây dựng `AlertService` hoàn chỉnh: Khi xác suất mưa dự báo $\ge \text{threshold}$ (mặc định 70%):
  1. Tự động publish lệnh cảnh báo xuống topic `weather/station01/alert` (QoS 1) để trạm IoT kích hoạt Buzzer và LED.
  2. Tự động gửi thông báo định dạng Markdown qua Telegram Bot tới người dùng.
  3. Ghi vết kiểm toán (Audit Trail) vào bảng `alert_logs`.
- **Đặc biệt:** Cài đặt **Cơ chế Cooldown / Anti-spam** (chỉ kích hoạt cảnh báo cách nhau tối thiểu $N$ phút) để tránh làm phiền người dùng và quá tải thiết bị.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-closed-loop-alert-be06`
- **Commit:**
  - `feat(alert): implement closed-loop actuation and alert cooldown logic [BE-06]`
  - `feat(telegram): add formatted markdown notifications with retry [BE-06]`

#### 3. Các file tác động
- `backend/app/services/alert_service.py`
- `backend/app/api/endpoints.py`
- `backend/app/config.py`

#### 4. Hướng dẫn triển khai kỹ thuật

##### Bước 5.1: Xây dựng Cơ chế Cooldown trong `AlertService`
Lưu vết thời điểm cảnh báo gần nhất trong bộ nhớ (`_last_alert_time` dictionary theo `device_id`):
```python
# app/services/alert_service.py
import time
from datetime import datetime, timezone
import httpx
import json
import logging

logger = logging.getLogger("weather_backend.alert")

class AlertService:
    _last_alert_timestamp: dict[str, float] = {}
    COOLDOWN_SECONDS: int = 180  # 3 phút cooldown giữa 2 lần kích hoạt còi/telegram

    @classmethod
    def should_trigger(cls, device_id: str, rain_prob: float, threshold: float) -> bool:
        if rain_prob < threshold:
            return False
        
        now = time.time()
        last_time = cls._last_alert_timestamp.get(device_id, 0)
        if now - last_time < cls.COOLDOWN_SECONDS:
            logger.info("[ALERT ENGINE] Dang trong thoi gian cooldown cho trạm %s (con %ds). Bo qua phat alert.", 
                        device_id, int(cls.COOLDOWN_SECONDS - (now - last_time)))
            return False
        
        cls._last_alert_timestamp[device_id] = now
        return True
```

##### Bước 5.2: Định dạng Payload MQTT gửi xuống Trạm IoT (Phối hợp với `IOT-05`)
Payload JSON được gửi xuống topic `weather/station01/alert`:
```json
{
  "type": "rain_warning",
  "device_id": "station01",
  "probability": 0.85,
  "forecast_minutes": 30,
  "timestamp": "2026-09-12T14:00:00Z",
  "action": {
    "buzzer": true,
    "led_blink": true,
    "oled_message": "MUA (+30m: 85%)"
  }
}
```
*Yêu cầu:* Publish với **QoS 1** để đảm bảo gói tin cảnh báo chắc chắn được đưa tới trạm đo.

##### Bước 5.3: Tích hợp Gửi Tin Nhắn Telegram Bot
- Sử dụng thư viện `httpx` (async hoặc sync with timeout 5s).
- Định dạng tin nhắn chuyên nghiệp với emoji và Markdown:
  ```text
  ⚠️ CẢNH BÁO MƯA CỤC BỘ (IOT WEATHER) ⚠️
  
  📍 Trạm đo: station01
  🌧 Xác suất mưa: 85.0%
  ⏱ Khung thời gian: +30 phút tới
  🔔 Hành động: Trạm IoT đã tự động kích hoạt còi và đèn cảnh báo ngoài trời!
  ```
- Bắt lỗi khi không có kết nối internet hoặc Token chưa được điền trong file `.env` (không làm crash luồng chính).

##### Bước 5.4: Ghi vết Audit Trail vào bảng `alert_logs`
Mọi lần kích hoạt đều được lưu vào CSDL: `device_id`, `rain_probability`, `threshold`, `mqtt_sent`, `telegram_sent`, `notes`.

#### 5. Checklist nghiệm thu Stage 5
- [ ] Khi xác suất mưa $\ge 70\%$, trạm giả lập nhận được message trên topic `weather/station01/alert`.
- [ ] Tin nhắn Telegram được gửi về điện thoại đúng mẫu Markdown (khi cấu hình token).
- [ ] Cơ chế Cooldown hoạt động chuẩn xác: Không gửi liên tục nếu gọi `/forecast` dồn dập.
- [ ] Bảng `alert_logs` có bản ghi tương ứng.

---

### GIAI ĐOẠN 6: Kiểm Thử Tích Hợp Toàn Chuỗi (E2E) & Khả Năng Chịu Lỗi (Tasks SYS-01, SYS-02, SYS-03)

#### 1. Mục tiêu
- Phối hợp toàn bộ các thành phần: Chạy trạm giả lập `simulate_iot_device.py`, Backend Server, WebSocket broadcast và bộ kịch bản nghiệm thu `test_end_to_end.py`.
- Thực hiện đầy đủ 3 kịch bản Demo nghiệm thu theo [docs/demo_scenarios/scenarios.md](../../docs/demo_scenarios/scenarios.md):
  1. Giám sát thời gian thực liên tục.
  2. Dự báo thời tiết ngắn hạn và so sánh giá trị.
  3. Kích hoạt tình huống mưa mô phỏng $\rightarrow$ Phản hồi 2 chiều khép kín.
- Kiểm thử khả năng chịu lỗi (Fault tolerance): Rút kết nối mạng, khởi động lại DB, gửi dữ liệu dị thường.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-e2e-integration-sys01`
- **Commit:**
  - `test(backend): execute e2e tests and verify closed-loop response [SYS-01]`
  - `test(resilience): verify fault recovery on broker and db reconnect [SYS-02]`

#### 3. Các file tác động
- `integration_tests/simulate_iot_device.py`
- `integration_tests/test_end_to_end.py`
- `backend/tests/test_api.py`

#### 4. Kịch bản chạy kiểm thử thực tế

##### Kịch bản 1: Giám sát ổn định (Baseline Monitoring)
```bash
# Terminal 1: Chạy Backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Chạy trạm giả lập phát dữ liệu tự nhiên
python integration_tests/simulate_iot_device.py --broker localhost --interval 5
```
*Quan sát:*
- Console Backend log dòng `[MQTT WORKER] Nhan du lieu...` và broadcast qua WebSocket.
- Mở trình duyệt tại `http://localhost:8000/api/weather/current` nhận được dữ liệu cập nhật liên tục.

##### Kịch bản 2: Mô phỏng mưa và Phản hồi 2 chiều khép kín (Closed-loop Demo)
```bash
# Terminal 2: Kích hoạt cờ mô phỏng mưa
python integration_tests/simulate_iot_device.py --simulate-rain --interval 3
```
*Quan sát:*
- Trạm giả lập hạ áp suất, tăng độ ẩm, bật cờ mưa.
- Gọi `GET /api/weather/forecast`.
- Console trạm giả lập hiển thị:
  `*** [MOCK STATION NHAN LENH PHAN HOI 2 CHIEU] ***`
  `Hanh dong phan cung: [COI BUZZER KEU BIP BIP] [LED CHOP NHAY] [OLED: MUA (+30m: 85%)]`
- Nếu cấu hình Telegram, điện thoại nhận thông báo.

##### Kịch bản 3: Kiểm tra tự động hóa toàn chuỗi
```bash
python integration_tests/test_end_to_end.py
```
*Yêu cầu kết quả:*
```text
=======================================================
BAT DAU KIEM THU TICH HOP TOAN HE THONG (END-TO-END)
=======================================================
1. Backend Health Check            [PASS]      Online
2. API Current Weather             [PASS]      T=31.2°C, H=78.0%
3. AI Inference API (/forecast)    [PASS]      +30m Forecast: 30.5°C, Rain: 85%
4. Closed-loop Threshold Update    [PASS]      Updated to 65% successfully
-----------------------------------------------------------------
>>> TAT CA BAI KIEM THU LIEN THONG DEU DAT YEU CAU! <<<
```

##### Kịch bản 4: Chạy Unit Tests của Backend
```bash
cd backend
pytest tests/test_api.py -v
```

#### 5. Checklist nghiệm thu Stage 6
- [ ] Tất cả 4 bước trong `test_end_to_end.py` đều đạt `[PASS]`.
- [ ] Cả 3 kịch bản demo chạy trơn tru, không có hiện tượng treo ứng dụng.
- [ ] Khả năng phục hồi tốt khi ngắt kết nối mạng hoặc restart Docker container.

---

### GIAI ĐOẠN 7: Hoàn Thiện Hồ Sơ Kỹ Thuật & Báo Cáo Đồ Án (Task SYS-04)

#### 1. Mục tiêu
- Cập nhật toàn diện tài liệu kỹ thuật tại `backend/README.md` để các thành viên khác dễ dàng sử dụng và tích hợp.
- Tổng hợp toàn bộ số liệu đo đạc (Độ trễ truy vấn CSDL, Bảng so sánh QoS 0 vs QoS 1, biểu đồ thời gian phản hồi closed-loop) để phục vụ viết các chương thuộc phần phân công của TV1 trong Báo cáo Đồ án tốt nghiệp:
  - *Chương: Thiết kế Hệ thống Nhúng & Mạng Cảm biến IoT.*
  - *Chương: Hạ tầng Thu thập Dữ liệu & Kiến trúc CSDL Chuỗi Thời Gian.*
  - *Chương: Hệ thống REST API, WebSocket & Điều Khiển Phản Hồi 2 Chiều Khép Kín.*
- Tạo Pull Request chính thức hợp nhất toàn bộ tính năng vào nhánh `develop`.

#### 2. Nhánh Git & Quy ước
- **Nhánh:** `feature/tv1-final-documentation`
- **Commit:** `docs(backend): update full architectural documentation and benchmarks [SYS-04]`

#### 3. Các file tác động
- `backend/README.md`
- `docs/reports/` (nội dung draft chương TV1)
- `personal/tv1/` (nhật ký thực nghiệm cá nhân)

#### 4. Checklist nghiệm thu Stage 7
- [ ] Tự kiểm tra bảng **Local Verification Checklist** theo mục 4 của `CONTRIBUTING.md`.
- [ ] Tạo Pull Request trên Git trỏ từ `feature/tv1-...` vào `develop` có điền đủ PR Template.
- [ ] Được TV2 hoặc TV3 review và phê duyệt (Approve).
- [ ] Đầy đủ số liệu thực nghiệm và hình chụp màn hình phục vụ Báo cáo Đồ án.

---

## 5. BẢNG TỔNG HỢP TIẾN ĐỘ & ĐỐI CHIẾU NHIỆM VỤ (TRACEABILITY MATRIX)

| Mã Giai đoạn | Mã Task (TASK.md) | Nội dung công việc trọng tâm | File code chính | Tiêu chí hoàn thành (DoD) |
|---|:---:|---|---|---|
| **Stage 0** | `BE-01` | Cấu hình môi trường Python, Docker, `.env` | `docker-compose.yml`, `.env` | 2 container chạy khỏe mạnh, venv sẵn sàng. |
| **Stage 1** | `BE-02` | Khởi tạo Schema PostgreSQL & Đánh Composite Index | `migrations/001_init_schema.sql`, `session.py`, `models.py` | Query cửa sổ trượt 30 điểm đo $< 10$ms. |
| **Stage 2** | `BE-01`, `BE-03` | Bảo mật MQTT Broker & Xây dựng Ingestion Worker | `mosquitto.conf`, `mqtt_worker.py` | Worker ghi DB an toàn, có báo cáo so sánh QoS 0/1. |
| **Stage 3** | `BE-04` | REST API `/current`, `/history` & WebSocket Broadcast | `endpoints.py`, `main.py`, `schemas/weather.py` | API phản hồi $< 50$ms, WebSocket push mượt mà cho multi-clients. |
| **Stage 4** | `BE-05` | Tích hợp AI Inference Engine & Ngưỡng động | `forecast_client.py`, `endpoints.py` | Trả về forecast 3 mốc, fallback heuristic ổn định. |
| **Stage 5** | `BE-06` | Vòng lặp Closed-loop Actuation & Bot Telegram | `alert_service.py` | Tự động publish alert QoS 1, gửi Telegram, có Cooldown anti-spam. |
| **Stage 6** | `SYS-01`, `SYS-02`, `SYS-03` | Kiểm thử Tích hợp toàn chuỗi End-to-End | `simulate_iot_device.py`, `test_end_to_end.py` | Vượt qua 100% các bài test liên thông & 3 kịch bản demo. |
| **Stage 7** | `SYS-04` | Cập nhật tài liệu kỹ thuật & Hoàn thiện báo cáo | `backend/README.md`, PR Review | Đầy đủ tài liệu, code merge vào `develop`. |

---

## 6. LƯU Ý KỸ THUẬT & PHÒNG NGỪA RỦI RO DÀNH RIÊNG CHO TV1 (PRO-TIPS FOR TV1)

1. **Vấn đề lệch múi giờ (Timezone Trap):**
   - Luôn sử dụng `datetime.now(timezone.utc)` khi gán timestamp cho bản ghi CSDL và message MQTT.
   - Không tự ý cộng 7 tiếng ở tầng Backend vì sẽ làm sai lệch các phép tính thời gian trễ của TV2 trong Feature Engineering. Dashboard của TV3 sẽ tự động chuyển đổi sang múi giờ trình duyệt người dùng.
2. **Vấn đề rò rỉ kết nối CSDL (Connection Pool Exhaustion):**
   - Trong `mqtt_worker.py`, tuyệt đối không lưu giữ đối tượng `db = SessionLocal()` ở mức thuộc tính class `self.db`. Luôn mở và đóng session cục bộ trong từng message handler:
     ```python
     db = SessionLocal()
     try:
         # Thao tác DB
     finally:
         db.close()
     ```
3. **Cơ chế Cooldown Cảnh báo (Debouncing):**
   - Tránh việc còi Buzzer trạm IoT hú inh ỏi liên tục mỗi 5 giây. Đặt biến `COOLDOWN_SECONDS = 180` (3 phút) hoặc `300` (5 phút) để chỉ kích hoạt lại cảnh báo nếu thời tiết tiếp tục xấu sau khoảng thời gian này.
4. **Kiểm tra trước khi Commit (Pre-push check):**
   - Luôn chạy:
     ```bash
     pytest backend/tests/test_api.py
     python integration_tests/test_end_to_end.py
     ```
   - Đảm bảo không commit nhầm file chứa token Telegram hoặc mật khẩu DB.

---
*Tài liệu được biên soạn dành riêng cho Thành viên 1 - Chúc bạn triển khai Backend thành công và đạt kết quả xuất sắc trong đồ án!*


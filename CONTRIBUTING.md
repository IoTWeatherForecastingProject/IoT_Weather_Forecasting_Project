# QUY CHUẨN ĐÓNG GÓP & PHÁT TRIỂN DỰ ÁN (CONTRIBUTING.MD)
## IoT Local Weather Monitoring & Short-Term Forecasting System

> **Dành cho tất cả thành viên trong nhóm dự án (TV1, TV2, TV3).**  
> Mọi dòng mã nguồn, tài liệu và mô hình đóng góp vào repository chung đều phải tuân thủ nghiêm ngặt các quy định dưới đây nhằm đảm bảo tính toàn vẹn, dễ bảo trì và tiến độ đồ án.

---

## 1. Branching Strategy (Chiến lược Phân nhánh Git)

Dự án áp dụng mô hình phân nhánh **Trunk-based Development kết hợp Feature Branching tinh gọn** phù hợp cho nhóm 3 thành viên:

```text
main (Production/Demo - Stable)
  ▲
  │ (Pull Request sau khi test liên thông)
develop (Integration branch)
  ▲
  ├── feature/tv1-firmware-bme280
  ├── feature/tv1-mqtt-ingestion-db
  ├── feature/tv2-temperature-xgboost
  ├── feature/tv2-unified-inference
  ├── feature/tv3-rain-calibration
  ├── feature/tv3-web-scada-dashboard
  └── bugfix/fix-websocket-reconnect
```

### 1.1. Các nhánh chính (Primary Branches)
- `main`: Nhánh ổn định tuyệt đối (Golden branch), chỉ chứa code đã vượt qua toàn bộ các bài test kiểm thử liên thông (Integration Tests) và sẵn sàng cho buổi báo cáo/demo. **Nghiêm cấm commit trực tiếp lên `main`**.
- `develop`: Nhánh tích hợp chung của cả nhóm. Các tính năng mới sau khi hoàn thành sẽ được tạo Pull Request (PR) vào `develop` để chạy test tích hợp.

### 1.2. Quy tắc đặt tên nhánh (Branch Naming Convention)
Tên nhánh bắt buộc sử dụng chữ thường, ngăn cách bằng dấu gạch ngang `-`, theo cú pháp:

```text
<loại-nhánh>/<mã-thành-viên>-<tên-ngắn-tính-năng>
```

| Loại nhánh | Mục đích | Ví dụ |
|---|---|---|
| `feature/` | Phát triển tính năng mới | `feature/tv1-firmware-mqtt-client`<br>`feature/tv2-temperature-models`<br>`feature/tv3-rain-calibration` |
| `bugfix/` | Sửa lỗi trong quá trình tích hợp trên `develop` | `bugfix/tv1-mqtt-reconnect-leak`<br>`bugfix/tv3-chart-timezone-offset` |
| `hotfix/` | Sửa lỗi khẩn cấp trực tiếp trước giờ demo | `hotfix/fix-broker-credentials` |
| `docs/` | Cập nhật tài liệu, báo cáo, slides | `docs/tv2-thesis-chapter-ai`<br>`docs/update-system-architecture` |
| `test/` | Viết bổ sung script kiểm thử chịu lỗi | `test/simulate-sensor-outlier` |

---

## 2. Commit Message Convention (Quy chuẩn Thông điệp Commit)

Dự án áp dụng chuẩn **Conventional Commits 1.0.0** kết hợp với **Mã Task** đã định nghĩa trong `TASK.md` để phục vụ việc truy vết tiến độ:

### 2.1. Cấu trúc Commit Message
```text
<type>(<scope>): <mô tả ngắn gọn bằng thể mệnh lệnh> [MÃ-TASK]

[Body: Giải thích lý do thay đổi, giải pháp kỹ thuật (nếu cần)]

[Footer: Breaking changes hoặc references (nếu có)]
```

### 2.2. Các loại Commit Type hợp lệ
- `feat`: Thêm tính năng mới (ví dụ: endpoint mới, mô hình mới, firmware mới).
- `fix`: Sửa lỗi logic, lỗi runtime, hoặc vá lỗ hổng.
- `refactor`: Tái cấu trúc mã nguồn (không đổi tính năng bên ngoài, tối ưu hiệu năng/clean code).
- `docs`: Thêm hoặc sửa tài liệu, docstrings, báo cáo đồ án.
- `perf`: Cải tiến hiệu năng truy vấn DB, giảm độ trễ WebSocket hoặc suy luận model.
- `test`: Thêm hoặc cập nhật test cases (unit test, mock data, e2e test).
- `chore`: Thay đổi cấu hình build, thêm dependency trong `requirements.txt`, cập nhật `.gitignore`.
- `style`: Định dạng code (khoảng trắng, dấu chấm phẩy, PEP 8 linter).

### 2.3. Ví dụ thực tế theo từng thành viên
- **TV1 (IoT + Backend):**
  - `feat(firmware): add moving average filter for BME280 sensor [IOT-03]`
  - `feat(backend): implement composite index on weather_measurements [BE-02]`
  - `fix(mqtt): resolve memory leak on broker disconnect reconnect loop [IOT-04]`
- **TV2 (Time-Series AI):**
  - `feat(ai): build multi-step XGBoost regressor for +10m/+30m/+60m [ML-03]`
  - `refactor(common): optimize spline interpolation for missing sensor data [ML-01]`
  - `feat(inference): package unified predict_forecast engine for API [ML-06]`
- **TV3 (Analytics + Frontend):**
  - `feat(analytics): implement isotonic regression for rain probability calibration [SA-02]`
  - `feat(dashboard): integrate dual-axis realtime chart with ApexCharts [SA-05]`
  - `fix(anomaly): filter negative atmospheric pressure spikes [SA-03]`

---

## 3. Code Standards & Guidelines (Quy chuẩn Viết Mã Nguồn)

### 3.1. C++ / Arduino Firmware (TV1)
- **Non-blocking Architecture:** Tuyệt đối không dùng hàm `delay()` trong vòng lặp chính `loop()`. Toàn bộ chu kỳ đọc cảm biến, gửi MQTT và nhấp nháy LED phải sử dụng máy trạng thái hữu hạn (FSM) và hàm `millis()`.
- **Khả năng tự phục hồi (Resilience):** Luôn có logic kiểm tra `WiFi.status()` và `mqttClient.connected()`. Nếu mất kết nối, tự động kích hoạt retry theo Exponential Backoff hoặc chu kỳ 5 giây, tránh làm treo vi điều khiển.
- **Hằng số & Cấu hình:** Tất cả chân GPIO, địa chỉ I2C (`0x76`/`0x77`), baudrate (`115200`), chu kỳ đo phải được định nghĩa bằng `#define` hoặc `const` trong thư mục `include/`.
- **Bảo mật:** Không commit mật khẩu WiFi hoặc thông tin đăng nhập MQTT Broker trực tiếp vào code. Sử dụng file `include/config.h.example` làm mẫu và cấu hình trên file nội bộ.

### 3.2. Python Backend & AI Engine (TV1, TV2, TV3)
- **Tuân thủ chuẩn:** Tuân thủ chuẩn **PEP 8**. Sử dụng công cụ `ruff` hoặc `flake8` để kiểm tra định dạng trước khi commit.
- **Type Hinting:** Mọi hàm xử lý dữ liệu và API endpoint bắt buộc phải có Type Annotations rõ ràng:
  ```python
  def predict_forecast(recent_data: pd.DataFrame) -> dict[str, Any]:
      ...
  ```
- **Logging thay vì `print()`:** Tuyệt đối không sử dụng hàm `print()` trong code chạy Backend và Inference. Bắt buộc dùng thư viện chuẩn `logging` với các mức phù hợp: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- **Quản lý Exception:** Bắt ngoại lệ cụ thể (ví dụ: `psycopg2.OperationalError`, `pydantic.ValidationError`), không dùng `except Exception: pass` trơ trọi làm mất vết lỗi.
- **Async/Await cho I/O:** Backend FastAPI phải tận dụng async cho các tác vụ I/O bound (kết nối DB, gọi network, phát WebSocket).

### 3.3. Frontend Dashboard (TV3)
- **Modularity:** Tách biệt rõ ràng giữa tầng hiển thị UI, tầng quản lý trạng thái (State) và tầng kết nối mạng (WebSocket/REST API).
- **WebSocket Reconnect:** Đảm bảo client WebSocket có cơ chế tự động kết nối lại khi Backend khởi động lại hoặc mạng chập chờn.
- **Responsive Design:** Giao diện SCADA phải hiển thị tốt trên cả máy tính bàn (Full HD) và màn hình di động/tablet.

### 3.4. CSDL & Dữ liệu Chuỗi Thời Gian (TV1, TV2)
- **Chuẩn hóa Timestamp:** Timestamp lưu trữ vào PostgreSQL bắt buộc ở dạng chuẩn **UTC ISO-8601** (`timestamptz`). Dashboard phía client sẽ chịu trách nhiệm chuyển sang giờ địa phương (`GMT+7`).
- **Chỉ mục tối ưu:** Mọi truy vấn chuỗi thời gian gần nhất phục vụ Dashboard hoặc Inference phải tận dụng Composite Index `(device_id, timestamp DESC)`.

---

## 4. Local Verification Checklist (Bảng Tự Kiểm tra Trước Khi Push)

Trước khi thực hiện `git push` và mở Pull Request, mỗi thành viên **bắt buộc tự kiểm tra** theo danh sách sau:

```markdown
- [ ] 1. Code chạy không sinh lỗi cú pháp (SyntaxError / Compilation Error).
- [ ] 2. Không chứa thông tin nhạy cảm: WiFi password, MQTT password, Telegram Bot Token, Database secret keys.
- [ ] 3. Không commit file rác, file tạm, cache (__pycache__, .venv, node_modules, .pio, .DS_Store).
- [ ] 4. Đã chạy unit test / integration test cục bộ và tất cả đều PASS.
- [ ] 5. File dữ liệu nặng (>20MB) và model weights không bị đưa vào git commit (đã cấu hình trong .gitignore).
- [ ] 6. Thư mục `personal/` cá nhân không bị commit nhầm tài liệu nháp lên repo chung.
- [ ] 7. Commit message tuân thủ đúng định dạng `type(scope): description [TASK-ID]`.
- [ ] 8. Đã cập nhật tài liệu hoặc README.md tương ứng nếu có thay đổi về tham số hoặc API.
```

---

## 5. Pull Request (PR) & Review Process (Quy trình PR & Xét duyệt)

Để đảm bảo chất lượng hệ thống tích hợp liên thông, toàn bộ mã nguồn hợp nhất vào `develop` và `main` đều phải đi qua quy trình Pull Request:

### 5.1. Quy trình mở Pull Request
1. Đồng bộ code mới nhất từ nhánh `develop` về nhánh tính năng cá nhân:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout feature/tv1-my-feature
   git merge develop
   # Giải quyết conflict (nếu có) tại local trước
   ```
2. Đẩy nhánh lên remote repository:
   ```bash
   git push origin feature/tv1-my-feature
   ```
3. Tạo Pull Request trên giao diện Git (GitHub/GitLab) trỏ từ `feature/tv1-my-feature` vào `develop`.

### 5.2. Mẫu Pull Request Template (PR Template)
Khi mở PR, thành viên sao chép và điền đầy đủ mẫu sau vào phần mô tả PR:

```markdown
## 1. Tóm tắt thay đổi (Summary)
- Mô tả ngắn gọn tính năng hoặc lỗi đã giải quyết.
- Liên quan đến Task: [IOT-03 / ML-02 / SA-01...]

## 2. Loại thay đổi (Type of Change)
- [ ] Tính năng mới (feat)
- [ ] Sửa lỗi (fix)
- [ ] Tái cấu trúc / Tối ưu hiệu năng (refactor / perf)
- [ ] Cập nhật tài liệu (docs)

## 3. Kết quả tự kiểm thử (Verification & Test Results)
- [ ] Đã chạy kiểm thử cục bộ thành công.
- [ ] Đã kiểm tra không có breaking changes ảnh hưởng đến module của thành viên khác.
- Kết quả đo lường (nếu có, ví dụ: MAE = 0.58°C, WebSocket delay < 50ms): ...

## 4. Ảnh chụp màn hình / Logs minh họa (Screenshots / Evidence)
[Đính kèm ảnh chụp Serial Monitor, Swagger UI, Dashboard hoặc đồ thị model]
```

### 5.3. Quy tắc Xét duyệt & Merge (Peer Review Policy)
- **Ít nhất 1 thành viên khác duyệt (Approve):**
  - Nếu TV1 tạo PR Backend liên quan đến API format, TV2 hoặc TV3 phải là người review và xác nhận format tương thích.
  - Nếu TV2 tạo PR Inference Engine, TV1 phải duyệt để đảm bảo hàm suy luận cắm vào FastAPI không bị lỗi import.
  - Nếu TV3 tạo PR Dashboard, TV1 duyệt phần kết nối WebSocket.
- **Chiến lược Merge:** Sử dụng **Squash and Merge** hoặc **Rebase and Merge** để giữ cho lịch sử commit trên nhánh `develop` và `main` luôn gọn gàng, tuyến tính.
- **Xóa nhánh sau khi merge:** Nhánh tính năng (`feature/*`) sau khi đã merge thành công vào `develop` cần được xóa bỏ trên remote để tránh gây rối repository.

---

## 6. Tiêu chí Hoàn thành (Definition of Done - DoD)

Một nhiệm vụ kỹ thuật được xem là `ĐÃ HOÀN THÀNH` khi và chỉ khi:
1. Đạt chỉ số kỹ thuật đề ra trong `TASK.md`.
2. Vượt qua bài kiểm tra độc lập và kiểm tra ghép nối (Integration Test).
3. Đã tạo PR, được ít nhất 1 thành viên review và merge vào `develop`.
4. Có tài liệu cập nhật tại `README.md` của module và ghi chép số liệu sẵn sàng cho Báo cáo Đồ án.


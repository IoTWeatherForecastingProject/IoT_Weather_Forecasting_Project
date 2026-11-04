# Kế hoạch và kết quả xử lý tích hợp — 04/11/2026

Nhánh thực hiện: `feature/tv1-iot-backend`, bắt đầu sau merge `e2d2c3a` từ `origin/develop` (`9567f3e`). Phạm vi là các lỗi tích hợp đã xác nhận trong review toàn dự án, cùng các trở ngại được phát hiện khi chạy luồng thực. Không huấn luyện lại model hoặc đưa chỉnh sửa phần cứng đang làm dở vào các commit này.

## Các bước đã hoàn thành

1. **Chuẩn bị runtime model — `13e8009`.** Nạp package `ml` theo nhu cầu; giữ public exports; tách thư viện inference khỏi PyTorch/công cụ huấn luyện. Runtime khớp artifacts hiện có (`scikit-learn==1.9.1`, `xgboost==3.4.1`, Python ≥3.12). Docker build từ gốc repository, mang đủ mã/weights và có lựa chọn `INSTALL_INFERENCE=true`.
2. **Nối dự báo nhiệt độ và mưa — `1fb275c`.** Backend gọi engine TV2 đã bàn giao và hàm rain-only của TV3; bỏ đường model nhiệt độ cũ. Tăng truy vấn từ 76 lên 120 phút để đáp ứng yêu cầu 90 phút thực. Giữ kiểm tra thời gian/coverage của TV2; công bố nguồn từng horizon và lý do fallback. Phân biệt thiếu một model với thiếu cả ba, và giữ mưa hợp lệ khi nhiệt độ dùng persistence. Khóa suy luận nhiệt độ giữa HTTP và monitor để bảo vệ diagnostics dùng chung.
3. **Sửa dữ liệu và cảnh báo Dashboard — `e9d7c53`.** Dashboard chọn `open-meteo-15min`, API chấp nhận nguồn này và vẫn tương thích mặc định lịch sử `open-meteo`. Banner dùng ngưỡng trong response forecast; mô tả quyết định xác suất thay vì khẳng định còi đã chạy.
4. **Kiểm thử luồng thực — `3299e10`.** E2E có hai chế độ: TV1 độc lập với import guard, và `--integrated-models` với model/phân tích thật. Mỗi lượt dùng DB, MQTT namespace, backend và ngưỡng riêng; tắt Telegram. Kiểm tra thêm trình duyệt, ngưỡng trong banner và kết nối lại WebSocket.
5. **Sửa phụ thuộc khi cài mới — `ad0229b`.** Bổ sung psycopg 3 cho URL `postgresql://` trên SQLAlchemy 2.1, đồng thời giữ psycopg2 cho cấu hình dùng driver tường minh. Test dùng model được bỏ qua có lý do nếu môi trường chỉ cài backend độc lập.
6. **Cập nhật hướng dẫn và hợp đồng.** Backend README, hướng dẫn E2E, data contract, schema provider và tài liệu bàn giao phản ánh cửa sổ 120 phút, metadata nguồn dự báo và cách bật runtime tích hợp.

## Kết quả kiểm chứng

- Backend trong DB PostgreSQL tạm, chế độ tích hợp: **155/155 test đạt**. Chế độ độc lập: **142 test đạt, 13 test tích hợp được loại theo marker**.
- E2E độc lập: **9 bước đạt**; E2E tích hợp: **11 bước đạt**. Đã kiểm tra MQTT → commit DB → REST/WebSocket, loại bản tin lặp/sai, cảnh báo nền trước khi gọi forecast, PUBACK, cooldown, đổi ngưỡng, phân tích TV3 và nguồn tham chiếu live.
- API thật dùng XGBoost ở cả ba horizon, `temperature_confidence=normal`, không fallback. Regression còn bao gồm dữ liệu 5 giây, lịch sử quá ngắn, gián đoạn dài, thiếu riêng model +10/+30 phút và thiếu cả ba.
- AI engine: **115/115 test đạt**. ML: **274/274 check đạt** (45 preprocessing, 56 benchmark, 52 deep learning, 121 error/inference). Script ML chạy trong bản sao để không ghi đè artifacts đang theo dõi.
- Edge desktop 1366×900 và mobile 390 px: không lỗi API/JavaScript, không tràn ngang; WebSocket reconnect và ghi ngưỡng đạt. Cố tình đặt ngưỡng trong state trình duyệt thành 1% vẫn hiển thị 70% từ response forecast.
- Image Docker Python 3.12 build thành công; **155/155 test backend và 11 bước E2E tích hợp cũng đạt ngay trong image Linux**, gồm DB/MQTT và ba model XGBoost. Bản cài mới dùng SQLAlchemy 2.1.8, psycopg 3.3.8, pandas 3.1.0 và chọn đúng driver cho URL `postgresql://`. Đường suy luận không nạp PyTorch/plotting. Kiểm tra cú pháp JS, lỗi Python tĩnh và whitespace đạt.

Các báo cáo được giữ ngoài repository trong thư mục phiên làm việc `project-review-20261104`: `e2e-independent-fix/`, `e2e-integrated-fix/`, `e2e-browser-fix/`, `linux-image-e2e/`, `docker-model-smoke.log`, `ai-fix-tests.log` và `ml-fix-test_*.log`. Fixture là dữ liệu tổng hợp; kết quả này xác nhận tích hợp phần mềm, không đo chất lượng dự báo khí tượng. Các DB, backend và MQTT namespace của E2E đã được dọn. Đối chiếu SHA-256 xác nhận 16 file chỉnh sửa có sẵn của người dùng giữ nguyên; weights đang theo dõi không đổi.

## Cách sử dụng sau thay đổi

Cài `backend/requirements.txt` và `backend/requirements-inference.txt` trong cùng môi trường Python ≥3.12. Đặt `FORECAST_ENGINE_MODE=auto`, `ANALYTICS_ENGINE_MODE=auto` trong cấu hình chạy để dùng các provider đã tích hợp. Mặc định vẫn là `heuristic`/`disabled` cho chế độ TV1 độc lập. Chạy E2E theo [hướng dẫn](../../integration_tests/README.md) trước khi triển khai.

Checkout hiện chưa có artifact mưa đã hiệu chuẩn nên xác suất mưa vẫn ghi nguồn `heuristic`. Nghiệm thu phần cứng, gửi Telegram thật và đánh giá độ chính xác trên dữ liệu thực là các công việc cần bằng chứng riêng. Các thay đổi chưa commit có sẵn của người dùng được giữ nguyên; các commit trên chưa được push.

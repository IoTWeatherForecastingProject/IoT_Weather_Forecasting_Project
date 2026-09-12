# MODULE 5: TECHNICAL DOCUMENTATION & THESIS REPORTS
## Tài Liệu Kiến Trúc Kỹ Thuật, Kịch Bản Demo & Báo Cáo Đồ Án

> **Phụ trách:** 👥 **Cả 3 thành viên làm chung**  
> **Các Task liên quan:** `SYS-04`, `SYS-05` (Xem chi tiết tại [TASK.md](../TASK.md)).

---

## 1. Cấu trúc Thư mục Tài liệu

```text
docs/
├── README.md                           # Tài liệu tổng thể và phân công viết báo cáo
├── architecture/
│   └── system_architecture.md          # Chi tiết thiết kế kiến trúc hệ thống, sơ đồ tuần tự & CSDL
├── demo_scenarios/
│   └── scenarios.md                    # Chi tiết các bước thực hiện 3 kịch bản Demo nghiệm thu
└── reports/
    └── .gitkeep                        # Thư mục chứa bản thảo Báo cáo Đồ án (.docx/.pdf) và Slide (.pptx)
```

---

## 2. Phân công Biên soạn Báo cáo Đồ án Tốt nghiệp / Môn học

Theo đúng phân công trong `TASK.md`, nội dung cuốn Báo cáo kỹ thuật được chia thành các chương chuyên trách:

| Thành viên phụ trách | Chương / Phần báo cáo đảm nhiệm | Nội dung trọng tâm |
|---|---|---|
| **Cả 3 thành viên** | **Chương 1: Mở đầu & Tổng quan đề tài** | Đặt vấn đề, mục tiêu, phạm vi dự án (short-term local forecasting), khảo sát các giải pháp hiện nay. |
| **TV1 (IoT + Backend)** | **Chương 2: Thiết kế Phần cứng IoT & Firmware** | Sơ đồ nguyên lý mạch, cảm biến BME280, Rain Sensor, vi điều khiển ESP8266/ESP32, bộ lọc Moving Average, giao thức MQTT (QoS 0 vs 1). |
| **TV1 (IoT + Backend)** | **Chương 3: Hạ tầng Backend & CSDL Time-Series** | Kiến trúc Data Ingestion Worker, thiết kế CSDL PostgreSQL/TimescaleDB, tối ưu Composite Index, REST API, WebSocket và Vòng lặp phản hồi 2 chiều. |
| **TV2 (Time-Series AI)** | **Chương 4: Nền tảng Chuỗi thời gian & Mô hình Dự báo Nhiệt độ** | Tiền xử lý dữ liệu (Resampling, Imputation, Outlier, ADF test), Feature Engineering (lags, rolling stats), Mô hình hồi quy nhiệt độ đa bước (+10m, +30m, +60m), Model Benchmark (Linear, RF, XGBoost) và Thực nghiệm Deep Learning (LSTM/GRU). |
| **TV3 (AI + Analytics + FE)** | **Chương 5: Dự báo Xác suất Mưa & Phân tích Dị thường Cảm biến** | Xử lý mất cân bằng dữ liệu, trích xuất đặc trưng tụt áp/tăng ẩm, Mô hình phân loại mưa và Kỹ thuật Hiệu chuẩn Xác suất (Platt/Isotonic, Brier Score), Thuật toán phát hiện lỗi/trôi cảm biến và Đối chuẩn OpenWeatherMap. |
| **TV3 (AI + Analytics + FE)** | **Chương 6: Phát triển Giao diện Giám sát SCADA** | Thiết kế giao diện Web thời gian thực, trực quan hóa biểu đồ ApexCharts đối chuẩn, hiển thị khung dự báo và form điều khiển 2 chiều. |
| **Cả 3 thành viên** | **Chương 7: Tích hợp Toàn chuỗi, Thực nghiệm & Đánh giá Demo** | Bảng kết quả đo đạc độ trễ toàn chuỗi, độ chính xác mô hình ngoài trời, nghiệm thu 3 kịch bản demo và kiểm thử chịu lỗi. |
| **Cả 3 thành viên** | **Chương 8: Kết luận & Hướng phát triển** | Tổng kết kết quả đạt được, bài học kinh nghiệm, các hạn chế và đề xuất mở rộng (Edge AI, trạm năng lượng mặt trời). |

---

## 3. Quy chuẩn Định dạng Tài liệu & Báo cáo
- Font chữ: Times New Roman, cỡ 13pt, giãn dòng 1.3 - 1.5.
- Hình ảnh và Biểu đồ: Tất cả hình chụp linh kiện, sơ đồ mạch, giao diện Dashboard và đồ thị training phải có chú thích rõ ràng (`Hình X.Y: ...`).
- Trích dẫn tài liệu tham khảo: Theo chuẩn IEEE.
- Đồ thị đối chuẩn (Benchmark Charts): Lưu trữ dưới định dạng `.png` độ phân giải cao tại `docs/reports/figures/`.


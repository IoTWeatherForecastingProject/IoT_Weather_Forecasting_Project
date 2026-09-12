# THƯ MỤC LÀM VIỆC CÁ NHÂN (PERSONAL WORKSPACE)

> **LƯU Ý QUAN TRỌNG:**  
> Toàn bộ nội dung bên trong thư mục này đã được cấu hình trong `.gitignore` ngoại trừ tệp `README.md` này và các tệp `.gitkeep`.  
> Điều này cho phép từng thành viên lưu trữ tài liệu nháp, ghi chú học tập, số liệu thử nghiệm cá nhân mà **KHÔNG SỢ LÀM BẨN REPOSITORY HOẶC GÂY MERGE CONFLICTS**.

---

## 1. Phân bổ thư mục cá nhân

- `personal/tv1/`: Không gian làm việc riêng của **Thành viên 1 (IoT + Backend Engineer)**.
- `personal/tv2/`: Không gian làm việc riêng của **Thành viên 2 (Time-Series AI Engineer)**.
- `personal/tv3/`: Không gian làm việc riêng của **Thành viên 3 (AI + Analytics + Frontend Engineer)**.

---

## 2. Những tài liệu NÊN để trong `personal/`

1. **Ghi chú & Nhật ký phát triển cá nhân:**
   - Scratchpad, TODO list hàng ngày, cheat-sheet cú pháp.
   - Các lệnh kiểm tra tạm thời, ghi chú debug phần cứng ESP.
2. **Tài liệu tham khảo chuyên sâu:**
   - Datasheet cảm biến BME280, Rain Sensor v.v.
   - Các bài báo khoa học (Papers), liên kết hướng dẫn kỹ thuật phục vụ nghiên cứu riêng.
3. **Mã nguồn thử nghiệm tạm (Scratch Scripts):**
   - Các đoạn script Python một lần để vẽ thử biểu đồ, test kết nối API riêng.
   - File log debug, test payload JSON tạm thời.
4. **Bản nháp nội dung báo cáo đồ án:**
   - Draft viết đoạn văn phân tích trước khi tổng hợp vào thư mục chính `docs/reports/`.

---

## 3. Những thứ KHÔNG ĐƯỢC để trong `personal/`

1. **Mã nguồn chính thức của hệ thống:**
   - Code Firmware ESP phải đặt trong `firmware/`.
   - Code Ingestion, API phải đặt trong `backend/`.
   - Code Tiền xử lý, Huấn luyện, Inference phải đặt trong `ai_engine/`.
   - Code Giao diện Web phải đặt trong `dashboard/`.
2. **Thông tin nhạy cảm bí mật:**
   - Tuyệt đối không lưu mật khẩu ngân hàng, private key tài khoản cá nhân.
3. **Tài liệu cần chia sẻ cho cả nhóm:**
   - Nếu tài liệu có giá trị cho cả nhóm hoặc phục vụ tích hợp liên thông, hãy di chuyển vào `docs/` để được lưu vết trên Git!


# SYS-02 — Kết quả kiểm thử chịu lỗi cảm biến

Thời gian chạy (UTC): 2026-11-02T04:57:34.396470+00:00

Ghi chú: dữ liệu tổng hợp từ simulator; không phải kết quả đo phần cứng thật.
Thời gian phát hiện tính từ trước kết nối/publish đến lúc API có đủ mẫu; poll sau publish tối đa 30 giây.

| Kịch bản | Dữ liệu | Kỳ vọng | Thực tế | PASS/FAIL | Thời gian |
|---|---|---|---|---|---|
| normal | 40 phut binh thuong | OK, khong anomaly | OK; anomalies=none; frozen=none; rain_drift=False; n_records=241 | PASS | 3.61 s |
| spike | 10 phut binh thuong + 62 C / 880 hPa | FAULT, OUT_OF_RANGE | FAULT; anomalies=OUT_OF_RANGE,SPIKE; frozen=none; rain_drift=False; n_records=62 | PASS | 0.41 s |
| frozen | 35 phut BME280 giu nguyen gia tri | WARNING, frozen temperature/pressure | WARNING; anomalies=FROZEN_VALUE; frozen=temperature,humidity,pressure; rain_drift=False; n_records=211 | PASS | 1.31 s |
| stuck-wet | 370 phut mua ket uot, do am kho | WARNING, rain_drift=true | WARNING; anomalies=WATER_STAGNATION_DRIFT; frozen=none; rain_drift=True; n_records=2221 | PASS | 15.62 s |
| unplugged | 5 phut binh thuong + BME280 null | FAULT, OUT_OF_RANGE | FAULT; anomalies=OUT_OF_RANGE,SPIKE; frozen=none; rain_drift=False; n_records=32 | PASS | 0.23 s |
| offline | 30 phut binh thuong, dung tu 20 phut truoc | FAULT, STALE_DATA | FAULT; anomalies=STALE_DATA; frozen=none; rain_drift=False; n_records=181 | PASS | 1.12 s |

Mã trạm riêng cho lần chạy:

- `sys02-normal-1793595454396470700`
- `sys02-spike-1793595454396470700`
- `sys02-frozen-1793595454396470700`
- `sys02-stuck-wet-1793595454396470700`
- `sys02-unplugged-1793595454396470700`
- `sys02-offline-1793595454396470700`

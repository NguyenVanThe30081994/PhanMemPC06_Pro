# Định hướng refactor báo cáo không phụ thuộc LibreOffice

## Mục tiêu

Xây lại chức năng báo cáo theo hướng:

- Đơn vị nhập trực tiếp trên phần mềm.
- Excel chỉ là nguồn quét cấu trúc và file xuất.
- Màn xem báo cáo trong phần mềm render từ DB + metadata.
- Không phụ thuộc LibreOffice trên host.

## Giữ lại

- Upload biểu mẫu Excel.
- Scanner cấu trúc và màn chỉnh cấu trúc header.
- Thiết lập trường nhập/ẩn/khóa.
- Cơ chế tự xác định mốc báo cáo hiện tại theo ngày/tháng/quý/6 tháng/năm.
- Xuất Excel từ biểu mẫu gốc.

## Giảm phụ thuộc

- Không dùng workbook Excel làm luồng xem chính trên web.
- Không coi công thức Excel là engine tính toán mặc định của server.
- Chỉ dùng xem theo workbook khi gọi rõ `layout=excel`.

## Công thức nội bộ

Hiện hỗ trợ bước đầu:

- Tham chiếu cột cùng hàng.
- Phép cộng, trừ, nhân, chia.
- `SUM(...)`
- `ROUND(...)`
- `MIN(...)`
- `MAX(...)`
- `ABS(...)`
- `IFERROR(a/b, "")` hoặc `IFERROR(a/b, 0)` qua `safe_div(a, b)`

Những công thức ngoài tập này cần:

1. bổ sung translator từ Excel sang biểu thức nội bộ;
2. hoặc đánh dấu là chỉ bảo đảm đầy đủ khi xuất file Excel.

## Lộ trình tiếp theo

1. Thêm màn hình quản trị hiển thị rõ công thức nào đã dịch được, công thức nào chưa.
2. Thêm renderer web-native dạng bảng nhiều cột cho các biểu mẫu có nhóm chỉ tiêu lớn.
3. Bổ sung translator cho các công thức định dạng phổ biến hơn.
4. Tách dần nhánh `report_submission_service` nếu không còn dùng luồng nộp Excel.

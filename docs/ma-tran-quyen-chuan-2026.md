# Ma Trận Quyền Chuẩn 2026

Ngày cập nhật: `16/05/2026`

## 1. Nguyên tắc chung

Mọi module trong hệ thống nên quy về 3 lớp quyền:

- `Xem`
- `Xử lý`
- `Thực hiện`

Ý nghĩa chuẩn:

- `Xem`
  - vào được module
  - xem danh sách
  - xem chi tiết
  - xem tiến độ, thống kê, lịch sử

- `Xử lý`
  - cấu hình
  - tạo/sửa/xóa
  - điều phối
  - giao việc
  - duyệt/kiểm tra
  - xuất dữ liệu

- `Thực hiện`
  - nhập nội dung
  - gửi kết quả
  - cập nhật kết quả của chính mình
  - tải minh chứng của chính mình

Quy tắc hiển thị:

- Có `Xem` mới thấy module.
- Có `Xử lý` mới thấy nút cấu hình/quản trị.
- Có `Thực hiện` mới thấy thao tác nộp/gửi/cập nhật đầu việc.

## 2. Mặc định theo vai trò

Mặc định khi tạo vai trò mới:

- `Lãnh đạo`, `Chỉ huy PC06`: `Xem`
- `Cán bộ PC06`: `Xử lý`
- Các vai trò khác: `Thực hiện`

Ghi chú:

- Đây là mặc định khởi tạo.
- Quản trị vẫn được phép điều chỉnh từng module riêng.
- Mặc định tự động chỉ nên áp dụng cho nhóm module vận hành chung như `Tổng quan`, `Công việc`, `Bảng tin`, `Thư viện`, `Danh bạ`, `Nhập báo cáo`, `Tiến độ`.
- Các module quản trị như `Quản lý báo cáo`, `Tài khoản`, `Hệ thống` không nên tự cấp hàng loạt cho vai trò mới.

## 3. Ma trận theo module

## 3.1 Tổng quan

Mã quyền:

- `p_dash_view`
- `p_dash_process`
- `p_dash_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem dashboard
  - xem các chỉ số tổng hợp

- `Xử lý`
  - cấu hình widget nếu sau này có
  - chọn bộ lọc quản trị dùng chung nếu sau này có

- `Thực hiện`
  - hiện chưa cần dùng mạnh
  - để mở rộng nếu dashboard có các checklist hành động cá nhân

## 3.2 Công việc

Mã quyền:

- `p_task_view`
- `p_task_process`
- `p_task_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem danh sách task
  - xem chi tiết task
  - xem tiến độ
  - xem task con
  - xem báo cáo tổng hợp

- `Xử lý`
  - tạo task
  - sửa task
  - xóa task
  - giao việc
  - cấu hình `xem việc`
  - tạo task con
  - cấu hình kiểu báo cáo của task con
  - xuất thống kê

- `Thực hiện`
  - tiếp nhận task
  - báo cáo lời
  - báo cáo số
  - tải minh chứng của mình
  - phản hồi theo đầu việc được giao

## 3.3 Bảng tin

Mã quyền:

- `p_news_view`
- `p_news_process`
- `p_news_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem danh sách bản tin
  - xem chi tiết bản tin
  - tải file đính kèm

- `Xử lý`
  - đăng tin
  - sửa tin
  - gỡ tin

- `Thực hiện`
  - hiện tại chưa bắt buộc
  - có thể dùng sau này nếu cần cơ chế cộng tác soạn thảo

## 3.4 Thư viện

Mã quyền:

- `p_lib_view`
- `p_lib_process`
- `p_lib_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem thư viện
  - tải tài liệu

- `Xử lý`
  - tải tài liệu lên
  - sửa metadata
  - xóa tài liệu

- `Thực hiện`
  - chưa cần tách riêng ở giai đoạn hiện tại

## 3.5 Danh bạ

Mã quyền:

- `p_contact_view`
- `p_contact_process`
- `p_contact_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem danh bạ
  - tìm kiếm, lọc

- `Xử lý`
  - thêm liên hệ
  - sửa liên hệ
  - xóa liên hệ
  - nhập Excel
  - quản lý nhóm danh bạ

- `Thực hiện`
  - hiện chưa cần tách thành luồng riêng

## 3.6 Báo cáo

Mã quyền khuyến nghị đích:

- `p_form_view`
- `p_form_process`
- `p_input_view`
- `p_input_exec`
- `p_stat_view`
- `p_stat_process`

Tương thích cũ đang tồn tại:

- `p_form_lead`
- `p_input_lead`
- `p_input_exec`
- `p_stat_lead`
- `p_stat_exec`

Quyền nghiệp vụ:

- `Biểu mẫu`
  - `Xem`: xem danh sách biểu mẫu, cấu hình hiện có
  - `Xử lý`: tạo/sửa/xóa biểu mẫu, quản lý version

- `Nhập báo cáo`
  - `Xem`: xem danh sách báo cáo được giao
  - `Thực hiện`: nhập và gửi báo cáo

- `Thống kê`
  - `Xem`: xem tiến độ, theo dõi tình trạng nộp
  - `Xử lý`: đóng/mở chu kỳ, reset, xuất tổng hợp, điều phối

## 3.7 Tài khoản và vai trò

Mã quyền:

- `p_user_view`
- `p_user_process`

Tương thích cũ:

- `p_user_lead`

Quyền nghiệp vụ:

- `Xem`
  - vào được màn vai trò
  - xem danh sách vai trò
  - xem danh sách tài khoản

- `Xử lý`
  - tạo vai trò
  - sửa quyền
  - tạo tài khoản
  - sửa tài khoản
  - nhập Excel
  - reset mật khẩu

## 3.8 Hệ thống

Mã quyền:

- `p_sys_view`
- `p_sys_process`

Tương thích cũ:

- `p_sys_lead`
- `p_sys_exec`

Quyền nghiệp vụ:

- `Xem`
  - xem các màn cấu hình hệ thống

- `Xử lý`
  - cập nhật danh mục
  - cập nhật AI settings
  - các cấu hình hạ tầng trong hệ thống

## 4. Bảng vai trò mẫu

## 4.1 Lãnh đạo

Khuyến nghị:

- `task`: `Xem`
- `report`: `Xem`
- `news`: `Xem`
- `library`: `Xem`
- `contacts`: `Xem`
- `user`: tùy tổ chức
- `sys`: không mặc định

## 4.2 Chỉ huy PC06

Khuyến nghị:

- `task`: `Xem`
- `report`: `Xem`
- `news`: `Xem`
- `library`: `Xem`
- `contacts`: `Xem`
- `user`: tùy tổ chức
- `sys`: không mặc định

## 4.3 Cán bộ PC06

Khuyến nghị:

- `task`: `Xử lý`
- `report`: `Xử lý`
- `news`: `Xử lý` nếu được giao biên tập
- `library`: `Xử lý` nếu được giao quản lý tài liệu
- `contacts`: `Xử lý`

## 4.4 Vai trò đơn vị thực hiện

Khuyến nghị:

- `task`: `Thực hiện`
- `report`: `Thực hiện`
- `news`: không mặc định
- `library`: `Xem`
- `contacts`: `Xem`

## 5. Quy tắc ánh xạ tương thích

Trong giai đoạn chuyển tiếp:

- `p_module` cũ
  - hiểu là quyền đầy đủ: `view + process + exec`

- `p_module_lead`
  - hiểu là `process`

- `p_module_exec`
  - hiểu là `exec`

Hệ thống có thể tự suy diễn:

- `process` bao hàm khả năng `xem`
- `exec` bao hàm khả năng `xem`

Nhưng ở giao diện cấu hình vai trò, chỉ hiển thị 3 quyền chuẩn để quản trị không bị rối.

## 6. Tiêu chí hoàn tất phần phân quyền

Phần phân quyền được coi là đạt khi:

- mọi menu đều dùng quyền chuẩn
- mọi route chính đều xác định được là `xem`, `xử lý` hay `thực hiện`
- vai trò mới không cần biết `lead/exec` vẫn dùng được bình thường
- vai trò cũ không bị mất quyền sau migration
- tài liệu vận hành mô tả rõ ý nghĩa từng quyền

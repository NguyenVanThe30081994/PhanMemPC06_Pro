# Đề Án Cải Tổ Kiến Trúc Hệ Thống PC06

Ngày cập nhật: `16/05/2026`

## Tài liệu đi kèm

- Ma trận quyền chi tiết: [ma-tran-quyen-chuan-2026.md](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/docs/ma-tran-quyen-chuan-2026.md)
- Lộ trình triển khai và nghiệm thu: [lo-trinh-trien-khai-de-an-2026.md](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/docs/lo-trinh-trien-khai-de-an-2026.md)

## 1. Mục tiêu

Chuẩn hóa hệ thống theo tư duy của một phần mềm nghiệp vụ hiện đại:

- Quyền hạn rõ ràng, thống nhất trên toàn hệ thống.
- Luồng thao tác tách bạch: `xem`, `điều phối/xử lý`, `thực hiện`.
- `Task` là nơi điều hành công việc.
- `Report` là nơi thu thập biểu mẫu/số liệu.
- `Task` và `Report` có thể liên kết, nhưng không chồng lấn trách nhiệm.
- Giao diện theo vai trò, không hiển thị dư thao tác.
- Cho phép mở rộng lâu dài mà không phải tiếp tục vá từng chức năng.

## 2. Hiện trạng

### 2.1 Điểm tốt hiện có

- Hệ thống đã có nền tảng phân vai trò, tài khoản, task, report, danh mục dùng chung.
- `Task con`, `xem việc`, `báo cáo số`, `báo cáo lời`, `liên kết biểu mẫu report` đã có hạt nhân triển khai.
- Giao diện quản trị và luồng task đã được cải thiện đáng kể so với trước.

### 2.2 Điểm đang lệch kiến trúc

- Quyền đang pha trộn giữa `lead/exec`, quyền cũ `p_module`, và các hành vi đặc thù theo module.
- `Task` đang gánh quá nhiều vai trò:
  - giao việc
  - theo dõi
  - báo cáo lời
  - báo cáo số
  - liên kết report
  - thảo luận
- `TaskAssignment` đang vừa đóng vai trò phân công, vừa là nơi chứa kết quả báo cáo.
- `viewer_scope_json`, `assignment_scope_json`, `report_schema_json`, `linked_report_templates_json` là cách mở rộng nhanh, nhưng về dài hạn sẽ khó bảo trì.
- Điều hướng và quyền truy cập hiện dựa nhiều vào suy luận trong code, chưa có một mô hình quyền chuẩn duy nhất.

### 2.3 Dấu hiệu kỹ thuật cho thấy cần cải tổ

- Mô hình dữ liệu `Task` hiện rất nặng và kiêm nhiều ý nghĩa tại [models.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/models.py:147).
- Quyền đang được nạp và chuẩn hóa ở nhiều nơi: [app.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/app.py:263), [routes/tasks.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/tasks.py:190), [routes/reporting.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/reporting.py:170), [routes/portal.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/portal.py:105), [routes/admin.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/admin.py:217).
- Trang vai trò hiện là nơi gần nhất để tái chuẩn hóa quyền theo 3 lớp mới.

## 3. Kiến trúc đích

### 3.1 Trục 1: Quyền

Chuẩn chung cho mọi chức năng:

- `Xem`: được nhìn thấy module, danh sách, chi tiết, tiến độ, kết quả.
- `Xử lý`: được điều phối, giao việc, cập nhật cấu hình, theo dõi, nhắc việc, kiểm tra.
- `Thực hiện`: được nhập liệu, gửi kết quả, phản hồi, tải minh chứng của chính mình.

Quy tắc kế thừa:

- `Thực hiện` không đồng nghĩa với `Xử lý`.
- `Xử lý` không mặc định là `Thực hiện`.
- Khi cần, hệ thống có thể suy diễn quyền hiển thị:
  - `Xử lý` luôn có `Xem`
  - `Thực hiện` luôn có `Xem`
- Nhưng ở giao diện phân quyền, 3 quyền vẫn phải được thể hiện tách bạch để quản trị hiểu rõ ý nghĩa.

### 3.2 Trục 2: Vai trò và tài khoản

- `Vai trò`: bộ quyền mẫu.
- `Tài khoản`: người dùng cụ thể.
- `Vai trò` không đại diện cho phân công công việc.
- `Phân công` là dữ liệu nghiệp vụ riêng, không trộn với định nghĩa vai trò.

Mặc định theo vai trò:

- `Lãnh đạo`, `Chỉ huy PC06`: mặc định `Xem`
- `Cán bộ PC06`: mặc định `Xử lý`
- Các vai trò khác: mặc định `Thực hiện`

Lưu ý:

- Đây là mặc định tạo mới để tăng tốc cấu hình.
- Quản trị vẫn có thể chỉnh tay cho từng vai trò khi cần ngoại lệ.

### 3.3 Trục 3: Công việc

Chuẩn hóa mô hình:

- `Task` cha: việc tổng, đích quản trị, giao ban, theo dõi tiến độ.
- `Task item` hoặc `Task con`: đầu mục nhỏ nhất để thực hiện.
- `Participant`: người tham gia theo vai trò nghiệp vụ cụ thể.
- `Watcher`: người chỉ xem, không thực hiện.

Một `task con` phải có:

- tiêu đề
- loại báo cáo: `lời` hoặc `số`
- có/không bắt buộc file
- người thực hiện hoặc nhóm thực hiện
- trạng thái

Không nên để `task con` vừa là một card độc lập ngoài danh sách, vừa là một phần của task cha, trừ khi chủ đích sản phẩm yêu cầu.

Khuyến nghị:

- Danh sách công việc chính hiển thị `task cha`.
- `task con` hiển thị trong chi tiết `task cha`.
- Người thực hiện đi vào `task cha` để thao tác trên từng `task con`.

### 3.4 Trục 4: Báo cáo

Chuẩn hóa phân tách:

- `Task`: điều hành công việc.
- `Report`: thu thập biểu mẫu và số liệu chuẩn hóa.

Ba kiểu liên kết nghiệp vụ:

1. `Task độc lập`
- Người dùng báo cáo trực tiếp trong task.

2. `Task có task con`
- Người dùng báo cáo ở từng đầu mục.

3. `Task liên kết report template`
- Người dùng nhập ở module report.
- Hệ thống tự đồng bộ kết quả tổng hợp về task.

Quy tắc quan trọng:

- Một đầu việc chỉ nên có một nguồn sự thật chính.
- Nếu đã liên kết `report template`, không nên cho nhập số liệu song song trực tiếp trong task.

### 3.5 Trục 5: Điều hướng

Theo loại người dùng:

- Người `xem`: thấy dashboard, danh sách, chi tiết, tiến độ, thống kê.
- Người `xử lý`: thấy cấu hình, giao việc, phân công, theo dõi, nhắc việc, xuất báo cáo.
- Người `thực hiện`: thấy việc của mình, thao tác cần làm, lịch sử đã nộp.

Mọi module nên có cùng nguyên tắc:

- Không có quyền thì không hiện menu.
- Có quyền `xem` thì hiện module nhưng không hiện nút sửa/giao/xóa.
- Có quyền `xử lý` thì hiện thao tác quản trị module.
- Có quyền `thực hiện` thì hiện thao tác nhập/gửi kết quả.

## 4. Mô hình dữ liệu đích

### 4.1 Quyền

Giữ ngắn hạn:

- tiếp tục lưu JSON trong `AppRole.perms`

Đích dài hạn:

- `permission_definition`
- `role_permission`
- `user_role_assignment` nếu sau này cần nhiều vai trò cho một tài khoản

### 4.2 Công việc

Khuyến nghị đích:

- `task`
  - metadata chung
  - trạng thái tổng
  - loại luồng công việc
- `task_item`
  - đầu mục con
  - loại báo cáo
  - yêu cầu file
  - deadline kế thừa/ghi đè
- `task_participant`
  - `task_id` hoặc `task_item_id`
  - `user_id`
  - `participation_type`: `watcher`, `manager`, `executor`
- `task_submission`
  - kết quả nộp
  - nội dung
  - giá trị số
  - file
  - submitted_at

### 4.3 Báo cáo

- `report_template`
- `report_cycle`
- `report_submission`
- `task_report_link`
  - liên kết task hoặc task item với template/cycle/report type

## 5. Ma trận quyền chuẩn

### 5.1 Công việc

- `p_task_view`
  - xem danh sách công việc
  - xem chi tiết
  - xem tiến độ
  - xem task con

- `p_task_process`
  - tạo task
  - sửa task
  - giao việc
  - thêm người xem
  - tạo task con
  - xóa task
  - xuất thống kê

- `p_task_exec`
  - tiếp nhận việc
  - gửi báo cáo
  - cập nhật báo cáo của mình
  - tải minh chứng của mình

### 5.2 Báo cáo

- `p_form_view`
  - xem danh sách biểu mẫu
  - xem trạng thái báo cáo

- `p_form_process`
  - quản lý biểu mẫu
  - tạo chu kỳ
  - cấu hình phạm vi
  - đóng/mở báo cáo

- `p_input_exec`
  - nhập và gửi báo cáo

- `p_stat_view`
  - xem tiến độ, thống kê, tổng hợp

Ghi chú:

- Module report đang có lịch sử `form/input/stat`, nên giai đoạn đầu sẽ cần giữ tương thích, sau đó mới hợp nhất tên quyền nếu cần.

### 5.3 Bảng tin, thư viện, danh bạ, hệ thống

Áp cùng khuôn:

- `p_news_view / process / exec`
- `p_lib_view / process / exec`
- `p_contact_view / process / exec`
- `p_user_view / process`
- `p_sys_view / process`

Không nhất thiết mọi module đều dùng đủ 3 quyền ở UI, nhưng mô hình dữ liệu nên thống nhất.

## 6. Thiết kế nghiệp vụ task chuẩn

### 6.1 Luồng tạo task

1. Chọn loại công việc
- việc thường
- việc có đầu mục con
- việc liên kết report

2. Chọn người xử lý
- vai trò hoặc tài khoản

3. Chọn người thực hiện
- vai trò hoặc tài khoản

4. Chọn người xem
- vai trò hoặc tài khoản

5. Nếu là `task có đầu mục con`
- nhập danh sách đầu mục
- chọn loại từng đầu mục hoặc áp cấu hình chung

### 6.2 Luồng thực hiện

- Người thực hiện chỉ nhìn thấy:
  - tên task cha
  - đầu mục được giao
  - nút thao tác
- Khi bấm thao tác:
  - nếu là báo cáo lời: nhập nội dung
  - nếu là báo cáo số: chỉ nhập số
  - nếu yêu cầu minh chứng: thêm file

### 6.3 Luồng theo dõi

- Người xem không thấy nút sửa, giao, nộp.
- Người xem chỉ thấy:
  - tiến độ chung
  - tiến độ theo đơn vị
  - tổng hợp số
  - danh sách đầu mục đã/đang/chưa hoàn thành

## 7. Đề xuất refactor theo pha

### Pha 1. Chuẩn hóa quyền

Mục tiêu:

- Chốt bộ quyền 3 lớp.
- Tạo lớp chuẩn hóa quyền dùng chung toàn hệ thống.
- Cập nhật màn `Vai trò`.
- Đảm bảo menu và điều hướng hiểu quyền `xem`.

Kết quả cần có:

- vai trò mới dùng `view/process/exec`
- vai trò cũ vẫn dùng được
- không gãy hệ thống đang chạy

### Pha 2. Chuẩn hóa task

Mục tiêu:

- Tách logic:
  - người xem
  - người xử lý
  - người thực hiện
- Chuẩn hóa `task con`
- Thu gọn giao diện thao tác cho người thực hiện

Kết quả cần có:

- `task cha` là lớp điều hành
- `task con` là đầu mục thực thi
- báo cáo lời/số và file minh chứng là cấu hình chuẩn

### Pha 3. Chuẩn hóa report

Mục tiêu:

- Tách hẳn `report engine` khỏi `task engine`
- Xây lớp liên kết chuẩn giữa task và biểu mẫu report

Kết quả cần có:

- một nguồn dữ liệu chính cho mỗi đầu việc
- đồng bộ tổng hợp từ report về task

### Pha 4. Chuẩn hóa giao diện

Mục tiêu:

- Điều hướng theo quyền
- Dashboard theo vai trò
- Popup và form theo một design language thống nhất

### Pha 5. Tái cấu trúc dữ liệu

Mục tiêu:

- giảm JSON field kiêm nhiều ý nghĩa
- tăng quan hệ chuẩn giữa `task`, `participant`, `submission`, `report link`

Lưu ý:

- Đây là pha cần migration cẩn thận nhất.
- Chỉ làm khi Pha 1-4 đã ổn nghiệp vụ.

## 8. Backlog ưu tiên gần

### Ưu tiên A

- Chốt quyền `view/process/exec` trên giao diện vai trò.
- Dùng một lớp chuẩn hóa quyền duy nhất.
- Rà toàn bộ menu theo quyền `xem`.

### Ưu tiên B

- Chuẩn hóa màn tạo task:
  - người xử lý
  - người thực hiện
  - người xem
- Chuẩn hóa task con về cấu hình:
  - lời
  - số
  - file bắt buộc/không

### Ưu tiên C

- Thiết kế lại task detail cho 3 loại người dùng:
  - xem
  - xử lý
  - thực hiện

### Ưu tiên D

- Thiết kế lớp liên kết `task <-> report`

## 9. Nguyên tắc triển khai

- Không viết lại toàn hệ thống trong một lần.
- Không xóa tương thích cũ trước khi giao diện và route mới ổn định.
- Mỗi pha đều cần:
  - migration dữ liệu
  - kiểm thử quyền
  - kiểm thử giao diện
  - kiểm thử tài khoản thật theo vai trò mẫu

## 10. Kết luận

Hệ thống hiện nay đã có đủ vật liệu để tiến lên một kiến trúc chuẩn hơn. Vấn đề chính không còn là thiếu tính năng, mà là thiếu một mô hình chung để các tính năng vận hành liền mạch với nhau.

Định hướng đúng cho giai đoạn tiếp theo là:

- chuẩn hóa quyền trước
- chuẩn hóa `task`
- tách bạch `task` và `report`
- sau đó mới tiếp tục mở rộng tính năng

Nếu bám đúng lộ trình này, hệ thống sẽ:

- dễ hiểu hơn với người dùng
- dễ quản trị hơn
- dễ mở rộng hơn
- giảm mạnh việc vá lỗi theo từng tình huống nghiệp vụ phát sinh

# Lộ Trình Triển Khai Đề Án Cải Tổ 2026

Ngày cập nhật: `16/05/2026`

## 1. Phạm vi

Tài liệu này chuyển đề án kiến trúc thành roadmap triển khai thực tế, có thể dùng để:

- theo dõi tiến độ nội bộ
- chia việc cho team
- kiểm tra nghiệm thu từng pha
- tránh cải tổ quá rộng trong một lần deploy

## 2. Nguyên tắc triển khai

- Không viết lại toàn hệ thống trong một đợt.
- Mỗi pha phải chạy được độc lập.
- Mọi pha đều phải có lớp tương thích ngược nếu dữ liệu cũ còn đang dùng.
- Luôn ưu tiên:
  - không gãy host đang chạy
  - không làm mất dữ liệu
  - không làm người dùng đang vận hành bị sốc giao diện

## 3. Trạng thái hiện tại

### Đã có trong code

- lớp chuẩn hóa quyền mới `view / process / exec`
- giao diện vai trò 3 quyền
- mặc định theo tên vai trò
- menu desktop/mobile đã hiểu quyền `xem`
- một phần `task`, `report`, `portal` đã đọc quyền chuẩn hóa
- đã có tài liệu kiến trúc gốc

### Chưa hoàn tất

- chưa refactor hết toàn bộ route còn tư duy `lead/exec`
- chưa tách chuẩn `task participant` và `task submission`
- chưa chuẩn hóa luồng `task` và `report` theo một mô hình dữ liệu đích
- chưa có migration chính thức cho việc thay mô hình dữ liệu task
- chưa có bộ test vai trò/nghiệp vụ đầy đủ

## 4. Các pha triển khai

## Pha 1. Chuẩn hóa quyền

### Mục tiêu

- Chốt quyền `Xem / Xử lý / Thực hiện`
- Ánh xạ ngược với dữ liệu quyền cũ
- Cập nhật giao diện vai trò
- Cập nhật menu và quyền truy cập module

### Đầu việc

1. Chuẩn hóa payload quyền dùng chung trong `utils`.
2. Cập nhật màn `Vai trò` desktop/mobile.
3. Cập nhật context processor.
4. Cập nhật `task`, `report`, `portal`, `contacts`, `news`, `library`.
5. Rà bản mobile để không lệch với desktop.

### Đầu ra

- vai trò mới dùng được ngay
- vai trò cũ không gãy
- quyền `xem` hoạt động thật, không chỉ hiện menu

### Tiêu chí nghiệm thu

- một vai trò chỉ có `p_task_view` vẫn xem được toàn bộ task nhưng không sửa
- một vai trò chỉ có `p_task_exec` không tạo/xóa task
- một vai trò có `p_task_process` tạo/sửa/xóa được task
- menu và route không mâu thuẫn nhau

### Rủi ro

- route cũ còn check thẳng `p_*_lead`
- mobile lệch logic với desktop

### Giảm rủi ro

- thêm helper chung
- rà grep toàn repo theo tên quyền cũ

## Pha 2. Chuẩn hóa mô hình task

### Mục tiêu

- tách rõ `xem việc`, `xử lý`, `thực hiện`
- giảm việc `Task` kiêm quá nhiều ý nghĩa

### Đầu việc

1. Chốt vocabulary nghiệp vụ:
  - `task`
  - `task item`
  - `watcher`
  - `manager`
  - `executor`
2. Thiết kế lại UI tạo task theo 3 lớp đối tượng:
  - người xử lý
  - người thực hiện
  - người xem
3. Chuẩn hóa `task con`
  - báo cáo lời
  - báo cáo số
  - file bắt buộc
4. Chuẩn hóa màn chi tiết task theo 3 chế độ nhìn
  - lãnh đạo/xem
  - điều phối/xử lý
  - thực hiện

### Đầu ra

- danh sách task chính chỉ hiển thị đúng cấp cần quản trị
- người thực hiện thao tác gọn, không phải nhìn quá nhiều thông tin điều phối

### Tiêu chí nghiệm thu

- người xem mở task được nhưng không thấy nút sửa/giao/nộp
- người xử lý tạo được task con hàng loạt
- người thực hiện chỉ thấy đầu mục của mình và thao tác cần làm

### Rủi ro

- logic `TaskAssignment` hiện đang kiêm nhiều vai trò
- nhiều template đang bám trực tiếp vào dữ liệu cũ

## Pha 3. Chuẩn hóa report

### Mục tiêu

- tách lớp `task` khỏi lớp `report`
- chuẩn hóa liên kết giữa 2 module

### Đầu việc

1. Định nghĩa rõ ba chế độ:
  - task tự báo cáo
  - task con báo cáo
  - task liên kết report template
2. Thiết kế model liên kết:
  - `task_report_link`
3. Chốt quy tắc “một nguồn dữ liệu chính”.
4. Đồng bộ tổng hợp từ report về task.

### Đầu ra

- không còn nhập số liệu song song ở hai nơi cho cùng một đầu việc

### Tiêu chí nghiệm thu

- task liên kết report chỉ đọc dữ liệu từ report
- tổng hợp số liệu về task khớp với report cycle

## Pha 4. Tái cấu trúc dữ liệu task

### Mục tiêu

- giảm phụ thuộc vào nhiều JSON field
- đưa nghiệp vụ về model quan hệ rõ ràng hơn

### Đầu việc

1. Tách `task_participant`
2. Tách `task_submission`
3. Tách `task_item`
4. Viết migration chuyển dữ liệu từ:
  - `assignment_scope_json`
  - `viewer_scope_json`
  - `report_schema_json`
  - `report_payload_json`

### Đầu ra

- schema rõ ràng hơn
- route ít phải suy luận hơn

### Tiêu chí nghiệm thu

- task cũ sau migration vẫn mở được
- dữ liệu báo cáo cũ không mất
- thống kê trước/sau migration khớp

### Rủi ro

- migration sai có thể làm lệch dữ liệu lịch sử

### Giảm rủi ro

- export backup DB trước migration
- viết script dry-run
- so sánh số lượng record trước/sau

## Pha 5. Chuẩn hóa giao diện và dashboard

### Mục tiêu

- giao diện theo vai trò
- giảm popup phức tạp
- dashboard đúng đối tượng sử dụng

### Đầu việc

1. Thiết kế dashboard cho:
  - người xem
  - người xử lý
  - người thực hiện
2. Tối giản popup tạo task và task con.
3. Chuẩn hóa pattern:
  - form shell
  - bảng danh sách
  - filter bar
  - action footer

### Đầu ra

- giao diện liền mạch giữa các module

### Tiêu chí nghiệm thu

- cùng một kiểu quyền thì pattern hiển thị giống nhau ở các module
- popup không còn trộn quá nhiều mục đích

## 5. Kế hoạch migration

## 5.1 Migration quyền

### Mục tiêu

- Vai trò cũ vẫn dùng được
- Vai trò mới không cần biết `lead/exec`

### Cách làm

1. Chuẩn hóa khi đọc quyền.
2. Chưa ép đổi dữ liệu DB ngay.
3. Chỉ khi hệ thống ổn mới viết job dọn dữ liệu quyền cũ.

### Rollback

- nếu lỗi, chỉ cần quay về logic đọc quyền cũ vì dữ liệu DB chưa bị phá

## 5.2 Migration task

### Mục tiêu

- chuyển dần từ JSON field sang model quan hệ

### Cách làm

1. thêm bảng mới
2. ghi song song một thời gian
3. đọc ưu tiên bảng mới, fallback dữ liệu cũ
4. sau khi ổn định mới bỏ phụ thuộc cũ

### Rollback

- vì còn ghi song song nên có thể quay lại lớp đọc cũ

## 6. Kế hoạch kiểm thử

## 6.1 Test theo vai trò

Ít nhất cần 6 tài khoản mẫu:

1. `Lãnh đạo`
2. `Chỉ huy PC06`
3. `Cán bộ PC06`
4. `Đơn vị thực hiện A`
5. `Đơn vị thực hiện B`
6. `Quản trị hệ thống`

## 6.2 Test theo tình huống

- tạo task thường
- tạo task có task con
- tạo task liên kết report
- người xem mở task
- người xử lý chỉnh cấu hình
- người thực hiện nộp báo cáo lời
- người thực hiện nộp báo cáo số
- tổng hợp số liệu
- tải file minh chứng
- xóa task

## 6.3 Test trước deploy

- `py_compile`
- parse Jinja
- test thủ công trên browser
- test host với tài khoản thật

## 7. Định nghĩa hoàn tất đề án

Đề án được coi là hoàn tất ở cấp triển khai khi có đủ:

- tài liệu kiến trúc
- ma trận quyền chuẩn
- lộ trình theo pha
- nguyên tắc migration
- tiêu chí nghiệm thu
- backlog đầu việc ưu tiên

Đề án được coi là hoàn tất ở cấp sản phẩm khi:

- Pha 1 đến Pha 5 đã triển khai xong
- quyền thống nhất trên toàn bộ module
- `task` và `report` tách bạch trách nhiệm
- dữ liệu được chuyển sang mô hình đích

## 8. Backlog ưu tiên ngay sau đề án

1. Rà toàn bộ các route còn check `lead/exec` trực tiếp.
2. Chốt schema đích cho `task_item`, `task_participant`, `task_submission`.
3. Thiết kế màn tạo task phiên bản mới.
4. Thiết kế màn chi tiết task theo 3 lớp người dùng.
5. Viết migration kế hoạch cho dữ liệu task.

## 9. Kết luận

Roadmap đúng cho hệ thống không phải là “thêm tiếp chức năng”, mà là:

- chuẩn hóa quyền
- chuẩn hóa mô hình task
- tách task và report
- rồi mới tiếp tục mở rộng

Nếu bám theo lộ trình này, từng đợt sửa sẽ có mục tiêu rõ, kiểm soát rủi ro tốt hơn, và hệ thống sẽ chuyển dần sang cấu trúc chuyên nghiệp mà không cần viết lại toàn bộ trong một lần.

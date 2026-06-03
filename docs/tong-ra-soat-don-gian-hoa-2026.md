# Tổng Rà Soát Logic Và Thiết Kế Đơn Giản Hóa PC06

Ngày cập nhật: `02/06/2026`

## 1. Kết luận rà soát nhanh

Hệ thống hiện đã có nhiều chức năng, nhưng trải nghiệm sử dụng còn khó vì:

- Người dùng phải hiểu tên module kỹ thuật thay vì hiểu theo việc cần làm.
- `Task`, `Report`, `child task`, `submission`, `report schema` vẫn còn chồng vai trò.
- Điều hướng đang trải rộng quá nhiều nút ngang cấp, thiếu nhóm thao tác chính.
- Nhiều màn hình vẫn tách desktop/mobile riêng nên khó giữ trải nghiệm nhất quán.
- Hai file nghiệp vụ lớn `routes/tasks.py` và `routes/reporting.py` đang vượt ngưỡng dễ bảo trì.

## 2. Các điểm nghẽn chính

### 2.1 Logic nghiệp vụ

- `Task` đang kiêm cả giao việc, theo dõi, báo cáo lời, báo cáo số, liên kết biểu mẫu.
- `TaskAssignment` còn giữ cả vai trò phân công lẫn nơi chứa kết quả tạm.
- Một số dữ liệu mở rộng vẫn nằm trong JSON nên khó kiểm soát quy tắc nghiệp vụ dài hạn.

### 2.2 Trải nghiệm người dùng

- Trang chủ cũ thiên về thống kê module hơn là hướng người dùng đi vào thao tác chính.
- Menu chính có quá nhiều mục ngang hàng: `Công việc`, `Điểm danh`, `Xếp hạng`, `Bảng tin`, `Thư viện`, `Danh bạ`, `QR & Link`, `Trợ lý AI`, `Báo cáo`, `Hệ thống`.
- Cùng một việc nhưng người dùng phải đoán nên vào `Task` hay `Report`.

### 2.3 Kỹ thuật

- `routes/tasks.py` hơn `5.200` dòng.
- `routes/reporting.py` hơn `5.300` dòng.
- Template và CSS đang chứa nhiều logic trình bày theo từng màn riêng lẻ, khó tái sử dụng.

## 3. Hướng thiết kế lại thống nhất

### 3.1 Tư duy vào hệ thống

Không tổ chức theo “module kỹ thuật”, mà theo 3 nhóm việc:

1. `Làm việc hằng ngày`
2. `Tra cứu và hỗ trợ`
3. `Quản trị hệ thống`

### 3.2 Phân tách trách nhiệm

- `Task`: điều hành và giao việc.
- `Report`: nhập biểu mẫu và tổng hợp số liệu chuẩn.
- `Task` liên kết `Report` khi cần, nhưng không nhập song song hai nơi cho cùng một đầu ra.

### 3.3 Chuẩn quyền

Giữ thống nhất 3 tầng:

- `Xem`
- `Xử lý`
- `Thực hiện`

Tất cả menu và nút bấm nên bám đúng 3 tầng này.

## 4. Pha triển khai đề xuất

### Pha 1: Đơn giản hóa lối vào

- Đổi trang chủ thành `trung tâm thao tác`.
- Gom menu theo nhóm thay vì liệt kê dài.
- Dùng nhãn dễ hiểu, gần thao tác thật.

### Pha 2: Ổn định luồng `Task`

- Giữ một mô hình thao tác chính: `Task -> Item -> Assignment -> Submission`.
- Dừng mở rộng thêm nhánh cũ dựa trên `child task` tự do.
- Tách helper, policy, builder khỏi `routes/tasks.py`.

### Pha 3: Ổn định luồng `Report`

- Giữ `Report` là nơi nhập số liệu chuẩn.
- Chuẩn hóa rõ `template`, `cycle`, `instance`, `submission`.
- Rút gọn màn quản trị biểu mẫu và màn nhập liệu theo cùng bố cục.

### Pha 4: Hợp nhất giao diện

- Giảm template desktop/mobile tách riêng nếu không thật sự cần.
- Tạo component dùng chung cho card, bảng, menu thao tác, trạng thái.

## 5. Những gì đã làm trong đợt chỉnh này

- Thiết kế lại trang chủ theo hướng `workspace`.
- Rút gọn menu điều hướng thành các nhóm: `Trang chủ`, `Công việc`, `Báo cáo`, `Điều hành`, `Tra cứu`, `Hỗ trợ`, `Hệ thống`.
- Giữ phần thống kê ở mức tóm tắt để người dùng nhìn nhanh rồi vào đúng nơi cần thao tác.
- Thiết kế lại danh sách `Task` theo ngữ cảnh sử dụng: `Cần xử lý ngay`, `Việc của tôi`, `Tôi giao hoặc theo dõi`, `Chỉ xem và tra cứu`.
- Sửa `lazy repair` runtime ở màn chi tiết `Task` để bridge `TaskParticipant` và `TaskSubmission` được hàn đúng lúc, đồng thời không làm màn danh sách tự ghi dữ liệu ngoài ý muốn.
- Làm lại trải nghiệm màn chi tiết `Task` theo hướng hành động: có `trạng thái tổng`, `bước tiếp theo`, `khu vực làm việc`, và tự ưu tiên mở đúng phần người dùng cần thao tác.
- Tách lớp `view-model` của `Task` sang module riêng để gom logic hiển thị/trạng thái ra khỏi `routes/tasks.py`, đồng thời thêm test đơn vị riêng cho lớp này.
- Tách tiếp lớp `scope/policy` của `Task` sang module riêng để gom logic phân quyền, kế thừa quyền cha-con và serialize phạm vi xử lý/xem khỏi `routes/tasks.py`, đồng thời thêm test đơn vị riêng cho lớp này.
- Tách thêm lớp `read model` của `Task` sang module riêng để gom logic dựng nhóm đề cương, danh sách nộp file/biểu mẫu và metadata field khỏi `routes/tasks.py`, đồng thời thêm test đơn vị riêng cho lớp này.
- Tách luôn lớp `page builder` của `Task` để gom điều phối danh sách/chi tiết `Task` ra khỏi route, giúp `routes/tasks.py` quay về vai trò nhận request, kiểm quyền, gọi builder và render.
- Bắt đầu áp dụng cùng mô hình cho `reporting`: tách `policy` và `page builder` của dashboard/workspace ra khỏi `routes/reporting.py` để chuẩn bị bóc tiếp `read model` và `services`.
- Tách tiếp lớp `service` của `reporting` cho phần `cycle context`, `route values` và `back-url`, giúp route workspace/report preview bớt giữ logic điều hướng và resolve trạng thái lõi.
- Tách thêm lớp `read model` và `submission service` của `reporting` để gom logic `history/export state` và `save/submit/export submission` ra khỏi route, đưa `routes/reporting.py` gần hơn với vai trò điều phối thuần.

## 6. Ưu tiên tiếp theo

1. Tách `routes/tasks.py` thành các phần: `queries`, `policies`, `services`, `views`.
2. Tiếp tục làm lại màn danh sách `Task` theo bộ lọc “Việc của tôi”, “Tôi giao”, “Quá hạn”, “Đã nộp”.
3. Giảm độ phức tạp của `reporting_dashboard` và `cycle_workspace`.
4. Thêm test bao phủ cho runtime `TaskParticipant`, `TaskSubmission`, và quyền truy cập theo vai trò.

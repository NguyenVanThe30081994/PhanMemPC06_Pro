# Nghiên cứu phần mềm giao việc hiện nay
## Báo cáo tham chiếu cho chức năng "Giao việc - Báo cáo" của PhanMemPC06_Pro

Ngày cập nhật: `04/08/2026`
Phạm vi: so sánh cách các phần mềm giao việc phổ biến xử lý việc **phân công**, **người nhận điền kết quả**, **báo cáo văn bản / bảng số liệu / biểu mẫu** và **tổng hợp dữ liệu**.

---

## 1. Tóm tắt nhanh (Executive summary)

Các phần mềm giao việc hiện nay chia thành 4 nhóm theo "hình thái nhận việc - báo cáo":

| Nhóm | Đại diện | Cách người nhận việc làm | Điểm mạnh để học hỏi |
|---|---|---|---|
| Quản lý công việc dạng thẻ/bảng | Trello, Jira, Asana, ClickUp, monday.com | Cập nhật trạng thái thẻ, comment, checklist, đính kèm | Luồng `Giao → Nhận → Làm → Nộp → Duyệt → Trả lại` rõ ràng |
| Nhập liệu dạng bảng tính | Google Sheets, Airtable, monday.com (board dạng bảng) | Điền trực tiếp vào ô/ dòng của bảng, công thức, dropdown | Thu thập khối lượng lớn số liệu có cấu trúc, tổng hợp tức thì |
| Điền biểu mẫu | Google Forms, Microsoft Forms, Jotform, Typeform | Trả lời câu hỏi theo form, có validate bắt buộc | Thu thập dữ liệu chuẩn hóa, không cần đào tạo |
| Báo cáo văn bản | Google Docs, Word + mẫu chuẩn, Notion, Confluence | Soạn văn bản theo đề cương/mẫu, nộp file | Báo cáo lời theo từng mục, gộp thành văn bản tổng hợp |

**Kết luận chung:** không phần mềm nào gộp trọn "một chức năng giao việc duy nhất" cả 3 hình thái trên vào một luồng vận hành cho cơ quan nhà nước. Các sản phẩm thương mại chọn 1-2 hình thái làm chính rồi tích hợp phần còn lại. Do đó, thiết kế phù hợp cho PC06 là **giữ 1 đối tượng "Công việc" duy nhất, cho phép cấu hình 3 kiểu thu thập kết quả** (biểu mẫu / bảng số / văn bản theo đề cương) — tương ứng đúng khái niệm người dùng mô tả.

---

## 2. Nhóm 1: Quản lý công việc dạng thẻ/bảng (Task management)

### 2.1 Trello
- **Mô hình:** bảng (board) → cột danh sách (list) → thẻ (card). Mỗi thẻ là một việc.
- **Giao việc:** gán thành viên (member), hạn chót, nhãn, checklist.
- **Người nhận báo cáo:** cập nhật trạng thái cột (dời thẻ), comment, đính kèm file.
- **Bài học:** trạng thái trực quan theo ống dẫn (pipeline); mỗi bước chuyển trạng thái nên để lại dấu vết (activity log).

### 2.2 Jira
- **Mô hình:** issue (vấn đề/công việc) với luồng trạng thái (workflow) tùy biến; phổ biến cho phần mềm nhưng cũng dùng cho hành chính.
- **Giao việc:** người phụ trách (assignee), người theo dõi (watcher), ưu tiên, phiên bản.
- **Người nhận báo cáo:** trường tùy biến (custom fields), comment, đính kèm; báo cáo con (sub-task) và epic gộp.
- **Tổng hợp:** bảng điều khiển (dashboard), bộ lọc, xuất CSV/Excel.
- **Bài học:** tách `người làm` và `người theo dõi`; cho phép trường nhập liệu tùy biến theo loại công việc; gộp kết quả từ sub-task lên cấp cha.

### 2.3 Asana
- **Mô hình:** task có cấp cha-con (task/subtask), dự án (project), mục tiêu.
- **Giao việc:** gán 1 hoặc nhiều người, hạn chót, phụ thuộc (dependency).
- **Người nhận báo cáo:** cập nhật trường tùy biến, comment, đính kèm, gắn cờ "cần phê duyệt".
- **Tổng hợp:** chế độ xem danh sách/board/timeline; báo cáo tiến độ.
- **Bài học:** nút "yêu cầu phê duyệt" tách biệt giữa nộp và duyệt; cho phép gán nhiều người cùng một việc nhưng có 1 người chịu trách nhiệm chính.

### 2.4 ClickUp
- **Mô hình:** "Everything view" — cùng dữ liệu hiển thị dạng danh sách/bảng/board/lịch/Gantt.
- **Giao việc:** nhiều người gán, checklist, mục tiêu (goal), form tự tạo.
- **Người nhận báo cáo:** trường tùy biến đa dạng (số, ngày, dropdown, quan hệ), comment, đính kèm; có "form view" cho phép người ngoài điền.
- **Bài học:** cùng một khối dữ liệu có thể "nhìn" dưới nhiều góc độ (bảng cho kế hoạch, form cho người nhận, bảng tính cho số liệu) — không cần tạo nhiều màn hình khác nhau.

### 2.5 monday.com
- **Mô hình:** bảng (board) dạng bảng tính kết hợp thẻ; mỗi dòng là một mục, mỗi cột là một trường.
- **Giao việc:** cột "người phụ trách", trạng thái, hạn chót, cột tùy biến.
- **Người nhận báo cáo:** điền vào ô của cột, upload file, form tích hợp (monday forms).
- **Tổng hợp:** nhóm theo cột, tự động tổng (automations), dashboard.
- **Bài học:** "bảng tính + trường tùy biến" là cách nhập liệu nhanh nhất cho người dùng quen Excel; dữ liệu nhập 1 lần, hiển thị nhiều chiều.

---

## 3. Nhóm 2: Nhập liệu dạng bảng tính (Spreadsheet-like)

### 3.1 Google Sheets + workflow
- Người nhận việc điền vào các dòng/ô được chỉ định; người quản lý xem trực tiếp, dùng công thức tổng hợp.
- Điểm mạnh: quen thuộc, cho phép nhập nhiều dòng cùng lúc, kiểm tra tính hợp lệ theo ô.
- Điểm yếu khi dùng trực tiếp: khó kiểm soát ai sửa ô nào, khó buộc nộp đúng hạn, không có luồng phê duyệt.
- **Bài học:** nên giữ trải nghiệm "giống bảng tính" cho dữ liệu số (nhiều dòng, nhiều cột) nhưng gắn vào luồng có trạng thái và quyền.

### 3.2 Airtable
- Như bảng tính nhưng mỗi cột có kiểu dữ liệu ràng buộc (text, số, ngày, dropdown, người, file đính kèm).
- Chuyển đổi giữa lưới (grid), kanban, gallery, form.
- **Bài học:** định nghĩa kiểu dữ liệu cho từng cột giúp tổng hợp đúng và giảm lỗi nhập; form là "mặt trước" của cùng bảng dữ liệu.

---

## 4. Nhóm 3: Điền biểu mẫu (Form-like)

### 4.1 Google Forms
- Người giao việc dựng câu hỏi (trắc nghiệm, chọn nhiều, đoạn văn, thang điểm, ngày, tệp).
- Người nhận điền theo từng câu; hệ thống buộc trường bắt buộc; câu trả lời vào bảng tổng hợp (Sheets).
- Hạn chế: không phân quyền theo đơn vị, không có trạng thái nộp/duyệt, khó tách "phần của tôi" trong form chung.
- **Bài học:** form cần `trường bắt buộc`, `kiểu dữ liệu`, `đầu ra gộp thành bảng`; khi một form chung phục vụ nhiều đơn vị, cần lọc "phần đơn vị mình phải điền".

### 4.2 Microsoft Forms / Jotform / Typeform
- Bổ sung logic điều kiện (hiện/ẩn câu hỏi), upload file, đáp án điền một lần.
- **Bài học:** trường hợp "chỉ cho đơn vị mình" (scope) và "điền nhiều lần nhưng giữ bản nộp hiện hành" là yêu cầu thực tế cần có.

---

## 5. Nhóm 4: Báo cáo văn bản (Word-like)

### 5.1 Google Docs / Microsoft Word + mẫu chuẩn
- Người nhận việc soạn văn bản theo đề cương (mục I, II, III...), nộp file .docx hoặc dán nội dung.
- Người quản lý gộp nhiều bản thành văn bản tổng hợp, giữ cấu trúc đề cương.
- **Bài học:** với báo cáo văn bản, "đầu mục" (outline item) là đơn vị phân công nhỏ nhất; mỗi đơn vị nộp theo từng đầu mục; hệ thống gộp theo đúng thứ tự đề cương ra file Word.

### 5.2 Notion / Confluence (wiki + task)
- Trang văn bản có thể chứa bảng, checkbox, mục con; nhiều người cùng soạn.
- **Bài học:** mỗi đầu mục có thể có `hướng dẫn soạn` (guide text) và `đầu mục cha/con` để hỗ trợ đề cương nhiều cấp.

---

## 6. Nhóm 5: Phần mềm nguồn mở và nội bộ
- **Redmine / OpenProject:** issue + trường tùy biến + nhật ký thời gian, phân quyền theo vai trò; phù hợp triết lý của hệ thống nội bộ.
- **Vikunja / Wekan / Focalboard:** đơn giản, self-hosted.
- **Bài học:** các hệ thống nội bộ nên chạy được offline/self-host, mọi thao tác đều ghi log để truy vết.

---

## 7. 10 bài học thiết kế áp dụng cho PC06

1. **Một "Công việc" duy nhất, ba kiểu thu thập kết quả:** không tạo 3 module riêng; dùng trường `task_mode` để bật kiểu `Báo cáo văn bản (OUTLINE)`, `Nộp file/văn bản (FILE)`, `Biểu mẫu (FORM)`.
2. **Chuỗi thống nhất:** `Công việc → Đầu mục → Giao việc → Nộp bài → Duyệt/Trả lại`, đúng với mô hình `Task → TaskItem → TaskAssignment → TaskSubmission` đang có.
3. **Người nhận chỉ thấy "phần việc của tôi":** lọc theo đơn vị/vai trò/người được giao, không cho thấy toàn bộ form chung.
4. **Trạng thái rõ ràng:** `Đã giao → Đã tiếp nhận → Đã nộp → Đã duyệt/Trả lại bổ sung`, mọi chuyển trạng thái để lại nhật ký.
5. **Mỗi đầu mục có kiểu báo cáo riêng:** số liệu (number), lời (narrative), file minh chứng (attachment) — gộp được thành ma trận đơn vị × đầu mục.
6. **Biểu mẫu có trường ràng buộc kiểu dữ liệu:** text/number/radio/checkbox/table/textarea; trường bắt buộc phải validate ở server, không tin client.
7. **Trải nghiệm "bảng tính" cho dữ liệu nhiều dòng:** trường kiểu `table` cho phép nhập nhiều hàng/cột như bảng Excel, xuất lại đúng dạng bảng.
8. **Tổng hợp đa định dạng:** ma trận tiến độ trên màn hình, xuất Excel cho biểu mẫu, gộp Word cho báo cáo văn bản theo đề cương.
9. **Phân quyền 3 tầng:** Xem / Xử lý / Thực hiện; mọi truy vấn đối chiếu với phiên đăng nhập, không tin tham số client.
10. **Khả năng mở rộng và truy vết:** cho phép nộp nhiều lần nhưng chỉ 1 bản nộp hiện hành; lưu lịch sử; ghi log mọi thao tác quan trọng.

---

## 8. Đối chiếu nhanh với hiện trạng PhanMemPC06_Pro

| Bài học | Hiện trạng code | Ghi chú |
|---|---|---|
| 1. task_mode duy nhất | ✅ Đã có `task_mode` = OUTLINE/FILE/FORM | Cần gom UI về một khái niệm |
| 2. Chuỗi Task→Item→Assignment→Submission | ✅ Đã có đủ bảng + luồng nộp | Đã dọn xong logic workflow cũ |
| 3. Phần việc của tôi | ✅ Có tab "Phần việc của tôi" cho cả 3 chế độ | Có thể nâng thành trang tổng hợp "Việc của tôi" |
| 4. Trạng thái + nhật ký | ✅ `assigned/in_progress/submitted` + TaskComment | Còn thiếu trạng thái `trả lại bổ sung` ở UI tổng |
| 5. Đầu mục có kiểu báo cáo | ✅ `report_kind` number/narrative + attachment_required | — |
| 6. Form builder + validate server | ✅ TaskFormField + validate ở `_submit_task_report_v2` | — |
| 7. Nhập dạng bảng tính | ⚠️ Trường `table` hiện nhập dạng textarea phân cách `|` | Cần nâng lên lưới thêm/xóa dòng giống Excel |
| 8. Tổng hợp đa định dạng | ⚠️ Có xuất Excel FORM; **thiếu gộp Word OUTLINE**; ma trận còn dạng cục bộ | Đây là lỗ hổng lớn nhất |
| 9. Phân quyền 3 tầng | ✅ Đã có `view/process/exec` + scope json | — |
| 10. Nộp nhiều lần, 1 bản hiện hành | ✅ TaskSubmission giữ lịch sử, assignment.last_submission_id | — |

# Hướng dẫn tích hợp: Giao việc theo đề cương (PC06 Pro)

Chức năng: **upload file .docx/.txt bất kỳ → tự động quét cấu trúc mục lục đa tầng → gán từng MỤC cho cán bộ → tạo công việc báo cáo nội dung**.

## Nguyên tắc thiết kế (đơn giản)

- **1 mục = 1 việc**: sau khi quét đề cương, mỗi **MỤC** (heading `I.`, `1.`, `1.1.`…) là một nhiệm vụ gán cho cán bộ. Các dòng nội dung (gạch đầu dòng `-`, mục con `+`, đoạn văn) thuộc mục nào thì được **liệt kê ở dưới mục đó** và **gộp lại** thành nội dung của việc đó.
- **Không tách từng dòng nội dung thành việc riêng** (bỏ "tên việc nhỏ").
- **Không bắt buộc nộp file** — đây là báo cáo nội dung (`attachment_required=False`, `report_kind='narrative'`).
- **Không tự gán theo vai trò** — chỉ gán trực tiếp cho cán bộ cụ thể.

## 1. Các file liên quan

| File | Vai trò |
|---|---|
| `outline_parser.py` | Thuật toán phân tích cấu trúc đề cương (heading/bullet/plus/para) |
| `routes/outline.py` | Blueprint: trang giao diện + API (quét, danh sách cán bộ, tạo công việc) |
| `templates/outline_assign.html` | Trang **giao việc theo đề cương** (mục + nội dung liệt kê bên dưới + nút Gán việc bên cạnh) |
| `app.py` | Đã đăng ký `outline_bp` |
| `demo_outline_giao_viec.html` | Demo tĩnh giao việc (mở bằng trình duyệt, không cần server) |

## 2. URL truy cập (sau khi chạy app)

- `/outline-giao-viec` — Trang **Giao việc theo đề cương**
- `/api/parse-outline` — POST upload file → JSON cây
- `/api/outline-assignees` — GET danh sách cán bộ (chỉ user, không có vai trò)
- `/api/create-outline-task` — POST tạo công việc từ cây + gán việc

> Tất cả endpoint yêu cầu đăng nhập (session uid). POST cần header `X-CSRF-Token` (tự động gắn trong giao diện).

## 3. Giao diện (đơn giản, gom theo mục)

- Sau khi quét, hiển thị **danh sách mục** theo phân cấp. Mỗi mục là một khối: tiêu đề mục + **nút "Gán việc" bên cạnh**.
- Các dòng nội dung của mục được liệt kê ở dưới tiêu đề mục (gạch đầu dòng `–`, mục con `+`, đoạn văn in nghiêng).
- Bấm **Gán việc** → hộp thoại chọn **cán bộ** (tick nhiều người được) → tên hiển thị dạng tag bên cạnh mục.
- Thanh công cụ: Mở rộng / Thu gọn / Tạo công việc.

## 4. Thuật toán tạo công việc (`/api/create-outline-task`)

Duyệt cây đề cương, **chỉ xử lý các mục (heading)**:

- Nếu một mục **đã được gán** cán bộ → tạo **1 `TaskItem`**:
  - `title` = tiêu đề mục (vd `1. CÔNG TÁC THAM MƯU`).
  - `content` = **toàn bộ các dòng nội dung dưới mục gộp lại** (kể cả nội dung trong mục con; tiêu đề mục con được ghi dạng `▸ 1.1. …`).
  - `is_required=True`, `attachment_required=False`, `output_type='OUTLINE'`, `report_kind='narrative'`.
  - Giữ phân cấp: `parent_item_id` trỏ tới `TaskItem` của mục cha (nếu mục cha cũng được gán).
- Mục **chưa gán** → bỏ qua, không tạo việc.
- Với mỗi cán bộ đã chọn → tạo 1 `TaskAssignment` (`assignee_type='user'`, `role_id=None`).

Nếu **không có mục nào được gán** → trả lỗi 400, không tạo công việc.

## 5. Kiểm chứng đã qua

- Parser: phân cấp `I → 1 → 1.1 → bullet → plus (+)`, đoạn văn thuộc mục đang mở.
- Gán 2 mục bất kỳ (mục cấp 2 + mục cấp 1) → đúng 2 `TaskItem`, nội dung gộp đúng từng mục, `parent_item_id` đúng, assignment `user`/`role=None`.
- Endpoint `/api/outline-assignees` chỉ trả `users` (không có `roles`).
- Không gán mục nào → 400 kèm thông báo rõ ràng.

## 6. Ghi chú bảo mật

- Blueprint yêu cầu đăng nhập; endpoint POST dùng CSRF token như các module khác.
- File upload chỉ chấp nhận `.docx`/`.txt`, lưu thư mục tạm rồi xoá sau khi parse.
- Luồng giao việc cũ (`/tasks/outline-parse`) vẫn hoạt động độc lập; chức năng mới là kênh giao việc theo đề cương gọn nhẹ.

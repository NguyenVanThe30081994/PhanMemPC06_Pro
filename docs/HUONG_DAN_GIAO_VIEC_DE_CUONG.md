# Hướng dẫn tích hợp: Giao việc theo đề cương (PC06 Pro)

Chức năng mới: **upload file .docx/.txt bất kỳ → tự động nhận diện cấu trúc mục lục đa tầng → hiển thị dạng cây → gán cán bộ/vai trò cho từng mục → tạo công việc giữ nguyên phân cấp**.

> **HẠN CHẾ BẮT BUỘC:** mỗi gạch đầu dòng (`-`, `–`, `•`) hoặc dấu cộng (`+`) trong đề cương là **một việc riêng** và được gán cho đơn vị/cán bộ khác nhau. Không thiết kế theo hướng gộp toàn bộ gạch đầu dòng của cùng một mục thành 1 nhiệm vụ con để gán.

## 1. Các file mới / đã sửa

| File | Vai trò |
|---|---|
| `outline_parser.py` | Thuật toán phân tích cấu trúc đề cương (độc lập, không phụ thuộc Flask) |
| `routes/outline.py` | Blueprint: trang giao diện + các API (parse, gán, tạo công việc) |
| `templates/outline_editor.html` | Trình biên tập đề cương (cây + sửa/xoá/thêm icon ở góc) |
| `templates/outline_assign.html` | Trang **giao việc theo đề cương** (cây + gán cán bộ/vai trò + tạo công việc) |
| `app.py` | Đã đăng ký `outline_bp` |
| `demo_outline_editor.html` | Demo tĩnh editor (mở bằng trình duyệt, không cần server) |
| `demo_outline_giao_viec.html` | Demo tĩnh giao việc (mở bằng trình duyệt, không cần server) |

## 2. URL truy cập (sau khi chạy app)

- `/outline-editor` — Trình biên tập đề cương
- `/outline-giao-viec` — Trang **Giao việc theo đề cương**
- `/api/parse-outline` — POST upload file → JSON cây
- `/api/outline-assignees` — GET danh sách cán bộ + vai trò
- `/api/create-outline-task` — POST tạo công việc từ cây + gán việc
- `/api/save-outline` — POST xuất cây thành file .docx

> Tất cả endpoint yêu cầu đăng nhập (session uid). POST cần header `X-CSRF-Token` (đã tự động gắn trong giao diện).

## 3. Thuật toán phân tích cấu trúc (`outline_parser.py`)

Nhận diện theo thứ tự ưu tiên, **không giới hạn số tầng**:

1. **Số La Mã** `I.`, `II.`, `III.` → cấp 1 (phần/chương)
2. **Số thập phân** `1.1.1.`, `1.1.`, `1.` → cấp theo số chấm: `1.1` = cấp 3, `1.1.1` = cấp 4, v.v.
3. **Gạch đầu dòng** `-`, `–`, `•` → nội dung (thuộc mục cha gần nhất)
4. **Dấu cộng** `+` → mục con (**thuộc gạch đầu dòng cha gần nhất**)
5. **Đoạn văn tự do** → nội dung thuộc mục đang mở
6. Tiêu đề/đề mục trước mục đầu tiên → `title`/`subtitle`

Tự động **chuẩn hoá cấp độ**: nếu đề cương không có mục La Mã (bắt đầu bằng `1.`, `2.`), toàn bộ cây được nâng một bậc để luôn có cấp gốc h1.

Cấu trúc JSON trả về:

```json
{
  "title": "ĐỀ CƯƠNG BÁO CÁO TIẾN ĐỘ NĂM 2026",
  "subtitle": "TRONG TRIỂN KHAI...",
  "sections": [
    {
      "id": "a1b2c3d4",
      "type": "h1",
      "label": "I",
      "text": "KẾT QUẢ CÁC MẶT CÔNG TÁC",
      "children": [
        {
          "id": "e5f6g7h8",
          "type": "h2",
          "label": "1",
          "text": "CÔNG TÁC THAM MƯU...",
          "children": [
            { "type": "h3", "label": "1.1", "text": "...", "children": [
              { "type": "bullet", "text": "...", "children": [
                { "type": "plus", "text": "..." }
              ]}
            ]}
          ]
        }
      ]
    }
  ]
}
```

## 4. Giao diện

- **Cây đa tầng**: mục La Mã nền đỏ, mục số viền xanh, tiểu mục viền nét đứt, nội dung gạch đầu dòng, mục con `+` màu vàng — đúng thứ bậc thị giác.
- **Nút icon ở góc mỗi mục** (không nằm trong nội dung): giao việc 👤, sửa ✎, thêm ＋, xoá 🗑.
- **Thu gọn/mở rộng** từng nhánh hoặc toàn cây.
- **Gán việc**: bấm icon giao việc → chọn Cán bộ hoặc Vai trò → tick người/vai trò → tag hiển thị bên phải mục.
- **Tạo công việc**: nhập tên + hạn nộp → backend tạo `Task` (mode OUTLINE) + `TaskItem` phân cấp (dùng `parent_item_id`) + `TaskAssignment`.

## 5. Kiểm chứng đã qua

Với file `Đề cương báo cáo ĐA06 - H.T.Q.docx` (126 nút):
- Phân cấp đúng: I → 1 → 1.1 → bullets → 5 dấu `+` thuộc gạch "Bám sát chỉ tiêu...".
- Tạo công việc: 126 đầu mục, độ sâu cây tối đa 5, gán đúng user/role.
- Xuất Word: heading cấp 1–4 + bullet + bullet con.
- Luồng cũ `/tasks/outline-parse` (routes/tasks.py) đã đồng bộ: tách từng gạch đầu dòng / dấu `+` thành việc riêng, gán đơn vị khác nhau (không gộp content).

## 6. Ghi chú bảo mật

- Blueprint mới yêu cầu đăng nhập; endpoint POST dùng CSRF token như các module khác.
- File upload chỉ chấp nhận `.docx`/`.txt`, được lưu vào thư mục tạm rồi xoá sau khi parse.
- Không sửa các luồng giao việc cũ (`/tasks/outline-parse`) — chức năng mới là kênh bổ sung giữ nguyên phân cấp.

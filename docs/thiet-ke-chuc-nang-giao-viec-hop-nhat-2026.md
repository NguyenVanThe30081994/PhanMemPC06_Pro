# Thiết kế chức năng Giao việc - Báo cáo hợp nhất
## Một chức năng giao việc duy nhất cho PhanMemPC06_Pro

Ngày cập nhật: `04/08/2026`
Kế thừa: `THIET_KE_CHUC_NANG_TASK_CUOI.md`, `docs/tong-ra-soat-don-gian-hoa-2026.md`, `docs/nghien-cuu-phan-mem-giao-viec-2026.md`

---

## 1. Khái niệm người dùng → mô hình hệ thống

Người dùng mô tả khái niệm bằng 3 hình ảnh quen thuộc:

| Người dùng nói | Nghĩa nghiệp vụ | Ánh xạ sang hệ thống |
|---|---|---|
| "Điền biểu mẫu như Google Form" | Thu thập câu trả lời có cấu trúc (text, chọn, số, nhiều lựa chọn) | `task_mode = FORM` + `TaskFormField` |
| "Điền như trang tính Excel" | Thu thập nhiều dòng dữ liệu dạng bảng, xuất tổng hợp ra Excel | `task_mode = FORM` + trường kiểu `table`; xuất `.xlsx` |
| "Báo cáo văn bản theo nhiệm vụ như Word" | Soạn nội dung theo từng mục của đề cương, gộp thành văn bản tổng hợp | `task_mode = OUTLINE` + `TaskItem`; gộp ra `.docx` |
| (bổ sung) "Nộp file văn bản/ công văn" | Nộp tệp minh chứng, văn bản tổng hợp | `task_mode = FILE` + `TaskSubmissionFile` |

**Nguyên tắc chốt:** toàn hệ thống chỉ có **một khái niệm "Công việc"** (`Task`). Mỗi công việc khai báo một `task_mode` để chọn cách người nhận trả kết quả. Người giao việc không phải hiểu khái niệm kỹ thuật, chỉ chọn 1 trong 3 nút: **Biểu mẫu**, **Bảng số liệu**, **Báo cáo văn bản**.

## 2. Luồng vận hành thống nhất

```
1. Người giao việc tạo "Công việc" (tiêu đề, hạn chót, mô tả, phạm vi)
2. Chọn kiểu thu thập + cấu hình:
   - Báo cáo văn bản  : nhập/tải đề cương, chọn kiểu từng đầu mục (lời/số), gán đơn vị
   - Nộp file/văn bản : gán đơn vị, quy định định dạng file
   - Biểu mẫu/Bảng số : dựng trường (text, số, chọn, bảng...), gán đơn vị
3. Phát hành → đơn vị thấy "Việc của tôi"
4. Đơn vị: Tiếp nhận → Điền/nộp (nhiều lần, giữ lịch sử, 1 bản hiện hành)
5. Người giao: theo dõi ma trận tiến độ → Duyệt / Trả lại bổ sung
6. Tổng hợp: ma trận màn hình, xuất Excel (biểu mẫu/bảng số), gộp Word (văn bản)
```

## 3. Mô hình dữ liệu (đã có, giữ nguyên)

```
Task ── 1:N ── TaskItem (đầu mục đề cương / nhóm câu hỏi)
Task ── 1:N ── TaskAssignment (giao cho ai, theo đầu mục nào)
Task ── 1:N ── TaskSubmission (bản nộp, lịch sử nộp)
Task ── 1:N ── TaskFormField (cấu hình trường biểu mẫu)
TaskSubmission ── 1:N ── TaskSubmissionFile (file minh chứng)
Task ── 1:N ── TaskComment (nhật ký, trao đổi)
```

Không thêm bảng mới cho pha này. Các trường cần có đã nằm trong `models.py` (xem phần 5).

## 4. Giao diện mục tiêu

### 4.1 Màn danh sách `/tasks`
- 4 nhóm ngữ cảnh: `Cần xử lý ngay`, `Việc của tôi`, `Tôi giao hoặc theo dõi`, `Chỉ xem và tra cứu` (đã có).
- Mỗi dòng hiện: tiêu đề, kiểu thu thập (nhãn dễ hiểu), hạn chót, trạng thái, tiến độ.

### 4.2 Màn chi tiết công việc
- Hành động chính theo vai trò:
  - Người giao: thiết lập nội dung, theo dõi `Tiến độ chung` (ma trận đơn vị × đầu mục / danh sách nộp), `Xuất tổng hợp` (Excel/Word), `Trả lại bổ sung`.
  - Người nhận: tab `Phần việc của tôi` — thấy đúng đầu mục/trường được giao, nút `Tiếp nhận`, biểu mẫu điền, nộp, xem bản đã nộp.
- Thanh công cụ tổng hợp đặt ở tab `Tiến độ chung` của từng kiểu.

## 5. Phân tích lỗ hổng (Gap analysis)

| # | Mục tiêu thiết kế | Hiện trạng | Khoảng trống | Ưu tiên |
|---|---|---|---|---|
| G1 | Gộp báo cáo văn bản OUTLINE thành file Word | Chưa có endpoint/nút xuất Word | Cần: endpoint `/tasks/<tid>/export-outline.docx` + nút trên UI | **Cao** |
| G2 | Ma trận tiến độ đơn vị × đầu mục (OUTLINE) | Tab OUTLINE chỉ hiển thị theo từng nhóm đơn vị | Cần: tab `Tiến độ chung` dạng ma trận cho OUTLINE | **Cao** |
| G3 | Nhập dạng bảng tính như Excel cho trường `table` | Textarea phân cách `\|` | Nâng thành lưới động: thêm/xóa dòng, validate cột | Trung bình |
| G4 | Trả lại bổ sung (return) từ người giao | Đã có dữ liệu `returned_at` + trạng thái `returned` nhưng thiếu nút UI | Cần: nút `Trả lại bổ sung` + lý do trong nhật ký | Trung bình |
| G5 | Trang tổng hợp "Việc của tôi" cho người nhận | Danh sách `Việc của tôi` có sẵn | Nâng hiển thị trạng thái + hạn chót rõ hơn | Thấp |

## 6. Kế hoạch triển khai đợt này

1. **G1 — Xuất Word tổng hợp OUTLINE** (ưu tiên cao nhất, đúng yêu cầu "báo cáo văn bản như Word"):
   - Backend: `_export_outline_word_v2(tid)` dùng `python-docx`; duyệt `TaskItem` theo `sort_order`, với mỗi đầu mục gộp các `TaskSubmission` hợp lệ của các đơn vị được giao; tiêu đề = task.title; mỗi mục = heading theo `item_code + title`; nội dung = narrative + số liệu + ghi chú file đính kèm.
   - Kiểm quyền: người quản lý/người giao mới được xuất.
   - UI: nút `Xuất báo cáo Word` ở tab Tiến độ chung.
   - Route: `GET /tasks/<tid>/export-outline.docx` (đặt cạnh `export-form.xlsx`).

2. **G2 — Ma trận tiến độ OUTLINE**:
   - Backend: dựng hàng = đầu mục, cột = đơn vị, ô = trạng thái nộp; kèm tổng hợp tiến độ.
   - UI: tab `Tiến độ chung` cho OUTLINE, thay cho việc chỉ xem từng nhóm.

3. **G3 — Lưới nhập kiểu Excel cho trường `table`**:
   - UI: chuyển textarea thành bảng động (thêm/xóa dòng), vẫn lưu payload cũ tương thích.
   - Backend giữ nguyên định dạng payload (list of rows) để không vỡ dữ liệu cũ.

4. **G4 — Trả lại bổ sung** (nếu còn thời gian):
   - Nút `Trả lại bổ sung` với lý do → ghi `TaskComment`, set trạng thái assignment = `returned`.

## 7. Tiêu chí nghiệm thu

- [ ] Tạo công việc `Báo cáo văn bản`, gán 2 đơn vị theo đề cương 3 mục.
- [ ] Đơn vị tiếp nhận và nộp nội dung từng mục; 1 mục chưa nộp.
- [ ] Màn hình `Tiến độ chung` hiện ma trận: mục × đơn vị, ô xanh/trống đúng trạng thái.
- [ ] Bấm `Xuất báo cáo Word` nhận file `.docx` gồm tiêu đề + từng mục có nội dung đã nộp, đơn vị nộp được ghi rõ.
- [ ] Tạo công việc `Biểu mẫu` có trường bảng 3 cột; đơn vị nhập 2 dòng; xuất Excel ra đúng ô.
- [ ] Người không trong phạm vi không xem/nộp/xuất được.

## 8. Ghi chú tương thích
- Giữ nguyên payload cũ: trường `table` lưu dạng list-of-list; dữ liệu textarea cũ vẫn đọc được.
- Không xóa bảng/luồng cũ; các phần mới thêm độc lập, không phá luồng `child_tasks` đang dùng.
- Tất cả endpoint mới đều yêu cầu đăng nhập và kiểm tra quyền theo `view/process/exec`.

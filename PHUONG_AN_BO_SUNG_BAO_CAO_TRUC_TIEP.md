# Bổ sung phương án triển khai báo cáo trực tiếp trên phần mềm

Tài liệu gốc trong `phuong_an_trien_khai_bao_cao_excel.md` dùng `upload Excel` làm luồng nhập chính. Với nghiệp vụ hiện tại, cần bổ sung một nguyên tắc bắt buộc:

## 1. Luồng tác nghiệp chính của đơn vị

Đơn vị **báo cáo trực tiếp trên phần mềm**, không bắt buộc nhập trong Excel rồi upload lại.

Excel vẫn là nguồn chuẩn cho:

- Quét cấu trúc biểu mẫu.
- Sinh cấu hình template/version.
- Giữ công thức gốc.
- Render màn xem báo cáo theo đúng mẫu.
- Xuất Excel/PDF đúng định dạng.

## 2. Điều chỉnh kiến trúc

### 2.1. Template Excel là nguồn cấu hình

Biểu mẫu Excel được quản trị tải lên để hệ thống:

- Quét sheet/header/section/cột.
- Tạo `template_config`.
- Sinh trường nhập trên web.
- Xác định cột công thức, cột khóa, cột hiển thị, cột ẩn.

### 2.2. Đơn vị nhập trực tiếp trên web

Người dùng đơn vị thao tác theo luồng:

```text
Chọn biểu mẫu
  -> Chọn kỳ báo cáo
  -> Hệ thống mở form nhập trực tiếp
  -> Lưu nháp
  -> Nộp báo cáo
  -> Cấp trên kiểm tra / duyệt / trả lại
```

### 2.3. Công thức Excel vẫn là chuẩn hiển thị

Khi xem báo cáo và xuất báo cáo:

- Hệ thống mở workbook gốc.
- Đổ dữ liệu người dùng đã nhập vào đúng ô map theo template.
- Tính lại công thức bằng LibreOffice Calc nếu có.
- Hiển thị trên phần mềm từ workbook đã đổ dữ liệu.

## 3. Vai trò của upload Excel người dùng

`Upload Excel` từ phía đơn vị chỉ nên là:

- kênh hỗ trợ nhập liệu hàng loạt về sau;
- hoặc công cụ đối soát/nhập bù;
- không phải luồng mặc định.

## 4. Hệ quả triển khai

Khi phát triển module báo cáo:

1. Không thiết kế UI theo hướng buộc đơn vị upload file để nộp.
2. Màn hình chính của đơn vị là form nhập trực tiếp trên phần mềm.
3. Template config phải đủ giàu để sinh được form nhập và màn xem từ cùng một nguồn.
4. Submission/workflow/error history vẫn cần giữ để phục vụ kiểm tra, duyệt, tổng hợp và export.

# Chức Năng Điều Hành Và Thu Báo Cáo Hợp Nhất

Ngày cập nhật: `01/07/2026`

## 1. Mục tiêu

Xây dựng một chức năng chung để:

- tiếp nhận đầu vào nghiệp vụ từ nhiều nguồn
- phân tích thành các đầu mục có thể giao việc
- cấu hình đầu ra phù hợp cho từng đơn vị thực hiện
- tổng hợp kết quả thực hiện và kết quả báo cáo về một nơi

Hai tài liệu tham chiếu tuần và 06 tháng chỉ dùng để rút ra mô hình chung. Chúng không được coi là dữ liệu đầu vào cố định của hệ thống.

## 2. Tư duy nghiệp vụ

Thay vì tách:

- `Task` = giao việc
- `Report` = thu báo cáo

chức năng mới dùng một lớp trung gian: `workflow blueprint`.

`workflow blueprint` là bản mô tả chuẩn hóa của một đợt điều hành, gồm:

- nguồn nghiệp vụ đang mô phỏng loại tài liệu nào
- chu kỳ thực hiện
- cách thu thập dữ liệu
- các đầu mục cần giao
- các trường thông tin cần thu
- hoặc schema báo cáo có cấu trúc

Từ blueprint, hệ thống ánh xạ về hạ tầng đang có:

- `OUTLINE` khi cần tách nhiều đầu mục giao việc
- `FORM` khi cần thu biểu mẫu nội bộ
- `FILE` khi cần nộp báo cáo tổng hợp có cấu trúc

## 3. Các kiểu đầu vào chung

Hệ thống hiện chuẩn hóa các `source_kind` sau:

- `directive`
  - văn bản chỉ đạo, công tác tuần, danh sách việc phải làm
- `sectioned_report`
  - đề cương báo cáo chia mục, nhiều đơn vị phụ trách từng phần
- `google_form`
  - biểu mẫu bên ngoài hoặc mô hình dữ liệu kiểu khảo sát
- `excel_template`
  - biểu mẫu chỉ tiêu, bảng số liệu
- `report_template`
  - mẫu báo cáo chuẩn đã có trong subsystem reporting
- `custom`
  - cấu hình thủ công

## 4. Contract blueprint

Backend hiện hỗ trợ nhận `workflow_blueprint_json` khi tạo task.

Ví dụ tối thiểu cho đợt giao việc theo đề cương:

```json
{
  "title": "Công tác tuần Đội 1",
  "source_kind": "directive",
  "cadence": "weekly",
  "collection_mode": "outline",
  "summary": "Các đầu mục trọng tâm cần triển khai và báo cáo kết quả trong tuần.",
  "items": [
    {
      "title": "Đôn đốc xử lý hồ sơ cư trú",
      "report_kind": "narrative",
      "attachment_required": false
    },
    {
      "title": "Tổng hợp số lượng hồ sơ quá hạn",
      "report_kind": "number",
      "attachment_required": true
    }
  ]
}
```

Ví dụ cho biểu mẫu nội bộ:

```json
{
  "title": "Thu thập tiến độ triển khai",
  "source_kind": "google_form",
  "cadence": "monthly",
  "collection_mode": "form",
  "form_fields": [
    {
      "label": "Đơn vị báo cáo",
      "type": "text",
      "required": true
    },
    {
      "label": "Tổng số hồ sơ",
      "type": "number",
      "required": true
    },
    {
      "label": "Khó khăn, vướng mắc",
      "type": "textarea",
      "required": false
    }
  ]
}
```

Ví dụ cho báo cáo tổng hợp có cấu trúc:

```json
{
  "title": "Báo cáo tổng hợp tháng",
  "source_kind": "sectioned_report",
  "cadence": "monthly",
  "collection_mode": "file",
  "report_schema": {
    "enabled": true,
    "narrative": {
      "enabled": true,
      "required": true,
      "label": "Nội dung tổng hợp"
    },
    "attachment": {
      "enabled": true,
      "required": false,
      "label": "Phụ lục minh chứng"
    },
    "fields": [
      {
        "label": "Số văn bản đã tham mưu",
        "type": "number",
        "required": false
      },
      {
        "label": "Nhận xét chung",
        "type": "textarea",
        "required": false
      }
    ]
  }
}
```

## 5. Cách backend đang ánh xạ

### `collection_mode = outline`

Hệ thống sẽ:

- tạo `Task` ở mode `OUTLINE`
- tạo các `TaskItem` từ `items`
- dùng danh sách người nhận đang chọn ở form tạo task để gán cho từng `TaskItem`

Phù hợp với:

- công tác tuần
- chỉ đạo nhiều đầu việc
- đề cương giao cho nhiều đơn vị báo cáo từng phần

### `collection_mode = form`

Hệ thống sẽ:

- tạo `Task` ở mode `FORM`
- sinh `TaskFormField` từ `form_fields`

Phù hợp với:

- Google Form nội bộ hóa
- khảo sát nhanh
- thu chỉ tiêu theo biểu mẫu

### `collection_mode = file`

Hệ thống sẽ:

- tạo `Task` ở mode `FILE`
- sinh `report_schema_json`

Phù hợp với:

- báo cáo lời có cấu trúc
- báo cáo có số liệu tổng hợp
- báo cáo kèm file phụ lục

## 6. Những gì đã triển khai trong code

- Thêm module [task_blueprints.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/task_blueprints.py) để chuẩn hóa workflow blueprint.
- Luồng tạo task tại [routes/tasks.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/tasks.py) đã hỗ trợ:
  - đọc `workflow_blueprint_json`
  - tự suy ra `task_mode`
  - tự tạo `TaskItem` khi là `outline`
  - tự tạo `TaskFormField` khi là `form`
  - tự tạo `report_schema_json` khi là `file`
- Modal tạo công việc tại [templates/tasks_rebuild.html](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/templates/tasks_rebuild.html) đã có:
  - chuyển chế độ giữa `nhập thủ công` và `blueprint hợp nhất`
  - nạp nhanh các mẫu tham chiếu phổ biến
  - gọi endpoint preview để phân tích trước khi phát hành
  - nạp trực tiếp tài liệu tham chiếu `.docx`, `.txt`, `.xlsx` để sinh blueprint ban đầu
  - tự áp dụng tiêu đề, mô tả và mode suy luận từ blueprint
- Endpoint preview backend `/tasks/workflow-blueprint-preview` dùng chung đúng logic normalize với luồng tạo thật, tránh lệch giữa phần xem trước và dữ liệu lưu.
- Endpoint import backend `/tasks/workflow-blueprint-import` hiện hỗ trợ:
  - `Word/TXT -> đề cương công tác`
  - `Word/TXT -> đề cương báo cáo theo mục`
  - `Excel (.xlsx) -> biểu mẫu số liệu`
  - `Google Form URL/form ID -> biểu mẫu`

## 7. Giới hạn hiện tại

- Chưa có parser tự động đọc Word/Excel/Google Form thật rồi sinh blueprint.
- Chưa đọc được file Word `.doc` cũ trực tiếp.
- Chưa tự suy luận cấu trúc phức tạp của Excel như bảng nhiều tầng, sheet lồng nhau, vùng merge hoặc công thức nghiệp vụ.
- Chưa hỗ trợ gán người thực hiện khác nhau cho từng item ngay trong payload blueprint.
- Chưa tự đồng bộ sang subsystem `reporting` khi đầu ra là `report_template`.

## 8. Bước tiếp theo

1. Mở rộng parser Excel để hỗ trợ chọn sheet, nhận diện nhiều bảng trong cùng file và suy luận tốt hơn kiểu dữ liệu.
2. Bổ sung import trực tiếp từ file Word `.doc` cũ nếu nghiệp vụ còn dùng nhiều.
3. Thêm cấu hình người phụ trách theo từng `item`.
4. Thêm đồng bộ hai chiều giữa `Task` blueprint và `reporting` template/cycle khi cần.
5. Nếu cần, tách modal hiện tại thành wizard nhiều bước để hỗ trợ người nhập không quen JSON.

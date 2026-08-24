# Reporty MySQL Cutover

## Mục tiêu

- Dùng MySQL/MariaDB của cPanel làm database production duy nhất.
- Giữ file mutable ngoài `public_html`.
- Không còn fallback sang SQLite khi chạy dưới Passenger.
- Báo cáo hằng ngày dùng một `cycle` đang mở, dữ liệu lưu theo `report_date`, khi xem sẽ cộng dồn trong cùng cycle.

## Thay đổi code đã áp dụng

- [storage.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/storage.py)
  - Chuẩn hóa `mysql://` sang `mysql+pymysql://`.
  - Khi chạy dưới Passenger, thiếu `DATABASE_URL` hoặc còn trỏ SQLite sẽ raise lỗi thay vì âm thầm fallback.
- [routes/reporting.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/routes/reporting.py)
  - Báo cáo daily không còn sinh một cycle mới cho mỗi ngày.
  - Daily submissions mới lưu dạng `daily_delta`.
  - Màn xem/tải dữ liệu daily dựng số liệu lũy kế đến `report_date`.
  - Schema inspection chuyển sang SQLAlchemy inspector để chạy được trên MySQL.
- [reporting_submission_service.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/reporting_submission_service.py)
  - Daily save chỉ ghi phần dữ liệu của ngày đang nhập.
- [reporting_read_models.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/reporting_read_models.py)
  - Daily timeline/status lấy theo `report_date`, không buộc khớp với `cycle.open_at`.
- [merge_daily_cycles.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/merge_daily_cycles.py)
  - Gộp lịch sử daily cũ từ nhiều cycle về một cycle chuẩn.
- [scripts/admin/migrate_sqlite_to_external_db.py](/Users/thenhung/Documents/GitHub/PhanMemPC06_Pro/scripts/admin/migrate_sqlite_to_external_db.py)
  - Copy toàn bộ dữ liệu từ SQLite production sang MySQL/MariaDB.

## Cấu hình production trên cPanel

Trong Python App hoặc `.env` của Passenger:

```env
DATABASE_URL=mysql://cpanel_user:strong_password@localhost/cpanel_db_name
PC06_DATA_DIR=/home/cpanel_user/pc06_data
FLASK_ENV=production
DEBUG=False
```

Thư mục `PC06_DATA_DIR` nên chứa:

- `uploads`
- `task_files`
- `library_files`
- `backups`
- `report_templates`
- `report_exports`
- `logs`
- `tmp`

## Quy trình chuyển dữ liệu từ SQLite sang MySQL

1. Sao lưu DB thật:

```bash
cp /home/<cpanel_user>/pc06_data/pc06_system.db /home/<cpanel_user>/pc06_data/pc06_system.db.bak_$(date +%Y%m%d_%H%M%S)
```

2. Kích hoạt virtualenv của app.

3. Chạy dry-run:

```bash
export DATABASE_URL='mysql://cpanel_user:strong_password@localhost/cpanel_db_name'
PC06_CONFIRM=YES python3 scripts/admin/migrate_sqlite_to_external_db.py \
  --source-sqlite /home/<cpanel_user>/pc06_data/pc06_system.db
```

4. Nếu summary ổn, chạy thật:

```bash
PC06_CONFIRM=YES python3 scripts/admin/migrate_sqlite_to_external_db.py \
  --source-sqlite /home/<cpanel_user>/pc06_data/pc06_system.db \
  --apply
```

5. Restart Passenger:

```bash
touch tmp/restart.txt
```

## Dựng lại dữ liệu daily sau cutover

Nếu lịch sử cũ đã bị tách thành nhiều cycle ngày:

1. Gộp các cycle nguồn vào cycle đích:

```bash
export PC06_DATA_DIR=/home/<cpanel_user>/pc06_data
python3 merge_daily_cycles.py --target-cycle-id <target> --source-cycle-ids <source1> <source2> --apply
```

2. Dựng lại effective exports:

```bash
python3 reconcile_report_history.py --report-type daily --include-open --apply --overwrite
```

3. Restart Passenger:

```bash
touch tmp/restart.txt
```

## Checklist xác nhận sau triển khai

- `SQLALCHEMY_DATABASE_URI` in ra `mysql+pymysql://...`
- MySQL đã có bảng `report_cycle`, `report_instance`, `report_submission`
- Mở một daily cycle duy nhất và nhập 2 ngày liên tiếp:
  - form ngày sau chỉ hiện delta của ngày đó
  - màn xem/tải hiện số liệu cộng dồn
- `create_cycle` cho daily không tạo thêm cycle mới nếu đã có cycle đang mở
- `admin/reports` không còn hiện nhiều cycle daily tách từng ngày cho cùng một biểu mẫu

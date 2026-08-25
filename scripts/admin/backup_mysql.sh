#!/bin/sh
# ============================================================================
# Backup MySQL hằng đêm cho PhanMemPC06_Pro trên cPanel (B4')
# docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md
#
# - Lưu ra thư mục NGOÀI public_html (mặc định ~/pc06_backups)
# - Nén gzip, giữ lại RETENTION_DAYS ngày (mặc định 14)
# - Gắn vào cPanel → Cron Jobs, ví dụ 02:30 mỗi đêm:
#     30 2 * * * /home/<cpanel_user>/public_html/PhanMemPC06_Pro/scripts/admin/backup_mysql.sh >> /home/<cpanel_user>/pc06_backups/backup.log 2>&1
#
# Thông tin kết nối đọc từ biến môi trường hoặc ~/.my.cnf (khuyến nghị):
#   [client]
#   host=localhost
#   user=cpanel_db_user
#   password=...
#
# Khôi phục (quy trình thử 1 quý/lần):
#   gunzip < pc06_<db>_<stamp>.sql.gz | mysql --host=localhost --user=<user> -p <db_moi>
# ============================================================================

set -eu

DB_HOST="${DB_HOST:-localhost}"
DB_NAME="${DB_NAME:?Thiếu DB_NAME — đặt trong ~/.my.cnf hoặc export trước khi chạy}"
DB_USER="${DB_USER:-}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/pc06_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

AUTH_ARGS=""
if [ -n "$DB_USER" ]; then
    AUTH_ARGS="--user=$DB_USER"
fi
if [ -n "${DB_PASS:-}" ]; then
    AUTH_ARGS="$AUTH_ARGS --password=$DB_PASS"
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${DB_NAME}_${STAMP}.sql.gz"

mysqldump \
    --host="$DB_HOST" $AUTH_ARGS \
    --single-transaction --quick \
    --routines --triggers --events \
    "$DB_NAME" | gzip > "$OUT"

# Xóa bản cũ hơn RETENTION_DAYS ngày
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime "+$RETENTION_DAYS" -delete 2>/dev/null || true

SIZE=$(du -h "$OUT" | cut -f1)
echo "$(date '+%Y-%m-%d %H:%M:%S') [OK] $OUT ($SIZE)"

#!/bin/sh
# ============================================================================
# Bảo trì bảo mật hàng tháng cho PhanMemPC06_Pro trên cPanel (Đợt C4)
# docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md
#
# Kiểm tra phụ thuộc lỗi thời + lỗ hổng đã biết (pip-audit nếu có cài).
# Chỉ BÁO CÁO, không tự nâng cấp — việc nâng cấp cần chạy test rồi restart.
#
# Gắn cron ngày 1 hằng tháng (08:00):
#   0 8 1 * * /home/<cpanel_user>/public_html/PhanMemPC06_Pro/scripts/admin/monthly_security_maintenance.sh >> /home/<cpanel_user>/pc06_backups/maintenance.log 2>&1
#
# Yêu cầu: PIP_BIN trỏ tới pip của venv "Setup Python App" ≥3.9:
#   PIP_BIN=/home/<cpanel_user>/virtualenv/<ten_app>/bin/pip
# ============================================================================

set -eu

PIP_BIN="${PIP_BIN:-pip}"
AUDIT="${AUDIT:-1}"   # đặt AUDIT=0 nếu chưa cài pip-audit và không muốn cảnh báo

echo "==================================================="
echo "[PC06] Bảo trì bảo mật hàng tháng - $(date '+%Y-%m-%d %H:%M')"
echo "==================================================="

echo ""
echo "--- 1. Phụ thuộc có bản mới (pip list --outdated) ---"
"$PIP_BIN" list --outdated || echo "[WARN] Không liệt kê được outdated."

echo ""
echo "--- 2. Lỗ hổng đã biết (pip-audit) ---"
if [ "$AUDIT" = "1" ]; then
    if "$PIP_BIN" show pip-audit >/dev/null 2>&1; then
        # pip-audit cần chạy bằng python -m để đúng môi trường venv
        PYBIN="$(dirname "$PIP_BIN")/python"
        "$PYBIN" -m pip_audit -l || echo "[HÀNH ĐỘNG] Có gói dính CVE — nâng cấp trong requirements.txt, chạy test, restart."
    else
        echo "[GỢI Ý] Cài pip-audit một lần để quét CVE:"
        echo "         $PIP_BIN install pip-audit"
    fi
fi

echo ""
echo "--- 3. Việc vận hành nhắc lại ---"
echo "  [ ] Đã thử khôi phục backup MySQL quý này chưa? (xem DEPLOY_CPANEL.md)"
echo "  [ ] Rà logs > Bảo mật 7 ngày: /admin/logs (tab Bảo mật)"
echo "  [ ] CHANGELOG ghi nhận phiên bản phụ thuộc sau khi nâng cấp"

echo ""
echo "[PC06] Hoàn tất kiểm tra. Không có thay đổi nào được áp dụng."

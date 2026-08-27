#!/usr/bin/env bash
# ============================================================
#  PC06 - Khởi động server local (macOS / Linux)
#  Cập nhật 2026-08: chuẩn hoá theo code mới nhất
#    - Tự dùng virtualenv nếu có (.venv/venv) và cài deps thiếu
#    - Tự chạy migrate.py (backfill runtime) khi thiếu biến môi trường
#      PC06_SKIP_MIGRATE=1 để bỏ qua
#    - Host/port qua PC06_HOST / PC06_PORT (mặc định 127.0.0.1:5000)
#    - Chống chạy trùng: thoát nếu port đã bị chiếm
#  Dừng server: ./stop_server.sh  hoặc  Ctrl+C
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

export PC06_HOST="${PC06_HOST:-127.0.0.1}"
export PC06_PORT="${PC06_PORT:-5000}"
export FLASK_ENV="${FLASK_ENV:-development}"

# ── 1) Chọn Python ──────────────────────────────────────────
if [ -x ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
else
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD=python3
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD=python
    else
        echo "[LOI] Khong tim thay Python 3. Hay cai dat tu https://python.org"
        exit 1
    fi
fi
echo "[OK] Python: $("$PYTHON_CMD" --version 2>&1) -> $PYTHON_CMD"

# ── 2) Kiểm tra & cài thư viện còn thiếu ────────────────────
if ! "$PYTHON_CMD" -c "import flask, sqlalchemy, docx" >/dev/null 2>&1; then
    # pip cài vào Python hệ thống thường bị chặn quyền (PEP 668 / sandbox):
    # tự tạo venv dự án rồi cài vào đó, tránh bẩn môi trường hệ thống.
    echo "[..] Thieu thu vien - tao virtualenv .venv va cai requirements.txt ..."
    BASE_PY="$PYTHON_CMD"
    if [ "$BASE_PY" = ".venv/bin/python" ] || [ "$BASE_PY" = "venv/bin/python" ]; then
        BASE_PY=python3
    fi
    if "$BASE_PY" -m venv .venv 2>/dev/null; then
        PYTHON_CMD=".venv/bin/python"
        "$PYTHON_CMD" -m pip install -q --disable-pip-version-check -r requirements.txt \
            || echo "[CANH BAO] pip install loi - server van se duoc thu chay."
    else
        echo "[CANH BAO] Khong tao duoc .venv - thu cai truc tiep ..."
        "$PYTHON_CMD" -m pip install -q --disable-pip-version-check -r requirements.txt \
            || echo "[CANH BAO] pip install loi - server van se duoc thu chay."
    fi
fi

# ── 3) Chống chạy trùng trên cùng port ─────────────────────
# Lưu ý: macOS AirPlay Receiver (ControlCenter) mặc định chiếm cổng 5000.
# Không tự kill tiến trình này - hướng dẫn người dùng xử lý.
if lsof -Pi ":${PC06_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1; then
    OWNER_PID="$(lsof -Pi ":${PC06_PORT}" -sTCP:LISTEN -t 2>/dev/null | head -1)"
    OWNER_CMD="$(lsof -p "$OWNER_PID" 2>/dev/null | awk 'NR==2{print $1}')"
    case "$OWNER_CMD" in
        ControlCe*|ControlCenter*)
            echo "[LOI] Cong ${PC06_PORT} bi AirPlay Receiver cua macOS chiem (khong the giai phong giup ban)."
            echo "      Cach 1: Tat AirPlay Receiver - Cai dat He thong > AirDrop & Handoff > AirPlay Receiver = OFF"
            echo "      Cach 2: Chay tren cong khac, vi du:  PC06_PORT=5001 ./start_server.sh"
            ;;
        *)
            echo "[CANH BAO] Cong ${PC06_PORT} dang duoc su dung boi PID ${OWNER_PID} (${OWNER_CMD})."
            echo "           Chay ./stop_server.sh de giai phong, hoac dat PC06_PORT khac."
            ;;
    esac
    exit 1
fi

# ── 4) Migration + backfill runtime (như README) ────────────
if [ "${PC06_SKIP_MIGRATE:-0}" != "1" ]; then
    echo "[..] Kiem tra migration / backfill runtime (migrate.py) ..."
    if "$PYTHON_CMD" migrate.py >/dev/null 2>&1; then
        echo "[OK] Migration OK."
    else
        echo "[CANH BAO] migrate.py that bai - bo qua, server van khoi dong."
        echo "           Chi tiet: chay tay 'python3 migrate.py' de xem loi."
    fi
fi

# ── 5) Khởi động ────────────────────────────────────────────
echo ""
echo "=========================================="
echo "   PC06 SERVER - http://${PC06_HOST}:${PC06_PORT}"
echo "   FLASK_ENV=${FLASK_ENV}  (DEBUG=true de bat debug)"
echo "=========================================="
echo ""

exec "$PYTHON_CMD" app.py

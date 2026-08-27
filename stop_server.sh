#!/usr/bin/env bash
# ============================================================
#  PC06 - Dừng server local (macOS / Linux)
#  Giải phóng port PC06_PORT (mặc định 5000)
#  An toàn: bỏ qua tiến trình hệ thống macOS AirPlay (ControlCenter)
#  vốn mặc định chiếm cổng 5000 - tuyệt đối không kill tiến trình này.
# ============================================================
set -u

PORT="${PC06_PORT:-5000}"

# Tách PID máy chủ PC06 khỏi tiến trình hệ thống AirPlay
PIDS_TO_KILL=()
SYSTEM_SKIPPED=0
for pid in $(lsof -Pi ":${PORT}" -sTCP:LISTEN -t 2>/dev/null || true); do
    cmd="$(lsof -p "$pid" 2>/dev/null | awk 'NR==2{print $1}')"
    case "$cmd" in
        ControlCe*|ControlCenter*)
            echo "[CANH BAO] Bo qua PID $pid ($cmd) - tien trinh he thong AirPlay cua macOS."
            SYSTEM_SKIPPED=$((SYSTEM_SKIPPED + 1))
            ;;
        *)
            PIDS_TO_KILL+=("$pid")
            ;;
    esac
done

if [ "${#PIDS_TO_KILL[@]}" -eq 0 ]; then
    if [ "$SYSTEM_SKIPPED" -gt 0 ]; then
        echo "[CANH BAO] Cong ${PORT} bi AirPlay Receiver cua macOS chiem (khong the kill)."
        echo "           Hai cach xu ly:"
        echo "           1. Tat AirPlay Receiver: Cai dat He thong > AirDrop & Handoff"
        echo "           2. Chay server PC06 tren cong khac: PC06_PORT=5001 ./start_server.sh"
    else
        echo "[THONG BAO] Khong co server nao dang chay tren cong ${PORT}."
    fi
    exit 0
fi

for pid in "${PIDS_TO_KILL[@]}"; do
    echo "Dang dung process PID: $pid (cong ${PORT}) ..."
    kill "$pid" 2>/dev/null || true
done

sleep 2

# Kiểm tra lại: chỉ quan tâm PID của server (bỏ qua AirPlay)
REMAINING=()
for pid in $(lsof -Pi ":${PORT}" -sTCP:LISTEN -t 2>/dev/null || true); do
    cmd="$(lsof -p "$pid" 2>/dev/null | awk 'NR==2{print $1}')"
    case "$cmd" in
        ControlCe*|ControlCenter*) ;;
        *) REMAINING+=("$pid") ;;
    esac
done

if [ "${#REMAINING[@]}" -gt 0 ]; then
    echo "[CANH BAO] Server van con - buoc ket thuc (kill -9) ..."
    for pid in "${REMAINING[@]}"; do
        kill -9 "$pid" 2>/dev/null || true
    done
fi

echo "[THANH CONG] Server PC06 tren cong ${PORT} da duoc dung."

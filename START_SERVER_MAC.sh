#!/usr/bin/env bash
# ============================================================
#  PC06 - Khởi động server trên macOS (wrapper tiện dụng)
#  Logic thật nằm ở start_server.sh - script này chỉ forward
#  để giữ tương thích với thói quen cũ (./START_SERVER_MAC.sh)
# ============================================================
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/start_server.sh"

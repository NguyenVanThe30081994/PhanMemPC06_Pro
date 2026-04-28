#!/bin/bash
# Script khởi động server trên macOS

echo "=========================================="
echo "   KHỞI ĐỘNG PC06 SERVER"
echo "=========================================="

# Kiểm tra Python
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    echo "❌ Không tìm thấy Python!"
    exit 1
fi

echo "✅ Sử dụng: $PYTHON_CMD"

# Kiểm tra port 5000
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 5000 đang được sử dụng. Đang giải phóng..."
    kill -9 $(lsof -t -i:5000) 2>/dev/null
    sleep 1
fi

echo "✅ Port 5000 sẵn sàng"

# Cài đặt dependencies (nếu cần)
if [ -f "requirements.txt" ]; then
    echo "📦 Kiểm tra dependencies..."
    $PYTHON_CMD -m pip install -r requirements.txt --quiet
fi

echo ""
echo "=========================================="
echo "   🚀 SERVER ĐANG CHẠY"
echo "   📍 http://localhost:5000"
echo "=========================================="
echo ""
echo "Nhấn Ctrl+C để dừng server"
echo ""

# Mở browser sau 2 giây
(sleep 2 && open http://localhost:5000) &

# Chạy server
$PYTHON_CMD app.py

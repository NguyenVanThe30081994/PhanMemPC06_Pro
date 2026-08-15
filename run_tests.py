# -*- coding: utf-8 -*-
"""
Runner chuẩn cho bộ test PC06 — dùng cho CI và chạy local/server.

Tại sao cần runner này (thay vì `python -m unittest discover tests`):
- Test tạo/xóa dữ liệu (user, task, điểm vệ tinh...). Nếu chạy thẳng trên
  server đang deploy, biến môi trường/.env trỏ DATABASE_URL về MySQL
  production → test ghi/xóa DỮ LIỆU THẬT.
- Runner này LUÔN ép bộ test chạy trên một database SQLite dùng xong bỏ
  (file tạm) + thư mục dữ liệu tạm, bất kể .env / DATABASE_URL của máy
  đang trỏ đi đâu. An toàn cả khi chạy nhầm trên server, và cho kết quả
  đồng nhất giữa các môi trường (điều kiện cần để CI ổn định).

Cách chạy:
    python3 run_tests.py
"""
import atexit
import os
import shutil
import sys
import tempfile

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_ROOT)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# ── Ép môi trường cô lập TRƯỚC KHI import app ──────────────────────────────
_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix='.db', prefix='pc06_test_')
os.close(_tmp_db_fd)
_tmp_data_dir = tempfile.mkdtemp(prefix='pc06_test_data_')

os.environ['DATABASE_URL'] = f'sqlite:///{_tmp_db_path}'
os.environ['PC06_DATA_DIR'] = _tmp_data_dir
os.environ['DEBUG'] = 'False'
os.environ['FLASK_ENV'] = 'testing'
# Mật khẩu admin bootstrap cố định (đủ policy) để init_db không in mật khẩu
# ngẫu nhiên ra log CI/server
os.environ['BOOTSTRAP_ADMIN_PASSWORD'] = 'Pc06Test!Admin#2026'
# Vô hiệu các cờ Passenger để storage.py không từ chối SQLite
# (chỉ có tác dụng nếu runner bị chạy trong shell có sẵn biến Passenger)
for _passenger_var in ('PC06_PASSENGER', 'PASSENGER_APP_ENV',
                       'PASSENGER_BASE_URI', 'PASSENGER_SPAWN_METHOD'):
    os.environ.pop(_passenger_var, None)
# Không cho tích hợp ngoài can thiệp khi test
os.environ['GOOGLE_FORMS_ENABLED'] = 'False'
# Báo cho tests/__init__.py biết đã cách ly rồi, khỏi tạo DB tạm thứ hai
os.environ['PC06_TEST_ISOLATED'] = '1'


def _cleanup():
    try:
        os.remove(_tmp_db_path)
    except OSError:
        pass
    shutil.rmtree(_tmp_data_dir, ignore_errors=True)


atexit.register(_cleanup)


def main():
    import unittest

    # Import app — init_db() chạy trên DB tạm ngay lúc import
    # (app.py gọi init_db trong app_context khi module được nạp).
    from app import app  # noqa: F401

    # Phòng thủ tầng 2: nếu một tầng nào đó (plugin/test cũ) đổi URI config
    # sau khi import, ép lại về DB tạm trước khi test chạy.
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{_tmp_db_path}'

    print(f'[run_tests] DB test dùng xong bỏ: {_tmp_db_path}')
    print(f'[run_tests] Thư mục dữ liệu tạm: {_tmp_data_dir}')

    loader = unittest.TestLoader()
    suite = loader.discover('tests', top_level_dir=APP_ROOT)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())

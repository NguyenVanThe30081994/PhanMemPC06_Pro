# -*- coding: utf-8 -*-
"""
Cách ly môi trường cho toàn bộ bộ test.

File này được nạp TRƯỚC mọi module test (kể cả khi chạy kiểu cũ
`python -m unittest discover tests`), nên đây là chốt chặn cuối cùng đảm bảo
test KHÔNG BAO GIỜ chạy trên database production: DATABASE_URL luôn bị ép về
một file SQLite tạm (dùng xong xóa), bất kể .env của máy/server trỏ đi đâu.

Nếu `run_tests.py` đã thiết lập cô lập rồi (flag PC06_TEST_ISOLATED=1)
thì bỏ qua, không tạo DB tạm thứ hai.
"""
import atexit
import os
import shutil
import sys
import tempfile

if os.environ.get('PC06_TEST_ISOLATED') != '1':
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _APP_ROOT not in sys.path:
        sys.path.insert(0, _APP_ROOT)

    _tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix='.db', prefix='pc06_test_')
    os.close(_tmp_db_fd)
    _tmp_data_dir = tempfile.mkdtemp(prefix='pc06_test_data_')

    os.environ['DATABASE_URL'] = f'sqlite:///{_tmp_db_path}'
    os.environ['PC06_DATA_DIR'] = _tmp_data_dir
    os.environ['DEBUG'] = 'False'
    os.environ['FLASK_ENV'] = 'testing'
    # Mật khẩu admin bootstrap cố định để init_db không in mật khẩu ngẫu nhiên ra log
    os.environ['BOOTSTRAP_ADMIN_PASSWORD'] = 'Pc06Test!Admin#2026'
    # Vô hiệu cờ Passenger (nếu shell có sẵn) để storage.py không từ chối SQLite
    for _passenger_var in ('PC06_PASSENGER', 'PASSENGER_APP_ENV',
                           'PASSENGER_BASE_URI', 'PASSENGER_SPAWN_METHOD'):
        os.environ.pop(_passenger_var, None)
    os.environ['GOOGLE_FORMS_ENABLED'] = 'False'
    os.environ['PC06_TEST_ISOLATED'] = '1'

    def _cleanup():
        try:
            os.remove(_tmp_db_path)
        except OSError:
            pass
        shutil.rmtree(_tmp_data_dir, ignore_errors=True)

    atexit.register(_cleanup)
    print(f'[tests] Chế độ cách ly: DB test dùng xong bỏ tại {_tmp_db_path}')

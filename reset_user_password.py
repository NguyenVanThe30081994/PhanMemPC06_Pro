#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import sys

from app import app
from models import db, User


def main():
    parser = argparse.ArgumentParser(
        description="Reset mật khẩu người dùng theo database đang cấu hình trong app."
    )
    parser.add_argument("--username", required=True, help="Tên tài khoản cần reset")
    parser.add_argument("--password", required=True, help="Mật khẩu mới")
    parser.add_argument(
        "--must-change",
        action="store_true",
        help="Đánh dấu bắt buộc đổi mật khẩu ở lần đăng nhập kế tiếp",
    )
    args = parser.parse_args()

    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if not user:
            print(f"Không tìm thấy tài khoản: {args.username}", file=sys.stderr)
            raise SystemExit(1)

        old_hash_len = len(user.password_hash or "")
        user.set_password(args.password)
        user.must_change_password = bool(args.must_change)
        db.session.commit()

        print("Reset mật khẩu thành công")
        print(f"- username: {user.username}")
        print(f"- old_hash_len: {old_hash_len}")
        print(f"- new_hash_len: {len(user.password_hash or '')}")
        print(f"- must_change_password: {user.must_change_password}")
        print(f"- db_uri: {app.config.get('SQLALCHEMY_DATABASE_URI')}")


if __name__ == "__main__":
    main()

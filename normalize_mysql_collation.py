#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from storage import _normalize_database_uri


def _validate_mysql_identifier(name):
    candidate = str(name or "").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", candidate):
        raise ValueError(f"Invalid identifier: {name!r}")
    return candidate


def normalize(target_url, apply=False, charset="utf8mb4", collation="utf8mb4_unicode_ci"):
    target_url = _normalize_database_uri(target_url)
    if not target_url:
        raise ValueError("Target DATABASE_URL is required")
    if not target_url.startswith(("mysql+pymysql://", "mariadb+pymysql://")):
        raise ValueError("Target database must be MySQL/MariaDB")

    engine = create_engine(
        target_url,
        connect_args={
            "charset": charset,
            "init_command": f"SET NAMES {charset} COLLATE {collation}",
        },
    )
    inspector = inspect(engine)
    url = make_url(target_url)
    db_name = url.database

    summary = {
        "database_altered": 0,
        "tables_seen": 0,
        "tables_altered": 0,
        "dry_run": 0 if apply else 1,
    }

    with engine.begin() as conn:
        if db_name:
            safe_db_name = _validate_mysql_identifier(db_name)
            sql = f"ALTER DATABASE `{safe_db_name}` CHARACTER SET {charset} COLLATE {collation}"
            print(sql)
            if apply:
                conn.exec_driver_sql(sql)
                summary["database_altered"] = 1

        for table_name in inspector.get_table_names():
            summary["tables_seen"] += 1
            safe_table_name = _validate_mysql_identifier(table_name)
            sql = f"ALTER TABLE `{safe_table_name}` CONVERT TO CHARACTER SET {charset} COLLATE {collation}"
            print(sql)
            if apply:
                conn.exec_driver_sql(sql)
                summary["tables_altered"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(description="Normalize all MySQL/MariaDB tables to utf8mb4 collation.")
    parser.add_argument("--target-url", default=os.environ.get("DATABASE_URL", ""), help="Target DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="Execute ALTER statements. Default is dry-run.")
    parser.add_argument("--charset", default="utf8mb4", help="Target character set")
    parser.add_argument("--collation", default="utf8mb4_unicode_ci", help="Target collation")
    args = parser.parse_args()

    summary = normalize(
        target_url=args.target_url,
        apply=args.apply,
        charset=args.charset,
        collation=args.collation,
    )
    print("COLLATION SUMMARY")
    for key, value in summary.items():
        print(f"  {key}={value}")


if __name__ == "__main__":
    main()

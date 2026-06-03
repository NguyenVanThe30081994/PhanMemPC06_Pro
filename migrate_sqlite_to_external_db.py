#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os

from sqlalchemy import MetaData, create_engine, inspect, select, text

from storage import _normalize_database_uri


def _row_batches(connection, table, chunk_size):
    result = connection.execute(select(table))
    while True:
        rows = result.fetchmany(chunk_size)
        if not rows:
            break
        yield [dict(row._mapping) for row in rows]


def migrate(source_sqlite_path, target_url, apply=False, chunk_size=500):
    source_path = os.path.abspath(source_sqlite_path)
    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)

    target_url = _normalize_database_uri(target_url)
    if not target_url:
        raise ValueError("Target DATABASE_URL is required")
    if target_url.startswith("sqlite:///"):
        raise ValueError("Target database must be MySQL/MariaDB, not SQLite")

    source_engine = create_engine(f"sqlite:///{source_path}")
    target_engine = create_engine(target_url)
    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_inspector = inspect(target_engine)
    target_meta = MetaData()

    summary = {
        "tables_seen": 0,
        "tables_created": 0,
        "tables_skipped_non_empty": 0,
        "rows_copied": 0,
        "rows_existing": 0,
    }

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for source_table in source_meta.sorted_tables:
            summary["tables_seen"] += 1
            table_name = source_table.name
            if table_name not in target_inspector.get_table_names():
                source_table.to_metadata(target_meta).create(bind=target_conn)
                summary["tables_created"] += 1
                target_inspector = inspect(target_engine)

            target_table = target_meta.tables.get(table_name)
            if target_table is None:
                target_meta.clear()
                target_meta.reflect(bind=target_engine, only=[table_name])
                target_table = target_meta.tables[table_name]

            source_total = source_conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
            existing_total = target_conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar() or 0
            summary["rows_existing"] += existing_total
            if existing_total:
                summary["tables_skipped_non_empty"] += 1
                print(f"SKIP table={table_name} existing_rows={existing_total} source_rows={source_total}")
                continue

            print(f"TABLE table={table_name} source_rows={source_total}")
            if not apply:
                continue

            copied = 0
            for batch in _row_batches(source_conn, source_table, chunk_size):
                if not batch:
                    continue
                target_conn.execute(target_table.insert(), batch)
                copied += len(batch)
            summary["rows_copied"] += copied
            print(f"  COPIED rows={copied}")
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Copy all tables from a SQLite database into the configured external MySQL/MariaDB database."
    )
    parser.add_argument("--source-sqlite", required=True, help="Path to source SQLite file")
    parser.add_argument("--target-url", default=os.environ.get("DATABASE_URL", ""), help="Target DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="Execute copy. Default is dry-run.")
    parser.add_argument("--chunk-size", type=int, default=500, help="Batch size for inserts")
    args = parser.parse_args()

    summary = migrate(
        source_sqlite_path=args.source_sqlite,
        target_url=args.target_url,
        apply=args.apply,
        chunk_size=max(1, args.chunk_size),
    )
    print("MIGRATION SUMMARY")
    for key, value in summary.items():
        print(f"  {key}={value}")
    print(f"  dry_run={0 if args.apply else 1}")


if __name__ == "__main__":
    main()

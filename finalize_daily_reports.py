#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from app import app
from routes.reporting import (
    _ensure_default_types,
    _ensure_report_schema,
    _finalize_due_daily_cycles_job,
)


def _print_summary(summary):
    print("DAILY REPORT FINALIZATION")
    print(f"  ran_at={summary.get('ran_at', '')}")
    print(f"  dry_run={int(bool(summary.get('dry_run')))}")
    print(f"  cycles_scanned={summary.get('cycles_scanned', 0)}")
    print(f"  daily_cycles_due={summary.get('daily_cycles_due', 0)}")
    print(f"  finalized_cycles={len(summary.get('finalized_cycle_ids', []))}")
    if summary.get("finalized_cycle_ids"):
        print(
            "  finalized_cycle_ids="
            + ",".join(str(cycle_id) for cycle_id in summary.get("finalized_cycle_ids", []))
        )
    print(f"  instances_with_data={summary.get('instances_with_data', 0)}")
    print(f"  instances_without_data={summary.get('instances_without_data', 0)}")
    print(f"  exports_generated={summary.get('exports_generated', 0)}")
    print(f"  exports_reused={summary.get('exports_reused', 0)}")
    for error in summary.get("errors", []):
        print(f"  error={error}")


def main():
    parser = argparse.ArgumentParser(
        description="Dong va xuat bao cao ngay da qua han."
    )
    parser.add_argument("--dry-run", action="store_true", help="Chi quet va thong ke, khong thay doi du lieu.")
    parser.add_argument("--cycle-id", type=int, help="Chi xu ly 1 cycle daily cu the.")
    args = parser.parse_args()

    with app.app_context():
        _ensure_report_schema()
        _ensure_default_types()
        summary = _finalize_due_daily_cycles_job(
            cycle_id=args.cycle_id,
            apply=not args.dry_run,
        )
        _print_summary(summary)


if __name__ == "__main__":
    main()

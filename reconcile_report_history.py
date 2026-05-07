#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from app import app
from models import db, ReportCycle, ReportInstance, ReportTemplateVersion
from routes.reporting import (
    _ensure_default_types,
    _ensure_report_schema,
    _materialize_effective_submission_export,
    _report_type,
)


def _bool_cycle_closed(cycle):
    return bool(cycle and (cycle.is_locked or cycle.status == "closed"))


def reconcile(
    apply=False,
    cycle_id=None,
    report_type_code=None,
    include_open=False,
    limit=None,
    overwrite=False,
):
    stats = {
        "cycles_scanned": 0,
        "cycles_skipped_open": 0,
        "instances_scanned": 0,
        "instances_with_data": 0,
        "instances_reused_export": 0,
        "exports_generated": 0,
        "export_errors": 0,
        "instances_without_data": 0,
    }

    cycles_query = ReportCycle.query.order_by(ReportCycle.id.asc())
    if cycle_id:
        cycles_query = cycles_query.filter(ReportCycle.id == cycle_id)
    cycles = cycles_query.all()

    if limit:
        cycles = cycles[:limit]

    for cycle in cycles:
        report_type = _report_type(cycle)
        if report_type_code and (not report_type or report_type.code != report_type_code):
            continue
        if not include_open and not _bool_cycle_closed(cycle):
            stats["cycles_skipped_open"] += 1
            continue

        template_version = db.session.get(ReportTemplateVersion, cycle.template_version_id)
        if not template_version:
            print(f"SKIP cycle={cycle.id} reason=missing_template_version")
            continue

        stats["cycles_scanned"] += 1
        instances = ReportInstance.query.filter_by(cycle_id=cycle.id).order_by(ReportInstance.id.asc()).all()
        print(
            f"CYCLE cycle={cycle.id} type={(report_type.code if report_type else 'unknown')} "
            f"status={cycle.status} locked={int(bool(cycle.is_locked))} instances={len(instances)}"
        )

        for instance in instances:
            stats["instances_scanned"] += 1
            result = _materialize_effective_submission_export(
                instance,
                cycle,
                template_version,
                report_type=report_type,
                overwrite=overwrite,
                apply=apply,
            )
            state = result["state"]
            latest_submission = result["latest_submission"]
            history = state["history"]

            if not latest_submission:
                stats["instances_without_data"] += 1
                print(
                    f"  INSTANCE instance={instance.id} unit={instance.org_unit or '-'} "
                    f"mode={state['mode']} submissions=0 effective_submission=none"
                )
                continue

            stats["instances_with_data"] += 1
            if result["error"]:
                stats["export_errors"] += 1
                print(
                    f"  INSTANCE instance={instance.id} unit={instance.org_unit or '-'} "
                    f"mode={state['mode']} submissions={len(history)} "
                    f"effective_submission={latest_submission.id} "
                    f"error={result['error']}"
                )
                continue
            if result["exported"]:
                stats["exports_generated"] += 1
            elif result["has_existing_export"]:
                stats["instances_reused_export"] += 1

            action = "scan"
            if result["exported"]:
                action = "exported"
            elif result["has_existing_export"]:
                action = "reused"
            elif result["needs_export"]:
                action = "pending_export"
            print(
                f"  INSTANCE instance={instance.id} unit={instance.org_unit or '-'} "
                f"mode={state['mode']} submissions={len(history)} "
                f"effective_submission={latest_submission.id} "
                f"effective_time={result['effective_time']} action={action}"
                f"{' export=' + result['export_path'] if result['export_path'] else ''}"
            )

        if apply:
            db.session.commit()

    print("SUMMARY")
    for key, value in stats.items():
        print(f"  {key}={value}")


def main():
    parser = argparse.ArgumentParser(
        description="Quet va reconcile du lieu bao cao lich su theo co che moi."
    )
    parser.add_argument("--apply", action="store_true", help="Ap dung ket qua reconcile vao du lieu")
    parser.add_argument("--cycle-id", type=int, help="Chi xu ly 1 cycle cu the")
    parser.add_argument(
        "--report-type",
        choices=["daily", "periodic", "ad_hoc"],
        help="Loc theo loai bao cao",
    )
    parser.add_argument(
        "--include-open",
        action="store_true",
        help="Bao gom ca nhung cycle chua dong",
    )
    parser.add_argument("--limit", type=int, help="Gioi han so cycle de quet")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi de lai tep da reconcile truoc do",
    )
    args = parser.parse_args()

    with app.app_context():
        _ensure_report_schema()
        _ensure_default_types()
        reconcile(
            apply=args.apply,
            cycle_id=args.cycle_id,
            report_type_code=args.report_type,
            include_open=args.include_open,
            limit=args.limit,
            overwrite=args.overwrite,
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import datetime

from app import app
from models import ReportCycle, ReportExportJob, ReportInstance, ReportSubmission, ReportTemplateVersion, db
from routes.reporting import _ensure_default_types, _ensure_report_schema, _report_type


def _cycle_template_id(cycle):
    version = db.session.get(ReportTemplateVersion, cycle.template_version_id) if cycle else None
    return version.template_id if version else None


def _instance_sort_key(instance):
    return (
        instance.report_unit_id or 0,
        instance.id or 0,
    )


def _build_target_instance(target_cycle, source_instance, target_period_id):
    return ReportInstance(
        template_id=source_instance.template_id,
        version_id=target_cycle.template_version_id,
        period_id=target_period_id,
        user_id=source_instance.user_id,
        org_unit=source_instance.org_unit,
        cycle_id=target_cycle.id,
        report_unit_id=source_instance.report_unit_id,
        assigned_user_id=source_instance.assigned_user_id,
        status=source_instance.status or "draft",
        opened_at=source_instance.opened_at,
        submitted_at=source_instance.submitted_at,
        reviewed_at=source_instance.reviewed_at,
        locked_at=source_instance.locked_at,
        locked_by=source_instance.locked_by,
        note=source_instance.note,
    )


def merge_daily_cycles(target_cycle_id, source_cycle_ids, apply=False, close_sources=True):
    target_cycle = db.session.get(ReportCycle, target_cycle_id)
    if not target_cycle:
        raise ValueError(f"Target cycle {target_cycle_id} not found")

    target_report_type = _report_type(target_cycle)
    if not target_report_type or target_report_type.code != "daily":
        raise ValueError(f"Target cycle {target_cycle_id} is not a daily cycle")

    target_template_id = _cycle_template_id(target_cycle)
    source_cycles = []
    for cycle_id in source_cycle_ids:
        cycle = db.session.get(ReportCycle, cycle_id)
        if not cycle:
            raise ValueError(f"Source cycle {cycle_id} not found")
        report_type = _report_type(cycle)
        if not report_type or report_type.code != "daily":
            raise ValueError(f"Source cycle {cycle_id} is not a daily cycle")
        if _cycle_template_id(cycle) != target_template_id:
            raise ValueError(f"Source cycle {cycle_id} does not belong to the same template as target cycle {target_cycle_id}")
        source_cycles.append(cycle)

    source_cycles = sorted(source_cycles, key=lambda item: ((item.open_at or item.created_at or datetime.min), item.id))

    target_instances = {
        instance.report_unit_id: instance
        for instance in ReportInstance.query.filter_by(cycle_id=target_cycle.id).all()
        if instance.report_unit_id
    }
    target_period_id = target_cycle.legacy_period_id

    summary = {
        "target_cycle_id": target_cycle.id,
        "source_cycle_ids": [cycle.id for cycle in source_cycles],
        "instances_created": 0,
        "instances_reused": 0,
        "submissions_moved": 0,
        "export_jobs_relinked": 0,
        "source_cycles_closed": 0,
        "source_instances_seen": 0,
        "source_instances_with_submissions": 0,
    }

    for source_cycle in source_cycles:
        instances = ReportInstance.query.filter_by(cycle_id=source_cycle.id).order_by(ReportInstance.report_unit_id.asc()).all()
        for source_instance in instances:
            summary["source_instances_seen"] += 1
            submissions = (
                ReportSubmission.query.filter_by(instance_id=source_instance.id)
                .order_by(ReportSubmission.version_no.asc(), ReportSubmission.created_at.asc(), ReportSubmission.id.asc())
                .all()
            )
            if submissions:
                summary["source_instances_with_submissions"] += 1

            target_instance = target_instances.get(source_instance.report_unit_id)
            if target_instance is None:
                target_instance = _build_target_instance(target_cycle, source_instance, target_period_id)
                db.session.add(target_instance)
                db.session.flush()
                target_instances[source_instance.report_unit_id] = target_instance
                summary["instances_created"] += 1
            else:
                summary["instances_reused"] += 1

            if source_instance.submitted_at and (
                not target_instance.submitted_at or source_instance.submitted_at > target_instance.submitted_at
            ):
                target_instance.submitted_at = source_instance.submitted_at
            if source_instance.locked_at and (
                not target_instance.locked_at or source_instance.locked_at > target_instance.locked_at
            ):
                target_instance.locked_at = source_instance.locked_at
            if source_instance.reviewed_at and (
                not target_instance.reviewed_at or source_instance.reviewed_at > target_instance.reviewed_at
            ):
                target_instance.reviewed_at = source_instance.reviewed_at
            if source_instance.status == "submitted" or target_instance.status != "submitted":
                target_instance.status = source_instance.status or target_instance.status

            if source_instance.id == target_instance.id:
                continue

            for submission in submissions:
                submission.instance_id = target_instance.id
                submission.period_id = target_instance.period_id or submission.period_id
                summary["submissions_moved"] += 1

        if close_sources:
            source_cycle.status = "closed"
            source_cycle.is_locked = True
            if not source_cycle.close_at:
                source_cycle.close_at = datetime.now()
            summary["source_cycles_closed"] += 1
        export_jobs = ReportExportJob.query.filter_by(cycle_id=source_cycle.id).all()
        for export_job in export_jobs:
            export_job.cycle_id = target_cycle.id
            summary["export_jobs_relinked"] += 1

    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Hop nhat nhieu cycle daily thanh 1 cycle de xem luu ke theo ngay."
    )
    parser.add_argument("--target-cycle-id", type=int, required=True, help="Cycle dich se giu lai du lieu")
    parser.add_argument(
        "--source-cycle-ids",
        type=int,
        nargs="+",
        required=True,
        help="Danh sach cycle nguon can chuyen du lieu vao cycle dich",
    )
    parser.add_argument("--apply", action="store_true", help="Thuc hien thay doi. Mac dinh la dry-run.")
    parser.add_argument(
        "--keep-sources-open",
        action="store_true",
        help="Khong dong cac cycle nguon sau khi hop nhat",
    )
    args = parser.parse_args()

    with app.app_context():
        _ensure_report_schema()
        _ensure_default_types()
        summary = merge_daily_cycles(
            target_cycle_id=args.target_cycle_id,
            source_cycle_ids=args.source_cycle_ids,
            apply=args.apply,
            close_sources=not args.keep_sources_open,
        )
        print("MERGE DAILY CYCLES")
        for key, value in summary.items():
            print(f"  {key}={value}")
        print(f"  dry_run={0 if args.apply else 1}")


if __name__ == "__main__":
    main()

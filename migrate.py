# -*- coding: utf-8 -*-
"""
Migration and backfill entrypoint for PC06.

Supports:
- Core schema safeguards via utils.apply_migrations
- Runtime backfill for task_participant / task_submission / task_item
- Dry-run summary before applying changes
"""

import argparse

from app import app
from models import Task, TaskItem, TaskParticipant, TaskSubmission
from routes.tasks import _backfill_task_runtime_models, _query_task_scope, _task_runtime_expected_counts
from utils import apply_migrations


def _task_runtime_snapshot():
    snapshot = {
        "tasks": 0,
        "participant_rows": 0,
        "submission_rows": 0,
        "task_item_rows": 0,
        "tasks_missing_runtime": 0,
        "sample_missing_tasks": [],
    }
    for task in Task.query.order_by(Task.id.asc()).all():
        snapshot["tasks"] += 1
        expected = _task_runtime_expected_counts(task)
        task_item_count = TaskItem.query.filter_by(task_id=task.id).count() if not getattr(task, "parent_task_id", None) else 0
        participant_count = _query_task_scope(TaskParticipant, task).filter(
            TaskParticipant.participant_type == "executor",
            TaskParticipant.is_active.is_(True),
        ).count()
        submission_count = _query_task_scope(TaskSubmission, task).count()

        snapshot["participant_rows"] += participant_count
        snapshot["submission_rows"] += submission_count
        snapshot["task_item_rows"] += task_item_count

        missing = (
            (expected["task_items"] and task_item_count < expected["task_items"])
            or
            (expected["executor_participants"] and participant_count < expected["executor_participants"])
            or (expected["submissions"] and submission_count < expected["submissions"])
        )
        if missing:
            snapshot["tasks_missing_runtime"] += 1
            if len(snapshot["sample_missing_tasks"]) < 10:
                snapshot["sample_missing_tasks"].append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "expected_task_items": expected["task_items"],
                        "actual_task_items": task_item_count,
                        "expected_participants": expected["executor_participants"],
                        "actual_participants": participant_count,
                        "expected_submissions": expected["submissions"],
                        "actual_submissions": submission_count,
                    }
                )
    return snapshot


def _print_snapshot(title, snapshot):
    print("=" * 72)
    print(title)
    print("=" * 72)
    print(f"- Tasks scanned: {snapshot['tasks']}")
    print(f"- Executor participants: {snapshot['participant_rows']}")
    print(f"- Submission rows: {snapshot['submission_rows']}")
    print(f"- Task items: {snapshot['task_item_rows']}")
    print(f"- Tasks still missing runtime rows: {snapshot['tasks_missing_runtime']}")
    if snapshot["sample_missing_tasks"]:
        print("- Sample tasks still missing runtime rows:")
        for item in snapshot["sample_missing_tasks"]:
            print(
                "  "
                f"#{item['id']} {item['title']} | "
                f"task_items {item['actual_task_items']}/{item['expected_task_items']} | "
                f"participants {item['actual_participants']}/{item['expected_participants']} | "
                f"submissions {item['actual_submissions']}/{item['expected_submissions']} | "
            )


def migrate(batch_size=250, dry_run=False, skip_task_runtime=False):
    with app.app_context():
        print("=" * 72)
        print("PC06 MIGRATION")
        print("=" * 72)

        apply_migrations(app)
        before = _task_runtime_snapshot()
        _print_snapshot("Task runtime snapshot before backfill", before)

        if dry_run:
            print("\nDry-run only. No data was changed.")
            return

        if skip_task_runtime:
            print("\nSkipped task runtime backfill by request.")
            return

        print("\nRunning task runtime backfill...")
        result = _backfill_task_runtime_models(batch_size=batch_size)
        print(
            f"- Backfill scanned: {result.get('scanned', 0)}\n"
            f"- Backfill changed: {result.get('changed', 0)}"
        )

        after = _task_runtime_snapshot()
        _print_snapshot("Task runtime snapshot after backfill", after)
        print("\nMigration completed.")


def main():
    parser = argparse.ArgumentParser(description="Run PC06 schema migration and runtime backfill.")
    parser.add_argument("--batch-size", type=int, default=250, help="Task backfill batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Only print migration/runtime summary.")
    parser.add_argument("--skip-task-runtime", action="store_true", help="Skip task runtime backfill.")
    args = parser.parse_args()
    migrate(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        skip_task_runtime=args.skip_task_runtime,
    )


if __name__ == "__main__":
    main()

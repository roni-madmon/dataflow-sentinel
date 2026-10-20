from pathlib import Path
from datetime import datetime, timezone
import json

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_GLOB = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "batch_tasks"
    / "part-*.parquet"
)

REPORT_DIR = PROJECT_ROOT / "data" / "validation"
REPORT_PATH = REPORT_DIR / "feature_availability_report.json"

RAW_GLOB_SQL = RAW_GLOB.as_posix().replace("'", "''")


def audit_feature_availability() -> None:
    con = duckdb.connect()

    print("Auditing pre-run feature availability...")
    print()

    overall = con.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
            ) AS waiting_prestart_rows,

            COUNT(DISTINCT job_name) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
            ) AS jobs_with_waiting_prestart,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
                  AND plan_cpu IS NULL
            ) AS waiting_missing_plan_cpu,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
                  AND plan_mem IS NULL
            ) AS waiting_missing_plan_mem,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
                  AND instance_num IS NULL
            ) AS waiting_missing_instance_num,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(status)) = 'waiting'
                  AND start_time = 0
                  AND task_type IS NULL
            ) AS waiting_missing_task_type

        FROM read_parquet('{RAW_GLOB_SQL}')
        """
    ).fetchone()

    (
        total_rows,
        waiting_prestart_rows,
        jobs_with_waiting_prestart,
        waiting_missing_plan_cpu,
        waiting_missing_plan_mem,
        waiting_missing_instance_num,
        waiting_missing_task_type,
    ) = overall

    print("=" * 70)
    print("FEATURE AVAILABILITY AUDIT")
    print("=" * 70)
    print()
    print(f"Total Task rows: {total_rows:,}")
    print(f"Waiting/pre-start Task rows: {waiting_prestart_rows:,}")
    print(f"Jobs with waiting/pre-start Tasks: {jobs_with_waiting_prestart:,}")
    print()

    if waiting_prestart_rows == 0:
        print("No waiting/pre-start proxy rows were found.")
        print("Dataset cannot provide empirical support for pre-run availability.")
    else:
        def pct(value: int) -> float:
            return value / waiting_prestart_rows * 100

        print("Missing values inside waiting/pre-start Tasks")
        print("-" * 70)
        print(
            f"plan_cpu:     {waiting_missing_plan_cpu:,} "
            f"({pct(waiting_missing_plan_cpu):.4f}%)"
        )
        print(
            f"plan_mem:     {waiting_missing_plan_mem:,} "
            f"({pct(waiting_missing_plan_mem):.4f}%)"
        )
        print(
            f"instance_num: {waiting_missing_instance_num:,} "
            f"({pct(waiting_missing_instance_num):.4f}%)"
        )
        print(
            f"task_type:    {waiting_missing_task_type:,} "
            f"({pct(waiting_missing_task_type):.4f}%)"
        )

    evidence = {
        "plan_cpu_observed_prestart":
            waiting_prestart_rows > waiting_missing_plan_cpu,
        "plan_mem_observed_prestart":
            waiting_prestart_rows > waiting_missing_plan_mem,
        "instance_num_observed_prestart":
            waiting_prestart_rows > waiting_missing_instance_num,
        "task_type_observed_prestart":
            waiting_prestart_rows > waiting_missing_task_type,
    }

    print()
    print("EVIDENCE")
    print("-" * 70)

    for name, value in evidence.items():
        print(f"{name}: {'YES' if value else 'NO'}")

    print()
    print("IMPORTANT LIMITATION")
    print("-" * 70)
    print(
        "Waiting tasks with start_time=0 are used only as a proxy for "
        "pre-execution availability."
    )
    print(
        "The dataset has no independent feature-observation timestamp, "
        "so this audit provides evidence but not absolute proof."
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "pre_run_feature_availability_proxy",
        "proxy_definition": "task_status=waiting AND start_time=0",
        "total_task_rows": total_rows,
        "waiting_prestart_rows": waiting_prestart_rows,
        "jobs_with_waiting_prestart": jobs_with_waiting_prestart,
        "waiting_prestart_missing": {
            "plan_cpu": waiting_missing_plan_cpu,
            "plan_mem": waiting_missing_plan_mem,
            "instance_num": waiting_missing_instance_num,
            "task_type": waiting_missing_task_type,
        },
        "evidence": evidence,
        "limitation": (
            "The source contains no independent feature-observation timestamp. "
            "Waiting/pre-start rows provide supporting evidence only."
        ),
    }

    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print()
    print(f"Report saved to: {REPORT_PATH}")

    con.close()


if __name__ == "__main__":
    audit_feature_availability()

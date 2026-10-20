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
REPORT_PATH = REPORT_DIR / "job_run_contract_report.json"

RAW_GLOB_SQL = RAW_GLOB.as_posix().replace("'", "''")


def validate_job_run_contract() -> None:
    con = duckdb.connect()

    print("Validating Job Run contract...")
    print()

    # ---------------------------------------------------------
    # 1. Validate Task -> Job grain
    # ---------------------------------------------------------

    grain = con.execute(
        f"""
        SELECT
            COUNT(*) AS total_task_rows,
            COUNT(DISTINCT job_name) AS unique_job_names,

            COUNT(
                DISTINCT ROW(job_name, task_name)
            ) AS unique_job_task_pairs,

            SUM(
                CASE WHEN job_name IS NULL OR TRIM(CAST(job_name AS VARCHAR)) = ''
                THEN 1 ELSE 0 END
            ) AS missing_job_name,

            SUM(
                CASE WHEN task_name IS NULL OR TRIM(CAST(task_name AS VARCHAR)) = ''
                THEN 1 ELSE 0 END
            ) AS missing_task_name

        FROM read_parquet('{RAW_GLOB_SQL}')
        """
    ).fetchone()

    (
        total_task_rows,
        unique_job_names,
        unique_job_task_pairs,
        missing_job_name,
        missing_task_name,
    ) = grain

    if total_task_rows == 0:
        con.close()
        raise SystemExit("No task rows found; contract validation failed.")

    duplicate_job_task_pairs = con.execute(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT
                job_name,
                task_name,
                COUNT(*) AS row_count
            FROM read_parquet('{RAW_GLOB_SQL}')
            GROUP BY
                job_name,
                task_name
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    # ---------------------------------------------------------
    # 2. Build Job-run level classification
    # ---------------------------------------------------------

    job_summary = con.execute(
        f"""
        WITH job_runs AS (
            SELECT
                job_name AS job_run_id,

                COUNT(*) AS task_count,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'failed'
                    THEN 1 ELSE 0 END
                ) AS failed_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'running'
                    THEN 1 ELSE 0 END
                ) AS running_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'waiting'
                    THEN 1 ELSE 0 END
                ) AS waiting_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'terminated'
                    THEN 1 ELSE 0 END
                ) AS terminated_tasks,

                MIN(
                    CASE
                        WHEN LOWER(TRIM(status)) = 'waiting' AND start_time = 0
                            THEN NULL
                        ELSE start_time
                    END
                ) AS run_start_time,
                MAX(end_time) AS run_end_time

            FROM read_parquet('{RAW_GLOB_SQL}')

            GROUP BY job_name
        )

        SELECT
            COUNT(*) AS total_job_runs,

            SUM(
                CASE
                    WHEN failed_tasks > 0
                    THEN 1
                    ELSE 0
                END
            ) AS failed_job_runs,

            SUM(
                CASE
                    WHEN failed_tasks = 0
                    AND running_tasks = 0
                    AND waiting_tasks = 0
                    AND terminated_tasks = task_count
                    THEN 1
                    ELSE 0
                END
            ) AS successful_job_runs,

            SUM(
                CASE
                    WHEN failed_tasks = 0
                    AND terminated_tasks < task_count
                    THEN 1
                    ELSE 0
                END
            ) AS unresolved_job_runs,

            SUM(
                CASE
                    WHEN failed_tasks > 0
                    AND (
                        running_tasks > 0
                        OR waiting_tasks > 0
                    )
                    THEN 1
                    ELSE 0
                END
            ) AS failed_jobs_with_unresolved_tasks,

            SUM(
                CASE
                    WHEN run_start_time IS NULL
                    THEN 1
                    ELSE 0
                END
            ) AS jobs_missing_run_start

        FROM job_runs
        """
    ).fetchone()

    (
        total_job_runs,
        failed_job_runs,
        successful_job_runs,
        unresolved_job_runs,
        failed_jobs_with_unresolved_tasks,
        jobs_missing_run_start,
    ) = job_summary

    eligible_model_jobs = (
        failed_job_runs
        + successful_job_runs
    )

    failure_rate = (
        failed_job_runs / eligible_model_jobs
        if eligible_model_jobs
        else None
    )

    # ---------------------------------------------------------
    # 3. Check timestamp availability for labeled Jobs
    # ---------------------------------------------------------

    labeled_time_summary = con.execute(
        f"""
        WITH job_runs AS (
            SELECT
                job_name,
                COUNT(*) AS task_count,
                SUM(CASE WHEN LOWER(TRIM(status)) = 'terminated'
                    THEN 1 ELSE 0 END) AS terminated_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'failed'
                    THEN 1 ELSE 0 END
                ) AS failed_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'running'
                    THEN 1 ELSE 0 END
                ) AS running_tasks,

                SUM(
                    CASE WHEN LOWER(TRIM(status)) = 'waiting'
                    THEN 1 ELSE 0 END
                ) AS waiting_tasks,

                MIN(
                    CASE
                        WHEN LOWER(TRIM(status)) = 'waiting' AND start_time = 0
                            THEN NULL
                        ELSE start_time
                    END
                ) AS run_start_time

            FROM read_parquet('{RAW_GLOB_SQL}')

            GROUP BY job_name
        ),

        labeled AS (
            SELECT *
            FROM job_runs

            WHERE
                failed_tasks > 0

                OR (
                    failed_tasks = 0
                    AND running_tasks = 0
                    AND waiting_tasks = 0
                    AND terminated_tasks = task_count
                )
        )

        SELECT
            COUNT(*) FILTER (WHERE run_start_time IS NULL),
            COUNT(*) FILTER (WHERE run_start_time <= 0)
        FROM labeled
        """
    ).fetchone()
    labeled_missing_start, labeled_nonpositive_start = labeled_time_summary

    # ---------------------------------------------------------
    # 4. Contract checks
    # ---------------------------------------------------------

    unknown_status_rows = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{RAW_GLOB_SQL}')
        WHERE status IS NULL
           OR LOWER(TRIM(status)) NOT IN
               ('failed', 'terminated', 'running', 'waiting')
        """
    ).fetchone()[0]

    checks = {
        "task_status_values_known": unknown_status_rows == 0,
        "target_partition_complete": (
            failed_job_runs + successful_job_runs + unresolved_job_runs
            == total_job_runs
        ),
        "job_name_not_null_or_blank": missing_job_name == 0,
        "task_name_not_null_or_blank": missing_task_name == 0,
        "job_task_pair_unique": duplicate_job_task_pairs == 0,
        "aggregation_matches_unique_jobs":
            total_job_runs == unique_job_names,
        "target_has_positive_examples":
            failed_job_runs > 0,
        "target_has_negative_examples":
            successful_job_runs > 0,
        "labeled_jobs_have_split_timestamp":
            labeled_missing_start == 0,
    }

    # ---------------------------------------------------------
    # 5. Print report
    # ---------------------------------------------------------

    print("=" * 70)
    print("JOB RUN CONTRACT REPORT")
    print("=" * 70)

    print()
    print("GRAIN")
    print("-" * 70)

    print(f"Task rows: {total_task_rows:,}")
    print(f"Unique job_name values: {unique_job_names:,}")
    print(
        f"Unique (job_name, task_name) pairs: "
        f"{unique_job_task_pairs:,}"
    )
    print(
        f"Duplicate (job_name, task_name) pairs: "
        f"{duplicate_job_task_pairs:,}"
    )

    print()
    print("TARGET")
    print("-" * 70)

    print(f"Total Job runs: {total_job_runs:,}")
    print(f"Failed Job runs: {failed_job_runs:,}")
    print(
        f"Successful Job runs: "
        f"{successful_job_runs:,}"
    )
    print(
        f"Unresolved Job runs: "
        f"{unresolved_job_runs:,}"
    )

    print(
        f"Eligible modeling Jobs: "
        f"{eligible_model_jobs:,}"
    )

    if failure_rate is not None:
        print(
            f"Job-level failure rate: "
            f"{failure_rate:.4%}"
        )

    print()
    print("TEMPORAL INFORMATION")
    print("-" * 70)

    print(
        f"Jobs missing run_start_time: "
        f"{jobs_missing_run_start:,}"
    )

    print(
        "run_start_time will be used for chronological "
        "ordering / Temporal Split only."
    )

    print(
        "start_time and end_time are NOT model features."
    )

    print()
    print("CONTRACT CHECKS")
    print("-" * 70)

    for check_name, passed in checks.items():
        status = "PASS" if passed else "FAIL"

        print(
            f"{check_name}: {status}"
        )

    all_passed = all(checks.values())

    print()
    print("=" * 70)

    if all_passed:
        print("JOB RUN CONTRACT: PASS")
    else:
        print("JOB RUN CONTRACT: FAIL")

    print("=" * 70)

    # ---------------------------------------------------------
    # 6. Save machine-readable evidence
    # ---------------------------------------------------------

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "structural_grain_and_target_rules",
        "unverified_assumptions": [
            "job_name identifies one execution; uniqueness checks alone do not establish this",
            "all model inputs are available before job start",
        ],
        "grain": {
            "missing_or_blank_job_names": missing_job_name,
            "missing_or_blank_task_names": missing_task_name,
            "unknown_status_rows": unknown_status_rows,
            "total_task_rows": total_task_rows,
            "unique_job_names": unique_job_names,
            "unique_job_task_pairs":
                unique_job_task_pairs,
            "duplicate_job_task_pairs":
                duplicate_job_task_pairs,
        },
        "target": {
            "total_job_runs": total_job_runs,
            "failed_job_runs": failed_job_runs,
            "successful_job_runs":
                successful_job_runs,
            "unresolved_job_runs":
                unresolved_job_runs,
            "eligible_model_jobs":
                eligible_model_jobs,
            "job_failure_rate":
                failure_rate,
        },
        "temporal": {
            "labeled_jobs_nonpositive_start": labeled_nonpositive_start,
            "nonpositive_start_policy": "exclude from chronological modeling splits",
            "labeled_jobs_missing_run_start":
                labeled_missing_start,
            "split_timestamp":
                "minimum task start_time, ignoring waiting tasks with start_time=0",
            "timestamp_usage":
                "temporal ordering only - not a model feature",
        },
        "decisions": {
            "job_run_id":
                "job_name for this dataset",
            "positive_target":
                "at least one Failed task",
            "negative_target":
                "all tasks terminal-successful",
            "unresolved_policy":
                "exclude all jobs without a known positive or negative target",
            "raw_job_name_model_feature":
                False,
            "start_time_model_feature":
                False,
            "end_time_model_feature":
                False,
            "stable_logical_job_key":
                None,
            "historical_features_enabled":
                False,
        },
        "checks": checks,
        "contract_passed": all_passed,
    }

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=2,
        )

    print()
    print(
        f"Report saved to: "
        f"{REPORT_PATH}"
    )

    con.close()

    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    validate_job_run_contract()
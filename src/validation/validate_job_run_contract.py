from pathlib import Path
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

RAW_GLOB_SQL = RAW_GLOB.as_posix()


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
                DISTINCT job_name || '|' || task_name
            ) AS unique_job_task_pairs,

            SUM(
                CASE WHEN job_name IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_job_name,

            SUM(
                CASE WHEN task_name IS NULL
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
                    CASE WHEN status = 'Failed'
                    THEN 1 ELSE 0 END
                ) AS failed_tasks,

                SUM(
                    CASE WHEN status = 'Running'
                    THEN 1 ELSE 0 END
                ) AS running_tasks,

                SUM(
                    CASE WHEN status = 'Waiting'
                    THEN 1 ELSE 0 END
                ) AS waiting_tasks,

                SUM(
                    CASE WHEN status = 'Terminated'
                    THEN 1 ELSE 0 END
                ) AS terminated_tasks,

                MIN(start_time) AS run_start_time,
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
                    AND (
                        running_tasks > 0
                        OR waiting_tasks > 0
                    )
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

    labeled_missing_start = con.execute(
        f"""
        WITH job_runs AS (
            SELECT
                job_name,

                SUM(
                    CASE WHEN status = 'Failed'
                    THEN 1 ELSE 0 END
                ) AS failed_tasks,

                SUM(
                    CASE WHEN status = 'Running'
                    THEN 1 ELSE 0 END
                ) AS running_tasks,

                SUM(
                    CASE WHEN status = 'Waiting'
                    THEN 1 ELSE 0 END
                ) AS waiting_tasks,

                MIN(start_time) AS run_start_time

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
                )
        )

        SELECT COUNT(*)
        FROM labeled
        WHERE run_start_time IS NULL
        """
    ).fetchone()[0]

    # ---------------------------------------------------------
    # 4. Contract checks
    # ---------------------------------------------------------

    checks = {
        "job_name_not_null": missing_job_name == 0,
        "task_name_not_null": missing_task_name == 0,
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
        "grain": {
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
            "labeled_jobs_missing_run_start":
                labeled_missing_start,
            "split_timestamp":
                "minimum task start_time",
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
                "exclude jobs with Running/Waiting and no failure",
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


if __name__ == "__main__":
    validate_job_run_contract()
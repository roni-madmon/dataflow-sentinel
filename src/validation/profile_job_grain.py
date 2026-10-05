from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_GLOB = (
    PROJECT_ROOT / "data" / "raw" / "batch_tasks" / "part-*.parquet"
)

RAW_GLOB_SQL = RAW_GLOB.as_posix()


def profile_job_grain() -> None:
    con = duckdb.connect()

    print("Profiling Job grain...")
    print()

    grain_summary = con.execute(
        f"""
        SELECT
            COUNT(*) AS total_task_rows,
            COUNT(DISTINCT job_name) AS unique_jobs,
            COUNT(
                DISTINCT job_name || '|' || task_name
            ) AS unique_job_task_pairs
        FROM read_parquet('{RAW_GLOB_SQL}')
        """
    ).fetchdf()

    print("=" * 70)
    print("TASK / JOB GRAIN SUMMARY")
    print("=" * 70)
    print(grain_summary.to_string(index=False))

    print()

    duplicate_pairs = con.execute(
        f"""
        SELECT
            COUNT(*) AS duplicate_job_task_pairs
        FROM (
            SELECT
                job_name,
                task_name,
                COUNT(*) AS row_count
            FROM read_parquet('{RAW_GLOB_SQL}')
            GROUP BY job_name, task_name
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    print(
        f"Duplicate (job_name, task_name) pairs: "
        f"{duplicate_pairs:,}"
    )

    print()

    job_summary = con.execute(
        f"""
        WITH jobs AS (
            SELECT
                job_name,
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
                ) AS terminated_tasks

            FROM read_parquet('{RAW_GLOB_SQL}')
            GROUP BY job_name
        )

        SELECT
            COUNT(*) AS total_jobs,

            SUM(
                CASE WHEN failed_tasks > 0
                THEN 1 ELSE 0 END
            ) AS jobs_with_failure,

            SUM(
                CASE
                    WHEN failed_tasks = 0
                    AND running_tasks = 0
                    AND waiting_tasks = 0
                    THEN 1
                    ELSE 0
                END
            ) AS completed_success_jobs,

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
            ) AS unresolved_jobs,

            MIN(task_count) AS min_tasks_per_job,
            AVG(task_count) AS avg_tasks_per_job,
            MAX(task_count) AS max_tasks_per_job

        FROM jobs
        """
    ).fetchdf()

    print("=" * 70)
    print("JOB STATUS SUMMARY")
    print("=" * 70)
    print(job_summary.to_string(index=False))

    print()
    print("Job-grain profiling completed.")

    con.close()


if __name__ == "__main__":
    profile_job_grain()
from pathlib import Path
import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_GLOB = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "batch_tasks"
    / "part-*.parquet"
)

RAW_GLOB_SQL = RAW_GLOB.as_posix().replace("'", "''")


def main():
    con = duckdb.connect()

    result = con.execute(
        f"""
        WITH job_summary AS (
            SELECT
                job_name,

                COUNT(*) AS total_tasks,

                COUNT(*) FILTER (
                    WHERE LOWER(TRIM(status)) = 'waiting'
                      AND start_time = 0
                ) AS prestart_waiting_tasks,

                COUNT(*) FILTER (
                    WHERE LOWER(TRIM(status)) = 'failed'
                ) AS failed_tasks,

                COUNT(*) FILTER (
                    WHERE LOWER(TRIM(status)) = 'terminated'
                ) AS terminated_tasks,

                COUNT(*) FILTER (
                    WHERE LOWER(TRIM(status)) = 'running'
                ) AS running_tasks,

                COUNT(*) FILTER (
                    WHERE task_type IS NULL
                ) AS missing_task_type_all,

                COUNT(*) FILTER (
                    WHERE LOWER(TRIM(status)) = 'waiting'
                      AND start_time = 0
                      AND task_type IS NULL
                ) AS missing_task_type_prestart

            FROM read_parquet('{RAW_GLOB_SQL}')

            GROUP BY job_name
        )

        SELECT
            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
            ) AS jobs_with_prestart_waiting,

            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
                  AND prestart_waiting_tasks = total_tasks
            ) AS jobs_fully_waiting_prestart,

            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
                  AND prestart_waiting_tasks < total_tasks
            ) AS jobs_mixed_state,

            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
                  AND failed_tasks > 0
            ) AS waiting_jobs_with_failed_tasks,

            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
                  AND terminated_tasks > 0
            ) AS waiting_jobs_with_terminated_tasks,

            COUNT(*) FILTER (
                WHERE prestart_waiting_tasks > 0
                  AND running_tasks > 0
            ) AS waiting_jobs_with_running_tasks

        FROM job_summary
        """
    ).fetchone()

    (
        jobs_with_prestart_waiting,
        jobs_fully_waiting_prestart,
        jobs_mixed_state,
        waiting_jobs_with_failed_tasks,
        waiting_jobs_with_terminated_tasks,
        waiting_jobs_with_running_tasks,
    ) = result

    print("=" * 70)
    print("PRE-RUN JOB SNAPSHOT AUDIT")
    print("=" * 70)

    print(f"Jobs with waiting/start_time=0 Tasks: {jobs_with_prestart_waiting:,}")
    print(f"Jobs where ALL Tasks are waiting/pre-start: {jobs_fully_waiting_prestart:,}")
    print(f"Jobs with mixed execution state: {jobs_mixed_state:,}")
    print()

    print("Among Jobs containing pre-start Tasks:")
    print(f"Also contain failed Tasks:     {waiting_jobs_with_failed_tasks:,}")
    print(f"Also contain terminated Tasks: {waiting_jobs_with_terminated_tasks:,}")
    print(f"Also contain running Tasks:    {waiting_jobs_with_running_tasks:,}")

    print()
    print("=" * 70)
    print("FEATURE MISSINGNESS BY STATUS")
    print("=" * 70)

    rows = con.execute(
        f"""
        SELECT
            LOWER(TRIM(status)) AS status,
            COUNT(*) AS rows,

            COUNT(*) FILTER (WHERE plan_cpu IS NULL) AS missing_plan_cpu,
            COUNT(*) FILTER (WHERE plan_mem IS NULL) AS missing_plan_mem,
            COUNT(*) FILTER (WHERE instance_num IS NULL) AS missing_instance_num,
            COUNT(*) FILTER (WHERE task_type IS NULL) AS missing_task_type

        FROM read_parquet('{RAW_GLOB_SQL}')

        GROUP BY LOWER(TRIM(status))
        ORDER BY status
        """
    ).fetchall()

    for row in rows:
        status, n, cpu, mem, inst, task_type = row

        print()
        print(f"Status: {status}")
        print(f"Rows: {n:,}")
        print(f"plan_cpu missing:     {cpu:,} ({cpu/n:.2%})")
        print(f"plan_mem missing:     {mem:,} ({mem/n:.2%})")
        print(f"instance_num missing: {inst:,} ({inst/n:.2%})")
        print(f"task_type missing:    {task_type:,} ({task_type/n:.2%})")

    con.close()


if __name__ == "__main__":
    main()

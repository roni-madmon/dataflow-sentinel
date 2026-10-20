from __future__ import annotations

import argparse
import os
from io import StringIO
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BRONZE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "batch_tasks"
)

ENV_PATH = PROJECT_ROOT / ".env"


POSTGRES_COLUMNS = [
    "task_name",
    "instance_num",
    "job_name",
    "task_type",
    "status",
    "start_time",
    "end_time",
    "plan_cpu",
    "plan_mem",
    "ingestion_run_id",
    "ingested_at_utc",
]


def get_connection() -> psycopg.Connection:
    load_dotenv(ENV_PATH)

    return psycopg.connect(
        host="localhost",
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def create_table(
    connection: psycopg.Connection,
) -> None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE SCHEMA IF NOT EXISTS staging;

            CREATE TABLE IF NOT EXISTS staging.batch_tasks_source (
                task_name TEXT NOT NULL,
                instance_num BIGINT,
                job_name TEXT NOT NULL,
                task_type BIGINT,
                status TEXT,
                start_time BIGINT,
                end_time BIGINT,
                plan_cpu DOUBLE PRECISION,
                plan_mem DOUBLE PRECISION,
                ingestion_run_id UUID NOT NULL,
                ingested_at_utc TIMESTAMPTZ NOT NULL
            );
            """
        )

    connection.commit()


def get_existing_row_count(
    connection: psycopg.Connection,
) -> int:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM staging.batch_tasks_source;
            """
        )

        return cursor.fetchone()[0]


def truncate_table(
    connection: psycopg.Connection,
) -> None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE TABLE staging.batch_tasks_source;
            """
        )


def copy_dataframe(
    connection: psycopg.Connection,
    dataframe: pd.DataFrame,
) -> None:

    buffer = StringIO()

    dataframe[POSTGRES_COLUMNS].to_csv(
        buffer,
        index=False,
        header=False,
        na_rep="",
    )

    buffer.seek(0)

    copy_sql = """
        COPY staging.batch_tasks_source (
            task_name,
            instance_num,
            job_name,
            task_type,
            status,
            start_time,
            end_time,
            plan_cpu,
            plan_mem,
            ingestion_run_id,
            ingested_at_utc
        )
        FROM STDIN
        WITH (
            FORMAT CSV,
            NULL ''
        );
    """

    with connection.cursor() as cursor:
        with cursor.copy(copy_sql) as copy:
            while True:
                chunk = buffer.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                copy.write(chunk)


def load_bronze(
    max_files: int | None,
    replace: bool,
) -> None:

    parquet_files = sorted(
        BRONZE_DIR.glob(
            "part-*.parquet"
        )
    )

    if not parquet_files:
        raise FileNotFoundError(
            f"No Parquet files found in {BRONZE_DIR}"
        )

    if max_files is not None:
        parquet_files = parquet_files[
            :max_files
        ]

    print(
        f"Found {len(parquet_files)} "
        "Parquet file(s) to load."
    )

    with get_connection() as connection:

        create_table(connection)

        existing_rows = (
            get_existing_row_count(
                connection
            )
        )

        if existing_rows > 0:

            if not replace:
                raise RuntimeError(
                    "staging.batch_tasks_source "
                    f"already contains {existing_rows:,} rows. "
                    "Use --replace to rebuild it."
                )

            print(
                f"Removing existing "
                f"{existing_rows:,} rows..."
            )

            truncate_table(
                connection
            )

        total_loaded = 0

        for index, parquet_file in enumerate(
            parquet_files,
            start=1,
        ):

            dataframe = pd.read_parquet(
                parquet_file
            )

            row_count = len(
                dataframe
            )

            copy_dataframe(
                connection,
                dataframe,
            )

            total_loaded += row_count

            print(
                f"File {index:03d}/"
                f"{len(parquet_files):03d} | "
                f"{parquet_file.name} | "
                f"rows={row_count:,} | "
                f"total={total_loaded:,}"
            )

        database_count = (
            get_existing_row_count(
                connection
            )
        )

        print()
        print("=" * 70)
        print("POSTGRES LOAD SUMMARY")
        print("=" * 70)

        print(
            f"Rows loaded: "
            f"{total_loaded:,}"
        )

        print(
            f"Rows in PostgreSQL: "
            f"{database_count:,}"
        )

        if total_loaded == database_count:
            print(
                "ROW COUNT CHECK: PASS"
            )
        else:
            print(
                "ROW COUNT CHECK: FAIL"
            )

            raise RuntimeError(
                "PostgreSQL row-count validation failed. "
                "The load transaction will be rolled back."
            )

        # Commit only after every Parquet file has been copied
        # and the final row-count validation has passed.
        #
        # PostgreSQL TRUNCATE is transactional, so a failure
        # before this point preserves the previously committed
        # staging snapshot when --replace is used.
        connection.commit()

        print(
            "LOAD TRANSACTION: COMMITTED"
        )

        print("=" * 70)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--replace",
        action="store_true",
    )

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    load_bronze(
        max_files=args.max_files,
        replace=args.replace,
    )
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "batch_tasks"


EXPECTED_COLUMNS = [
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

ALLOWED_STATUSES = {
    "Terminated",
    "Running",
    "Failed",
    "Waiting",
}


def validate_raw_contract() -> None:
    parquet_files = sorted(RAW_DIR.glob("part-*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(
            f"No Parquet files found in {RAW_DIR}"
        )

    total_rows = 0

    missing_counts = {
        column: 0
        for column in EXPECTED_COLUMNS
    }

    status_counts = {}

    invalid_time_rows = 0
    missing_job_name = 0
    missing_task_name = 0

    observed_statuses = set()

    print(f"Found {len(parquet_files)} Parquet files.")
    print()

    for file_number, parquet_file in enumerate(
        parquet_files,
        start=1,
    ):
        df = pd.read_parquet(parquet_file)

        if list(df.columns) != EXPECTED_COLUMNS:
            raise ValueError(
                f"Unexpected schema in {parquet_file.name}"
            )

        total_rows += len(df)

        for column in EXPECTED_COLUMNS:
            missing_counts[column] += int(
                df[column].isna().sum()
            )

        missing_job_name += int(
            df["job_name"].isna().sum()
        )

        missing_task_name += int(
            df["task_name"].isna().sum()
        )

        statuses = set(
            df["status"]
            .dropna()
            .unique()
            .tolist()
        )

        observed_statuses.update(statuses)

        current_status_counts = (
            df["status"]
            .value_counts(dropna=False)
        )

        for status, count in current_status_counts.items():
            key = "<NA>" if pd.isna(status) else str(status)

            status_counts[key] = (
                status_counts.get(key, 0)
                + int(count)
            )

        valid_times = (
            df["start_time"].notna()
            & df["end_time"].notna()
        )

        invalid_time_rows += int(
            (
                df.loc[valid_times, "end_time"]
                < df.loc[valid_times, "start_time"]
            ).sum()
        )

        print(
            f"Checked {file_number:02d}/"
            f"{len(parquet_files)}: "
            f"{parquet_file.name}"
        )

    unexpected_statuses = (
        observed_statuses - ALLOWED_STATUSES
    )

    print()
    print("=" * 60)
    print("RAW DATA CONTRACT REPORT")
    print("=" * 60)

    print(f"\nTotal rows: {total_rows:,}")

    print("\nObserved statuses:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count:,}")

    print("\nMissing values:")
    for column, count in missing_counts.items():
        print(f"  {column}: {count:,}")

    print(
        f"\nRows where end_time < start_time: "
        f"{invalid_time_rows:,}"
    )

    print(
        f"Missing job_name: "
        f"{missing_job_name:,}"
    )

    print(
        f"Missing task_name: "
        f"{missing_task_name:,}"
    )

    print(
        f"Unexpected statuses: "
        f"{unexpected_statuses}"
    )

    print()
    print("Contract validation completed.")


if __name__ == "__main__":
    validate_raw_contract()
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "batch_tasks"


def profile_task_quality() -> None:
    parquet_files = sorted(RAW_DIR.glob("part-*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(
            f"No Parquet files found in {RAW_DIR}"
        )

    results = {}

    for file_number, parquet_file in enumerate(
        parquet_files,
        start=1,
    ):
        df = pd.read_parquet(
            parquet_file,
            columns=[
                "status",
                "instance_num",
                "start_time",
                "end_time",
                "plan_cpu",
                "plan_mem",
            ],
        )

        for status, group in df.groupby("status", dropna=False):

            status = str(status)

            if status not in results:
                results[status] = {
                    "rows": 0,
                    "missing_instance_num": 0,
                    "missing_plan_cpu": 0,
                    "missing_plan_mem": 0,
                    "missing_both_resources": 0,
                    "missing_either_resource": 0,
                    "end_before_start": 0,
                }

            result = results[status]

            result["rows"] += len(group)

            result["missing_instance_num"] += int(
                group["instance_num"].isna().sum()
            )

            result["missing_plan_cpu"] += int(
                group["plan_cpu"].isna().sum()
            )

            result["missing_plan_mem"] += int(
                group["plan_mem"].isna().sum()
            )

            result["missing_both_resources"] += int(
                (
                    group["plan_cpu"].isna()
                    & group["plan_mem"].isna()
                ).sum()
            )

            result["missing_either_resource"] += int(
                (
                    group["plan_cpu"].isna()
                    | group["plan_mem"].isna()
                ).sum()
            )

            result["end_before_start"] += int(
                (
                    group["end_time"]
                    < group["start_time"]
                ).sum()
            )

        print(
            f"Checked {file_number:02d}/"
            f"{len(parquet_files)}: "
            f"{parquet_file.name}"
        )

    report = (
        pd.DataFrame.from_dict(
            results,
            orient="index",
        )
        .reset_index()
        .rename(columns={"index": "status"})
        .sort_values("status")
    )

    report["missing_instance_pct"] = (
        100
        * report["missing_instance_num"]
        / report["rows"]
    )

    report["missing_resource_pct"] = (
        100
        * report["missing_either_resource"]
        / report["rows"]
    )

    report["end_before_start_pct"] = (
        100
        * report["end_before_start"]
        / report["rows"]
    )

    print()
    print("=" * 100)
    print("TASK DATA QUALITY PROFILE BY STATUS")
    print("=" * 100)
    print()

    print(report.to_string(index=False))

    print()
    print("Profile completed.")


if __name__ == "__main__":
    profile_task_quality()
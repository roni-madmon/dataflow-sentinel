"""Read evaluation artifacts and CSV requests without loading model objects."""

import csv
from io import StringIO
import json
import math
from pathlib import Path
import re

import pandas as pd

FEATURES = [
    "task_count", "mean_task_plan_cpu", "max_task_plan_cpu", "total_task_plan_cpu",
    "mean_task_plan_mem", "max_task_plan_mem", "total_task_plan_mem",
    "missing_plan_cpu_flag", "missing_plan_mem_flag", "total_instances",
    "missing_instance_num_flag", "task_type_group",
]


def optional_number(value):
    text = str(value).strip()
    if text.lower() in {"", "null", "none"}:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError("Enter a number, or leave a nullable field empty.") from exc
    if not math.isfinite(number):
        raise ValueError("Numbers must be finite; use an empty cell for missing data.")
    return number


def parse_jobs_csv(data, *, max_rows=500):
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("CSV uploads are limited to 5 MB.")
    try:
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
        headers = reader.fieldnames or []
        required = {"job_run_id", *FEATURES}
        if len(headers) != len(set(headers)) or set(headers) != required:
            raise ValueError("Use exactly job_run_id and the 12 feature columns in the downloadable template.")
        jobs, ids = [], set()
        for line, row in enumerate(reader, start=2):
            if len(jobs) >= max_rows:
                raise ValueError(f"At most {max_rows} jobs are allowed per upload.")
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"CSV row {line} has the wrong number of cells.")
            job_id = row["job_run_id"].strip()
            if not job_id or job_id in ids:
                raise ValueError(f"CSV row {line}: job IDs must be non-empty and unique.")
            ids.add(job_id)
            features = {}
            for name in FEATURES:
                if name == "task_type_group":
                    features[name] = row[name].strip()
                else:
                    try:
                        features[name] = optional_number(row[name])
                    except ValueError as exc:
                        raise ValueError(f"CSV row {line}, {name}: {exc}") from exc
            jobs.append({"job_run_id": job_id, "features": features})
        if not jobs:
            raise ValueError("The CSV contains no jobs.")
        return jobs
    except UnicodeDecodeError as exc:
        raise ValueError("Save the CSV using UTF-8 encoding.") from exc


def normalized(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def whole(value, name):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a non-negative whole number.") from exc
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{name} must be a non-negative whole number.")
    return int(number)


def validate_counts(jobs, alerts, tp, fp, fn):
    values = {k: whole(v, k) for k, v in dict(jobs=jobs, alerts=alerts, tp=tp, fp=fp, fn=fn).items()}
    n, a, t, f, missed = (values[k] for k in ("jobs", "alerts", "tp", "fp", "fn"))
    if n == 0 or a != t + f or a + missed > n:
        raise ValueError("Evaluation counts are inconsistent: require jobs > 0, alerts = TP + FP, and alerts + FN <= jobs.")
    return values


def _split_rows(metadata, split):
    rows = {normalized(k): v for k, v in metadata.get("rows", {}).items()}
    value = rows.get(split.lower(), rows.get("val") if split == "Validation" else None)
    if isinstance(value, dict):
        value = next((value[k] for k in ("jobs", "rows", "n_rows", "n_jobs") if k in value), None)
    return value


def normalize_metrics(frame, metadata):
    frame = frame.copy()
    frame.columns = [normalized(c) for c in frame.columns]
    if not frame.columns.is_unique:
        raise ValueError("Metrics CSV has duplicate column names.")
    aliases = {"dataset": "split", "dataset_split": "split", "average_precision": "ap",
               "n_jobs": "jobs", "n_rows": "jobs", "rows": "jobs",
               "tp": "true_alerts", "fp": "false_alerts", "fn": "missed_failures"}
    frame = frame.rename(columns={k: v for k, v in aliases.items() if k in frame and v not in frame})
    # A CSV written with split as its index has an unnamed first column.
    if "split" not in frame:
        for column in frame:
            values = set(frame[column].dropna().astype(str).str.lower().str.strip())
            if values and values <= {"validation", "val", "test", "train"}:
                frame = frame.rename(columns={column: "split"})
                break
    required = {"split", "alerts", "false_alerts", "missed_failures", "threshold"}
    if not required.issubset(frame):
        raise ValueError("Metrics CSV is missing: " + ", ".join(sorted(required - set(frame))))
    if "model" in frame and "model_name" in metadata:
        frame = frame.loc[frame["model"].astype(str).str.strip() == metadata["model_name"]]
    records = []
    for row in frame.to_dict("records"):
        split = {"validation": "Validation", "val": "Validation", "test": "Test"}.get(str(row["split"]).strip().lower())
        if split is None:
            continue
        threshold = float(row["threshold"])
        if not math.isfinite(threshold) or not math.isclose(threshold, float(metadata["threshold"]), rel_tol=0, abs_tol=1e-12):
            raise ValueError("Metrics threshold differs from metadata.json. Use the full-precision saved metrics CSV.")
        alerts = whole(row["alerts"], "alerts")
        fp = whole(row["false_alerts"], "false_alerts")
        tp = whole(row.get("true_alerts", alerts - fp), "true_alerts")
        n = row.get("jobs")
        if n is None or pd.isna(n):
            n = _split_rows(metadata, split)
        counts = validate_counts(n, alerts, tp, fp, row["missed_failures"])
        n, fn = counts["jobs"], counts["fn"]
        failures = tp + fn
        ap = float(row["ap"]) if "ap" in row and not pd.isna(row["ap"]) else None
        if ap is not None and (not math.isfinite(ap) or not 0 <= ap <= 1):
            raise ValueError("AP must be between 0 and 1.")
        records.append({"split": split, "jobs": n, "failures": failures,
                        "threshold": threshold, "ap": ap,
                        "precision": tp / alerts if alerts else None,
                        "recall": tp / failures if failures else None,
                        "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None,
                        "alerts": alerts, "true_alerts": tp, "false_alerts": fp,
                        "missed_failures": fn, "true_negatives": n - alerts - fn,
                        "alert_pct": 100 * alerts / n, "failure_pct": 100 * failures / n})
    result = pd.DataFrame(records)
    if result.empty or result["split"].duplicated().any():
        raise ValueError("Expected one saved row per Validation/Test split for the selected model.")
    return result


def load_report(directory, expected_model_version=None):
    directory = Path(directory).expanduser()
    if directory.is_file():
        directory = directory.parent
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8-sig"))
    version = f"{metadata['model_name']}@{metadata['created_at_utc']}"
    if expected_model_version and version != expected_model_version:
        raise ValueError("The selected report belongs to a different model than the running API.")
    metrics = normalize_metrics(pd.read_csv(directory / "validation_test_metrics.csv"), metadata)
    return {"metadata": metadata, "metrics": metrics, "model_version": version, "directory": directory}


def load_cohorts(directory, by_instances=False):
    name = "error_analysis_by_task_type_and_instances.csv" if by_instances else "error_analysis_by_task_type.csv"
    frame = pd.read_csv(Path(directory) / name)
    frame.columns = [normalized(c) for c in frame.columns]
    return frame


def simulate(jobs, alerts, tp, fp, fn, failure_cost, review_cost, prevention_rate):
    counts = validate_counts(jobs, alerts, tp, fp, fn)
    failure_cost, review_cost, prevention_rate = map(float, (failure_cost, review_cost, prevention_rate))
    if (not all(math.isfinite(x) for x in (failure_cost, review_cost, prevention_rate))
            or failure_cost < 0 or review_cost < 0 or not 0 <= prevention_rate <= 1):
        raise ValueError("Costs must be finite and non-negative; prevention rate must be between 0 and 1.")
    prevented = counts["tp"] * prevention_rate
    gross = prevented * failure_cost
    review = counts["alerts"] * review_cost
    net = gross - review
    opportunity = counts["tp"] * failure_cost
    return {"prevented_failures": prevented, "gross_benefit": gross,
            "investigation_cost": review, "net_benefit": net,
            "net_per_1000_jobs": net * 1000 / counts["jobs"],
            "roi": net / review if review else None,
            "remaining_failures": counts["fn"] + counts["tp"] - prevented,
            "break_even_prevention": review / opportunity if opportunity else None}

"""Check the local dashboard's artifact and API connections, without training."""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.client import call_api
from dashboard.data import FEATURES, load_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=os.environ.get("SENTINEL_MODEL_PATH", "artifacts/models/hgb_v2_20261002T104801_398392Z"))
    parser.add_argument("--api-url", default=os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    info = call_api(args.api_url, "/model-info")
    if info["feature_columns"] != FEATURES:
        raise ValueError("API features differ from the dashboard contract.")
    path = Path(args.model_dir)
    report = load_report(path if path.is_absolute() else ROOT / path, info["model_version"])
    print("Dashboard checks passed: API connection, model identity, saved evaluation counts.")
    print("Model:", info["model_version"])
    print(report["metrics"][["split", "jobs", "true_alerts", "false_alerts", "missed_failures"]].to_string(index=False))


if __name__ == "__main__":
    main()

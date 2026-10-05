"""Check a running local API using synthetic requests and the standard library."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    def call(path, payload=None, expected_status=200):
        body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
        request = Request(base + path, data=body, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.status
            result = json.loads(response.read())
        if status != expected_status:
            raise RuntimeError(f"{path}: expected {expected_status}, got {status}: {result}")
        return result

    health = call("/health")
    info = call("/model-info")
    assert health["model_loaded"] is True
    assert health["model_version"] == info["model_version"]
    assert info["score_is_calibrated"] is False

    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "examples" / "predict_request.json").read_text(encoding="utf-8"))
    payload["expected_model_version"] = info["model_version"]
    single = call("/predict", payload)
    assert single["alert_threshold"] == info["alert_threshold"]
    assert single["alert"] == (single["risk_score"] >= single["alert_threshold"])

    first = {"job_run_id": payload["job_run_id"], "features": payload["features"]}
    second = deepcopy(first)
    second["job_run_id"] = "demo-job-002"
    second["features"]["task_type_group"] = "type_1"
    second["features"]["total_instances"] = 128
    batch = call("/predict/batch", {"jobs": [first, second], "expected_model_version": info["model_version"]})
    assert batch["total"] == 2
    assert [p["job_run_id"] for p in batch["predictions"]] == ["demo-job-001", "demo-job-002"]
    assert batch["predictions"][0]["risk_score"] == single["risk_score"]
    assert batch["alerts"] == sum(p["alert"] for p in batch["predictions"])

    invalid = deepcopy(first)
    del invalid["features"]["task_count"]
    call("/predict", invalid, expected_status=422)

    print("API smoke test passed: health, model-info, single, batch, invalid input.")
    print("Requests used synthetic demo feature values.")
    print(json.dumps(single, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

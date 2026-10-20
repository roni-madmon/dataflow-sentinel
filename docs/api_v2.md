# DataFlow Sentinel: experimental HGB V2 API

This patch adds a local FastAPI service around the saved HGB V2 pipeline. It
loads the selected bundle once per server process and uses its saved feature
precision, positive class, and full-precision alert threshold.

## Install in the existing Windows project

Save `dataflow_sentinel_api_v2.zip` in Downloads, then run in PowerShell:

```powershell
Set-Location "C:\project\dataflow-sentinel"
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\dataflow_sentinel_api_v2.zip" -DestinationPath . -Force
.\.venv\Scripts\python.exe -m pip install -r .\requirements-api.txt
```

The archive adds the `api`, `examples`, and `scripts` files, API tests,
requirements, and documentation. It also updates `src/ml/predictor.py` with
public read-only metadata properties and includes the existing inference tests.
The inference algorithm is unchanged. The saved model bundle, training data,
notebooks, dbt models, and Docker Compose file are not part of the archive.

Use the project's existing training environment. Its ML dependency versions
must match the saved artifact's `metadata.json`; the API requirements do not
replace those ML dependencies. The API dependencies have tested direct pins
for FastAPI and Uvicorn, but are not a lockfile for the entire project.

## Start the API

```powershell
Set-Location "C:\project\dataflow-sentinel"
$env:SENTINEL_MODEL_PATH = "C:\project\dataflow-sentinel\artifacts\models\hgb_v2_20261002T104801_398392Z"
.\.venv\Scripts\python.exe -m uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Leave this terminal open. Open http://127.0.0.1:8000/docs for interactive
requests. Stop the server with Ctrl+C when finished. `SENTINEL_MODEL_PATH` is
required and accepts a bundle directory or the `model_bundle.joblib` file.
Relative model paths resolve against the project root. There is no automatic
selection of the latest model or retraining during startup.

The optional `SENTINEL_MAX_THREADS` environment variable defaults to `4` and
must be a positive integer. Concurrent inference calls are serialized around
the process-wide native thread limit, as in the original predictor.

## Verify the running server

In a second PowerShell terminal:

```powershell
Set-Location "C:\project\dataflow-sentinel"
.\.venv\Scripts\python.exe .\scripts\smoke_test_api.py
```

Expected first output line:

```text
API smoke test passed: health, model-info, single, batch, invalid input.
```

The script checks health, metadata, single and batch predictions, consistency
between the two prediction paths, and a rejected incomplete request. It uses
synthetic feature values from `examples/predict_request.json`. Its score depends
on the loaded artifact; it does not assert a known outcome for these demo jobs
or estimate model accuracy. For the saved project model, the threshold should
be `0.9696205830070223`.

## HTTP contract

| Method | Path | Result |
|---|---|---|
| GET | `/health` | Ready only when the model is loaded; includes model identity |
| GET | `/model-info` | Model identity, threshold, feature order, saved dtypes, JSON input schema, limitations |
| POST | `/predict` | One job's score, threshold decision, metadata, and suggested checks |
| POST | `/predict/batch` | Between 1 and 500 jobs, preserving request order |

Every response has an `X-Request-ID` header. Predictions also include
`request_id` in the JSON body. A request for one job has this shape:

```json
{
  "job_run_id": "demo-job-001",
  "schema_version": "hgb-v2-features-v1",
  "features": {
    "task_count": 1,
    "mean_task_plan_cpu": 100.0,
    "max_task_plan_cpu": 100.0,
    "total_task_plan_cpu": 100.0,
    "mean_task_plan_mem": 0.1,
    "max_task_plan_mem": 0.1,
    "total_task_plan_mem": 0.1,
    "missing_plan_cpu_flag": 0,
    "missing_plan_mem_flag": 0,
    "total_instances": 1,
    "missing_instance_num_flag": 0,
    "task_type_group": "type_10"
  }
}
```

All twelve feature keys are required. `job_run_id` is required request metadata
and never enters the feature matrix. `schema_version` may be omitted; its default
is the version above. An optional `expected_model_version` can be copied from
`GET /model-info` to require a particular loaded artifact. The model version is
constructed from its saved name and creation timestamp.

For batch prediction, wrap job objects as `{"jobs": [job1, job2]}`. Put optional
`schema_version` and `expected_model_version` at the batch's top level.
Job IDs must be unique within the batch.

Input rules:

- Counts accept whole JSON numbers, including `1.0`; `task_count` is positive
  and `total_instances` is non-negative or `null`.
- Flags are numeric `0` or `1`. Booleans and numeric strings are rejected.
- CPU and memory aggregates accept finite numbers or `null`. A missing aggregate
  requires its corresponding missing flag to be `1`. Partial missing source
  data may also produce non-null aggregates with a missing flag of `1`.
- `total_instances: null` requires `missing_instance_num_flag: 1`.
- Use JSON `null` for missing values. NaN and infinity are rejected.
- Task type is a non-empty trimmed string. Unseen categories pass to the saved
  encoder's existing unknown-category handling.
- Extra fields, including `failed_job`, are rejected. Values outside the saved
  feature dtype's numeric range are rejected before inference.

| Status | Meaning |
|---|---|
| 200 | Valid request completed |
| 422 | Missing, unexpected, malformed, inconsistent, or incompatible feature input; unsupported schema version |
| 409 | `expected_model_version` differs from the loaded model |
| 503 | Application is not ready because the model is not loaded |
| 500 | Unexpected internal error; response omits internal exception details |

A missing bundle, incompatible sklearn version, or incompatible saved feature
schema fails application startup. A successfully running server's health route
reports the loaded model.

## Interpret responses

`risk_score` is the frozen pipeline's score and is **not a calibrated failure
probability**. `alert` means `risk_score >= alert_threshold`; neither value is
rounded before comparison. `risk_level` is `ABOVE_THRESHOLD` or
`BELOW_THRESHOLD`, describing that comparison only. A below-threshold job can
still fail.

`score_is_calibrated` is `false`, and the saved project artifact remains
`experimental`. The source data does not independently establish model-feature
availability before job start. `/model-info` therefore reports
`unverified_pre_run`.

Local feature attributions have not been implemented. `main_risk_factors` is
therefore empty and `explanation_status` is `not_available`. The
`recommended_checks` list is a deterministic playbook driven by missing
metadata and the alert decision. These checks are not SHAP explanations,
identified root causes, retrieved incident evidence, or RAG output.

## Logging

The application writes one JSON event per HTTP request to standard error. It
contains request ID, matched route, HTTP method, model version, latency,
response status, validation outcome, and score summary for successful
predictions. It omits raw features, job IDs, and query strings. Unexpected errors
log their exception type only. `--no-access-log` disables Uvicorn's separate
access log; application JSON request logs remain enabled. Logs are not persisted
to the database by this patch.

## Automated tests

```powershell
Set-Location "C:\project\dataflow-sentinel"
.\.venv\Scripts\python.exe -m pip install -r .\requirements-api-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -p "test_*v2.py" -v
```

Verified on 2026-10-02: 18 tests passed (12 API tests and 6 inference tests),
using a small real HGB pipeline fitted to synthetic data. An actual temporary
Uvicorn server also passed `scripts/smoke_test_api.py`. The server was stopped
afterward.

Local verification used Python 3.12.14, FastAPI 0.142.2, Uvicorn 0.54.0,
Pydantic 2.13.5, Starlette 1.7.0, HTTPX 0.28.1, AnyIO 4.15.1,
scikit-learn 1.8.0, NumPy 2.3.5, and pandas 2.2.3. These are the test fixture's
versions, not replacement requirements for the user's trained artifact.

Separately, the user already verified the original predictor against 1,000
notebook predictions using the real HGB V2 artifact: scores, threshold, and
alert decisions matched. The HTTP API still needs the Windows smoke test above
against that real artifact. No new Test-set evaluation or threshold tuning was
performed while building this API.

Implementation references:

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [FastAPI middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/)

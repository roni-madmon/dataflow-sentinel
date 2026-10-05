# DataFlow Sentinel: Streamlit dashboard

This dashboard connects to the existing HGB V2 API for predictions and reads
saved evaluation reports from the selected model directory. It does not load
the joblib model or retrain it.

The interface is in English for a portfolio/demo audience. It uses the existing
project's Python environment and runs locally at http://127.0.0.1:8501.

## Windows quick start

Keep the working API terminal open at http://127.0.0.1:8000. Save the dashboard
ZIP in Downloads and open another PowerShell terminal:

```powershell
Set-Location "C:\project\dataflow-sentinel"
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\dataflow_sentinel_streamlit_v2.zip" -DestinationPath . -Force
```

After extraction, run this command separately:

```powershell
.\.venv\Scripts\python.exe .\scripts\start_dashboard.py
```

The script installs the dashboard requirement using the Python you invoked,
sets the model folder and API address, checks their
compatibility, and launches Streamlit. If installation or connection checks
fail, it stops and displays the error before launching the dashboard.

The initial checks should print:

```text
Dashboard checks passed: API connection, model identity, saved evaluation counts.
```

They also print the actual Validation/Test counts read from your saved CSV.
The browser should open automatically. Otherwise open http://127.0.0.1:8501.
Keep both service terminals open. Ctrl+C stops each service in its own terminal.

For subsequent launches without reinstalling dependencies:

```powershell
.\.venv\Scripts\python.exe .\scripts\start_dashboard.py --skip-install
```

The default experiment folder matches the already verified artifact:

```text
artifacts\models\hgb_v2_20261002T104801_398392Z
```

To select another saved model explicitly:

```powershell
.\.venv\Scripts\python.exe .\scripts\start_dashboard.py --model-path "C:\path\to\saved_model" --api-url "http://127.0.0.1:8000" --port 8501
```

The API must be running that same model. Dashboard report loading checks the
model name and creation timestamp against the API identity. Requests also carry
`expected_model_version`, so an API model change cannot silently score a job
with the previously selected version.

If the API needs restarting, use its existing launch command in its own terminal:

```powershell
Set-Location "C:\project\dataflow-sentinel"
$env:SENTINEL_MODEL_PATH = "C:\project\dataflow-sentinel\artifacts\models\hgb_v2_20261002T104801_398392Z"
.\.venv\Scripts\python.exe -m uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## Workspace views

| View | What it shows |
|---|---|
| Overview | Saved evaluation summary and a separate summary of this session's submitted predictions |
| Score jobs | A single-job form or a CSV batch of up to 500 jobs; predictions come from the API |
| Alert queue | Filtered session predictions, job details, the exact request/response, suggested checks, and CSV export |
| Model performance | Saved Validation/Test metrics, a confusion matrix, prevalence context, and available cohort reports |
| Business simulator | Editable cost/prevention assumptions, three scenarios, negative and positive net benefit, a sensitivity curve, and export |
| Data quality | Missing-feature flags in session inputs, saved label-time exclusions and split sizes, and active model information |

The queue is session history, not a live feed from the scheduler or a durable
database. It retains the latest 1,000 prediction records. Repeat submissions
remain separate records. Refreshing/reconnecting the browser can end the
session; export records before closing if they need to be retained. The clear
button clears only these local session predictions.

## First demo

1. Confirm the sidebar displays **API connected** and `HGB V2 · experimental`.
2. Confirm the Overview loads the saved Test evaluation, with **624,196 jobs**.
3. Open **Score jobs**, keep **Synthetic demo** selected, and click **Score job**.
4. For the supplied one-task/type_10/one-instance example, the user previously
   observed a score equal to the frozen threshold. Equality triggers an alert
   because the comparison is `score >= threshold`.
5. Open **Alert queue** and inspect the submitted feature values and response.
6. Open **Business simulator** and change an assumption. Model weights, scores,
   and threshold are not changed by these controls.

The form uses the same feature units as training. Blank nullable numeric fields
become JSON null, and their missing flags are set. A missing flag can also be
set when an aggregate is present but some source tasks had missing metadata.
The existing API performs the final feature validation.

Scores and thresholds are rounded only for display. The full values remain in
the complete response and the API's decision uses full precision. The score is
uncalibrated, so the UI does not present it as a failure probability.

Suggested checks come from the current deterministic API playbook. Feature
attributions and RAG evidence have not yet been implemented; no generated
explanations or retrieved sources are fabricated in this dashboard.

## CSV batches

Download the synthetic template from the Score jobs page, or use
`examples/dashboard_jobs_template.csv`. It contains two synthetic jobs. Keep
the **Synthetic demo** source label when testing those examples.

Use UTF-8 CSV with exactly `job_run_id` and all twelve model features. Do not
include `failed_job`, timestamps, or other columns. IDs must be non-empty and
unique within a batch; leading zeros in IDs are preserved. Uploads are limited
to 500 jobs and 5 MB. Empty numeric cells become null; required counts/flags
and consistency constraints are still checked by the API. There is one API
request per batch, with no background scoring on ordinary page reruns.

## Saved report contract

Required in the selected artifact directory:

- `metadata.json`: model name, creation timestamp, threshold, and split row counts.
- `validation_test_metrics.csv`: split, threshold, alerts, false alerts, and
  missed failures. `true_alerts` may be supplied or derived as alerts minus
  false alerts. Saved AP is displayed when present; AP is never inferred from
  confusion-matrix counts.

Optional cohort files:

- `error_analysis_by_task_type.csv`
- `error_analysis_by_task_type_and_instances.csv`

Metric names are normalized to lowercase. Common aliases and an exported split
index are supported. Jobs come from a jobs/n_jobs/n_rows/rows CSV column or from
`metadata.json` under `rows.validation` and `rows.test`. Precision, recall and
F1 are computed from the saved counts, avoiding rounding errors in displayed
notebook output. Invalid counts and a threshold mismatch are rejected.

No saved results are bundled as a production fallback. Missing or incompatible
reports produce an explanatory message. Once the app is running, an offline
API disables scoring while saved reports remain available. An API/report model
mismatch blocks the report to prevent mixing experiments.

## Business assumptions

The default input values are illustrative: failure cost 100 units, investigation
cost 10 units per alert, and prevention assumptions of 10%, 25%, and 50%.
Selecting ILS or USD labels the inputs; it does not perform currency conversion.

```text
assumed_prevented_failures = true_alerts * assumed_prevention_rate
gross_benefit = assumed_prevented_failures * assumed_failure_cost
investigation_cost = all_alerts * assumed_cost_per_reviewed_alert
net_benefit = gross_benefit - investigation_cost
net_per_1000_jobs = net_benefit * 1000 / evaluated_jobs
```

All alerts incur review cost, including false positives. Only correctly flagged
failures are eligible for modeled prevention. Fractional prevented failures
represent an expected scenario quantity. The comparison is with no alert-review
program and excludes other operating costs. A negative net result stays negative.

For the reported Test counts and base assumptions, the calculation produces
612 assumed prevented failures, 61,200 units of gross benefit, 198,260 units of
review cost, and **-137,060 units of net benefit**. This is an assumption-driven
simulation, not observed savings or a claim about a real operational rollout.

There is no Test-set threshold tuning control. Model or policy revisions
informed by already-inspected Test results need a new separate evaluation.

## Validation

Run the supplied automated tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -p "test_dashboard_v2.py" -v
```

Eleven tests cover report counts, experiment identity, CSV parsing, invalid
inputs, business calculations, all six Streamlit views, single prediction and
queue behavior, reruns without duplicate scoring, and API unavailability. UI
tests use an API stub and explicitly constructed local report fixtures.

A separate integration check ran real local Uvicorn and Streamlit servers with
a tiny HGB pipeline trained on synthetic data. The dashboard HTTP client matched
single and batch scores; Streamlit AppTest submitted a live prediction and
verified the queue and simulator. Both temporary servers were stopped afterward.
The build environment could not download its graphical browser, so visual
inspection in an actual browser remains part of the local walkthrough above.

The report fixture uses counts reported in the conversation. This does not
replace verification of the user's actual saved files: the startup script
performs that check on Windows before opening the app.

For the data/connection check alone:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_test_dashboard.py
```

Reference: [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).

## Project status after this delivery

The user has verified 1,000 inference predictions against the notebook and
passed the API smoke test with the real HGB V2 artifact. This delivery adds the
dashboard, saved-report views, and an assumption-based business simulator.

RAG remains required. The next phase needs an identified corpus with source
provenance, a retrieval baseline, retrieval evaluation, citations, and refusal
to make unsupported claims. Local feature explanations are also still pending.
The experimental feature-availability gate, business heuristic/XGBoost
comparison, operational policy, full dependency locking, containers, and CI
remain separate project work. A passing interface test does not close those
acceptance criteria.

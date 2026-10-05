# Implementation alignment with the master specification, version 3

Reviewed on 2026-10-02 against the uploaded DataFlow Sentinel master project
specification and the user's reported project outputs. This is a progress map,
not a declaration that all project acceptance criteria have passed.

## Current delivery

The FastAPI patch implements the required `/predict` and `/health` routes and
the recommended `/predict/batch` and `/model-info` routes. It includes typed
requests and responses, feature and model compatibility checks, loading at
startup, request logs, and automated contract and inference integration tests.
The user's real-model HTTP smoke check remains to be run on Windows.

The original inference layer already matched 1,000 real notebook predictions.
The API reuses that inference path. It requires the saved artifact explicitly;
the model and threshold are not retrained or retuned by the service.

## Deliberate adaptations

| Specification concept | Current implementation and reason |
|---|---|
| `risk_probability` | `risk_score` plus `score_is_calibrated: false`, because calibration has not been established |
| Risk tier such as `HIGH` | `ABOVE_THRESHOLD` / `BELOW_THRESHOLD`, tied only to the frozen experimental threshold |
| Main risk factors | Empty list with `explanation_status: not_available`; no computed local attributions yet |
| Recommended checks | Deterministic metadata and alert playbook, explicitly separate from model explanations |
| Pre-run deployment | Experimental local demonstration; source-field availability before job start remains unverified |
| Optional RAG in the original PDF | Required in this project's scope, following the user's explicit instruction |
| Proposed repository layout | Extend the existing `src/ml` and new `api/app` paths without restructuring unrelated ingestion and dbt code |

## Model state

The current model is HGB V2. Its threshold `0.9696205830070223` was selected by
Validation F1, then frozen for Test. The reported results are:

| Metric | Validation | Test |
|---|---:|---:|
| AP | 0.5169 | 0.1948 |
| Precision | 0.5240 | 0.1235 |
| Recall | 0.9022 | 0.5111 |
| F1 | 0.6629 | 0.1989 |
| Alerts | 45,910 | 19,826 |
| False alerts | 21,854 | 17,378 |
| Missed failures | 2,607 | 2,342 |

On Test, `type_10` jobs with one instance account for 17,375 false alerts, while
`type_1` jobs with 101+ instances account for 1,554 missed failures. These cohort
results and the change in failure prevalence constrain operational claims.
Successful serialization and API parity do not establish operational utility.

The Test set has already been inspected for evaluation and error analysis.
Any subsequent model or decision-policy choices informed by those findings
need an appropriately separated future evaluation period. Do not relabel this
same Test set as untouched.

## Remaining project work

| Area | Remaining deliverable |
|---|---|
| Feature availability | Establish when each feature, task count, task type, and instance count is known; retain the V2 experimental label until the pre-run gate is supported |
| Model comparisons | Document the business heuristic baseline and the specification's XGBoost candidate; reported comparisons currently cover LR, HGB V1, and HGB V2 |
| Decision policy | Define alert capacity and FP/FN costs, compare policies on appropriate development data, and distinguish operational policy from the current F1 benchmark |
| Explanations | Compute and validate genuine model attributions before populating main risk factors |
| Streamlit | Overview, alert queue, job detail, model performance, business simulator, and data-quality views |
| Business simulator | Explicit cost/prevention assumptions, scenario comparisons, per-1,000 normalization, and honest negative results |
| RAG | Useful source corpus, provenance, retrieval baseline, retrieval evaluation, cited answers, and abstention when evidence is insufficient |
| Reproducibility | Consolidated dependency locking, clean-environment setup, service containers, CI, and project-level documentation |

## Business simulator contract

Use observed confusion-matrix counts and explicit assumptions:

```text
detected_failures = TP
assumed_prevented_failures = TP * assumed_prevention_rate
gross_benefit = assumed_prevented_failures * assumed_failure_cost
investigation_cost = alerts * assumed_investigation_cost_per_alert
net_benefit = gross_benefit - investigation_cost
metric_per_1000_jobs = metric * 1000 / evaluated_jobs
```

Show conservative, base, and optimistic assumptions, including negative net
benefit where produced. These are simulated outcomes, not verified real-world
savings. Investigation cost applies to all reviewed alerts, not just false
positives.

## Required RAG work

RAG is part of the agreed scope. Its implementation should add evidence that is
useful for investigating jobs; a generic text box alone does not satisfy it.

Start with an identified corpus such as runbooks and documented incidents,
preserving stable source IDs, locations, and provenance. No incident corpus has
yet been supplied or verified here. Synthetic incidents, if used for a demo,
must be clearly identified as synthetic.

Define representative retrieval questions and relevant-source judgments, then
compare a simple structured/SQL or filtering baseline with semantic or hybrid
retrieval. Evaluate retrieval quality separately from answer quality. Generated
answers should cite retrieved evidence and decline unsupported claims. Retrieved
recommendations must remain distinguishable from model feature attributions
and from verified causal diagnoses.

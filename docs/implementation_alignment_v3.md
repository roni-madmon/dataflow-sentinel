# Implementation alignment with Master Specification v3

Review date: 2026-10-05. Reference: DataFlow_Sentinel_Master_Project_Specification_v3.pdf.
This replaces the earlier progress map, whose API, dashboard and RAG statuses were outdated.

## Evidence and limits

Reviewed the uploaded specification and notebook, supplied implementation code,
reported dbt/API/dashboard/RAG results, and the file list of commit b7a392e.
No fresh full-project test, database build, clean-install verification, or
end-to-end notebook execution was performed in this review. Unverified items
below remain open rather than being treated as passed.

## Recorded HGB V2 results

| Split | Jobs | AP | Precision | Recall | F1 | False alerts | Missed failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| Validation | 623,763 | 0.5169 | 0.5240 | 0.9022 | 0.6629 | 21,854 | 2,607 |
| Test | 624,196 | 0.1948 | 0.1235 | 0.5111 | 0.1989 | 17,378 | 2,342 |


Threshold: 0.9696205830070223, selected by maximum Validation F1 and frozen before Test.
Scores are uncalibrated. AP is Average Precision, not a reported trapezoidal PR-AUC.
The reported 1,000-row parity check and HTTP smoke results support serving correctness.
They do not establish pre-run availability, causal explanations, or operational utility.

## Requirement status

| Area / specification section | Status on 2026-10-05 | Remaining work |
|---|---|---|
| Job grain and target, 6-7 | Aggregation and target logic inspected; validation scripts exist | Review current grain-contract evidence, including whether job_name separates executions |
| Pre-run feature gate, 7 | OPEN: availability is unverified in the source data | Prove availability for every input; exclude unsupported features from a strict pre-run model |
| Ingestion and dbt, 8-10 | Implemented components and successful reported builds | Verify current full dbt run, ingestion rerun/idempotency, and downstream failure blocking |
| Model ladder, 13 | Business heuristic, Logistic Regression, HGB V1/V2, and a fixed XGBoost candidate evaluated on development data | HGB V2 remains the deployed experimental model; further Test-informed model selection requires a new untouched future period |
| Temporal evaluation, 14 | Implemented; recorded metrics verified | Preserve the frozen report; further Test-informed tuning needs new evaluation data |
| Threshold policy, 14/16 | Frozen threshold plus exact-capacity policies at 5%, 7.36%, and 10%; business scenarios evaluated on Validation | Balanced 7.36% is the default development policy; preserve the policy as an assumption-driven decision rather than retuning on Test |
| Explainability, 15 | Local SHAP attribution implemented, validated for additivity, and integrated into API and dashboard | Preserve the non-causal interpretation and Train-only reference-background requirement |
| API and dashboard, 17-18 | Working local service and UI; smoke/parity results reported | Add attribution views, PR/threshold views, and actual ingestion/dbt quality reports |
| RAG, 19 + user scope | Model card and investigation runbook indexed; cited answers, abstention, labeled retrieval benchmark, and lexical baseline implemented | Rebuild the index after knowledge-base edits and keep corpus limitations explicit; no historical incident corpus is claimed |
| Orchestration and packaging, 8/22 | Airflow/DAG and CI absent from the committed file list; no verified full service stack | Orchestrated workflow, complete demo packaging, and clean-environment verification |
| Reproducibility and tests, 21-22 | Core ML pins, saved artifact, API/inference/dashboard tests | Complete dependency record, training entry point, current full test run; CI is SHOULD HAVE |


## Interpretation and scope decisions

- RAG is required by the user's later instruction. The current implementation retrieves from
  the model card and investigation runbook, returns cited grounded answers, and abstains when evidence is insufficient.
- HGB V2 is the current deployed experimental model. The specification's XGBoost candidate
  and the business heuristic have now been evaluated on Train/Validation development data without reusing Test for candidate selection.
- risk_score with score_is_calibrated=false accurately reflects the current model.
  Calibration is needed before interpreting these values as failure probabilities.
- main_risk_factors is populated with local SHAP attributions when the explanation background is configured. The deterministic
  playbook remains separate from model attributions and neither is a substitute for verified failure causes.
- The simulator implements the section-16 core formula and three prevention scenarios, and the Validation capacity analysis defines constrained, balanced, and high-coverage operating policies.
  Cost applies to every reviewed alert. The current default development policy is Balanced 7.36%, subject to explicit business assumptions.
- Test has been inspected. Any Test-informed model or policy changes require a separate
  future evaluation period; the existing Test must not be described as newly untouched.
- The original mixed notebook is retained locally. The curated notebook's retained outputs
  belong to the original run; annotation changes do not constitute a rerun.

## Next work, in order

1. Close the grain and feature-availability evidence gaps, especially instance counts.
2. Add the missing development-set baselines and cost/capacity policy comparison.
3. Implement and validate model explanations for the final candidate.
4. Define a labeled RAG benchmark and a suitable documented investigation corpus.
5. Complete data-quality reporting, orchestration, packaging, training entry point,
   dependency documentation and fresh-environment tests before claiming full compliance.

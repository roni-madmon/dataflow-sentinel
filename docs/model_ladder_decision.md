# Model Ladder Decision

## Scope

This comparison uses the chronological development populations only.

- Train: 2,912,014 Jobs, 51,731 failures
- Validation: 623,763 Jobs, 26,663 failures
- Test rows accessed during the new Business Heuristic and XGBoost comparison: 0

The existing Test period had already been inspected in the earlier HGB V2
experiment. It was therefore not reused for candidate selection or tuning.

## Business Heuristic

The heuristic was selected using Train only and then frozen before Validation.

Rule:

`alert if task_type_group == "type_10"`

Validation results:

| Metric | Value |
| --- | ---: |
| Precision | 0.3083 |
| Recall | 0.8837 |
| F1 | 0.4571 |
| Alerts | 76,424 |
| Alert rate | 12.252% |

## Validation Model Ladder

| Candidate | AP | Precision | Recall | F1 | Alerts | Alert rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Business Heuristic | N/A | 0.3083 | 0.8837 | 0.4571 | 76,424 | 12.252% |
| Logistic Regression | 0.2517 | 0.2540 | 0.9229 | 0.3983 | 96,885 | 15.532% |
| HGB V1 | 0.2907 | 0.2808 | 0.9104 | 0.4293 | 86,433 | 13.856% |
| HGB V2 | 0.516948 | 0.523982 | 0.902224 | 0.662946 | 45,910 | 7.3602% |
| XGBoost candidate | 0.517926 | 0.523982 | 0.902224 | 0.662946 | 45,910 | 7.3602% |

## XGBoost Candidate

The candidate used the same 12 Job-level inputs as HGB V2 and the same
chronological Train and Validation populations.

Fixed configuration:

- XGBoost 3.4.1
- objective: binary:logistic
- n_estimators: 250
- learning_rate: 0.05
- max_depth: 6
- min_child_weight: 20
- subsample: 0.8
- colsample_bytree: 0.9
- reg_lambda: 1.0
- scale_pos_weight: 55.2915
- tree_method: hist
- native categorical handling enabled
- random_state: 42
- Validation threshold selected by maximum F1

No Test rows were accessed in this candidate experiment.

## Final Model Decision

HGB V2 remains the deployed experimental model.

XGBoost improved Validation Average Precision by only about 0.00098 absolute,
while producing the same Validation precision, recall, F1, alert count, and
alert rate at its maximum-F1 operating point.

That marginal ranking improvement does not justify replacing the already
validated HGB V2 serving stack, model artifact, SHAP integration, API,
dashboard, and tests.

The model remains experimental. Scores are uncalibrated, and the source data
does not independently establish that every input feature is available before
Job execution.

## Next Decision

The next development step is not additional model tuning.

The frozen HGB V2 Validation scores will be used to compare alert thresholds
under explicit investigation-capacity and business-cost assumptions.

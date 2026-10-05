# HGB V2 - Job Failure Prediction

Source: DataFlow Sentinel notebook evaluation outputs.
Model artifact: hgb_v2_20261002T104801_398392Z
Model status: experimental.

## Purpose

HGB V2 predicts job-run failure using task metadata.
The positive target, failed_job = 1, means at least one task failed.

## Alert decision

The alert threshold is 0.9696205830070223.
An alert is raised when the model score is greater than or equal to this threshold.
The threshold was selected on Validation and kept fixed for Test.

The score is not calibrated and must not be interpreted as a failure probability.

## Evaluation results

| Split | Average Precision (AP) | Precision | Recall | F1 |
|---|---|---|---|---|
| Validation | 0.5169 | 0.5240 | 0.9022 | 0.6629 |
| Test | 0.1948 | 0.1235 | 0.5111 | 0.1989 |

## Test population and alerts

- Evaluated job runs: 624196.
- Actual failed jobs: 4790.
- Total alerts: 19826.
- True alerts: 2448.
- False alerts: 17378.
- Missed failures: 2342.

## Limitations

Performance was lower on Test than on Validation.
Availability of all input features before job execution remains an assumption requiring verification.
The model does not provide verified failure causes or feature attributions.
An alert indicates that the score reached the threshold; it does not prove that a job will fail.

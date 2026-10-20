# Feature Availability Decision

## Goal

DataFlow Sentinel originally targets failure-risk scoring before Job execution.

A dedicated leakage audit was performed to determine whether the current
model inputs can be empirically shown to exist before execution.

## Evidence

Dataset size:

- 14,295,731 Task rows
- 4,201,014 Job runs
- 4,161,396 labeled Jobs eligible for modeling

A proxy for pre-execution Tasks was defined as:

`task_status = waiting AND start_time = 0`

This identified:

- 23,557 Task rows
- 12,356 Jobs

However, none of those Jobs contained only waiting/pre-start Tasks.

Results:

- Fully pre-start Jobs: 0
- Mixed-state Jobs: 12,356
- Jobs also containing failed Tasks: 2,269
- Jobs also containing terminated Tasks: 11,767
- Jobs also containing running Tasks: 1,599

Therefore, waiting/start_time=0 does not represent a complete Job snapshot
before execution.

## Feature evidence

Among waiting Tasks:

- plan_cpu missing: 100%
- plan_mem missing: 100%
- instance_num missing: 98.33%
- task_type missing: 0%

The dataset does not contain an independent timestamp describing when each
feature became available.

## Decision

The current HGB V2 model must NOT be described as a verified leakage-safe
pre-run model.

It remains a valid experimental offline model for studying Job failure risk
using aggregated Job metadata.

The following features remain unsupported as strictly pre-run based on the
available evidence:

- CPU aggregates
- Memory aggregates
- total_instances
- missing-value flags derived from those fields

task_type is observed on waiting Tasks, but aggregation across an entire Job
still assumes that the full Job plan is known before execution.

task_count has the same limitation because it is calculated from the final
observed Task set.

## Portfolio wording

Preferred wording:

"Built an experimental Job failure-risk scoring platform with temporal
evaluation and explicit leakage auditing."

Do not claim:

"Predicts failures before execution using verified pre-run features."

until independent evidence for feature availability is available.

## Next step

Maintain HGB V2 as the current experimental offline candidate and evaluate
whether a defensible strict pre-run feature set can be derived from available
source semantics or external data documentation.

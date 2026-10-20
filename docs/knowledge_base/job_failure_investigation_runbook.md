# Job Failure Investigation Runbook

## Purpose

This runbook provides structured review steps for Job runs flagged by
DataFlow Sentinel.

It is operational guidance, not evidence of the root cause of a failure.
The current HGB V2 model does not provide causal explanations.

## When an alert is raised

An alert means that the model score is greater than or equal to the configured
alert threshold.

The score is not calibrated and must not be interpreted as a probability
that the Job will fail.

Review the Job metadata before taking action.

## Planned resource checks

Review the planned CPU and memory values associated with the Job.

Check for:

- unusually high planned CPU values
- unusually high planned memory values
- missing CPU planning metadata
- missing memory planning metadata
- large differences between average and maximum planned resources

These checks are investigation suggestions only.
They do not establish that resource planning caused the predicted risk.

## Task structure checks

Review the number and types of Tasks associated with the Job.

Check for:

- unusually large task counts
- unusual task-type combinations
- missing or incomplete task-type metadata
- large instance counts
- missing instance-count metadata

The HGB V2 model uses Job-level aggregates, so these checks help reviewers
understand the supplied model inputs.

## Missing metadata

Missing planning metadata should be reviewed before interpreting a risk score.

Relevant indicators include:

- missing_plan_cpu_flag
- missing_plan_mem_flag
- missing_instance_num_flag

A missing-value flag indicates incomplete supplied metadata.
It does not by itself mean that the Job will fail.

## Execution status interpretation

The source data contains the following Task statuses:

- waiting
- running
- terminated
- failed

A failed Job is defined as a Job containing at least one failed Task.

Jobs that cannot be resolved into a valid failed or successful target are
excluded from the labeled modeling population.

## Pre-run limitation

The current dataset does not provide an independent timestamp describing
when every model input became available.

Leakage auditing found that waiting Tasks with start_time = 0 do not represent
complete Job snapshots before execution.

Therefore, HGB V2 is treated as an experimental offline risk model and must
not be described as a verified leakage-safe pre-run predictor.

## Suggested investigation sequence

For an alerted Job:

1. Confirm that required metadata is present.
2. Review the Job task count and task-type composition.
3. Review planned CPU and memory aggregates.
4. Review planned instance counts.
5. Check whether supplied values appear incomplete or inconsistent.
6. Escalate for manual investigation if the alert requires operational action.

Do not describe any of these checks as a confirmed root cause unless
independent evidence supports that conclusion.

## What the assistant should not claim

The assistant must not claim:

- that a specific feature caused the failure
- that an alert guarantees a future failure
- that the risk score is a calibrated probability
- that the current model is verified as leakage-safe before Job execution
- that a recommended check is a confirmed incident root cause

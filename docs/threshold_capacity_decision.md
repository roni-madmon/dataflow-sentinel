# Threshold and Team-Capacity Decision

## Scope

This analysis uses the frozen HGB V2 model and the chronological Validation
population only.

- Validation Jobs: 623,763
- Validation failures: 26,663
- Frozen threshold: 0.9696205830070223
- Test rows accessed during this capacity-policy analysis: 0

The model score is uncalibrated and must not be interpreted as a failure
probability.

## Frozen Threshold Behavior

At the frozen maximum-F1 threshold:

- Alerts: 45,910
- Alert rate: 7.360%
- Precision: 0.5240
- Recall: 0.9022
- F1: 0.6629
- True alerts: 24,056
- False alerts: 21,854
- Missed failures: 2,607

A large score tie exists exactly at the frozen threshold:

- Jobs above threshold: 719
- Jobs exactly at threshold: 45,191
- Failures within the tied group: 23,349
- Failure rate within the tied group: 51.67%

Therefore, threshold-only logic cannot represent every possible operational
review capacity.

## Deterministic Risk Queue

For capacity-constrained review, Jobs are ordered by:

1. model score descending
2. md5(job_run_id) ascending when model scores are exactly equal

The hash is only an operational tie-breaker.

It does not use additional predictive information and does not imply that one
equal-score Job is riskier than another.

## Exact-Capacity Validation Results

| Capacity | Alerts | Precision | Recall | F1 | False alerts | Missed failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00% | 6,238 | 0.5601 | 0.1310 | 0.2124 | 2,744 | 23,169 |
| 2.50% | 15,595 | 0.5358 | 0.3134 | 0.3955 | 7,239 | 18,307 |
| 5.00% | 31,189 | 0.5284 | 0.6181 | 0.5698 | 14,708 | 10,182 |
| 7.36% | 45,909 | 0.5240 | 0.9022 | 0.6630 | 21,853 | 2,607 |
| 10.00% | 62,377 | 0.4004 | 0.9366 | 0.5609 | 37,404 | 1,690 |
| 15.00% | 93,565 | 0.2745 | 0.9633 | 0.4273 | 67,881 | 979 |

## Recommended Operating Policies

### Constrained Capacity ? 5%

Use when investigation capacity is limited.

- Reviews: 31,189
- Recall: 61.81%
- Precision: 52.84%

This substantially reduces review volume but misses more failures.

### Balanced ? 7.36%

Recommended default development policy.

- Reviews: 45,909
- Recall: 90.22%
- Precision: 52.40%

This is effectively the frozen maximum-F1 operating point and provides the
strongest balance between failure coverage and investigation volume.

### High Coverage ? 10%

Use when missed failures are considered more costly and additional review
capacity is available.

- Reviews: 62,377
- Recall: 93.66%
- Precision: 40.04%

Increasing capacity beyond the Balanced policy produces sharply diminishing
returns.

## Marginal Capacity Observation

Moving from 5% to 7.36% requires 14,720 additional reviews and captures
7,575 additional failures.

Moving from 7.36% to 10% requires 16,468 additional reviews but captures only
917 additional failures.

Moving from 10% to 15% requires 31,188 additional reviews but captures only
711 additional failures.

For this Validation population, 7.36% is therefore a clear operational elbow.

## Product Interpretation

The model provides risk ranking.

The operational queue applies a separate capacity constraint.

The selected review capacity is a business decision, not a learned model
parameter and not evidence that any particular review volume is appropriate
for a real organization.

## Next Step

Evaluate the Constrained, Balanced, and High-Coverage policies under explicit
business-cost and prevention assumptions.

All monetary inputs must remain clearly labeled as scenario assumptions rather
than measured savings.

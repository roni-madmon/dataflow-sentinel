# Business Policy Decision

## Scope

This document translates the HGB V2 Validation results into illustrative
operational and business scenarios.

The analysis uses:

- Validation Jobs: 623,763
- Constrained policy: 5% review capacity
- Balanced policy: 7.36% review capacity
- High-Coverage policy: 10% review capacity
- Test rows accessed for this analysis: 0

All monetary values are illustrative cost units.

They are scenario assumptions, not measured company costs, realized savings,
or guaranteed ROI.

## Scenario Assumptions

The current simulator assumptions are:

- Assumed cost per failure: 100 cost units
- Assumed cost per reviewed alert: 10 cost units
- Conservative prevention rate: 10%
- Base prevention rate: 25%
- Optimistic prevention rate: 50%

The prevention rate represents the assumed fraction of correctly detected
failures that an operational intervention could actually prevent.

It is not a model metric.

## Business Formula

For each operating policy:

Prevented failures =
true alerts * assumed prevention rate

Gross avoided cost =
prevented failures * assumed cost per failure

Investigation cost =
alerts * assumed cost per reviewed alert

Expected net benefit =
gross avoided cost - investigation cost

Net benefit per 1,000 Jobs =
expected net benefit / scored Jobs * 1,000

## Scenario Results

| Policy | Scenario | Alerts | True alerts | Prevention | Net benefit | Net / 1,000 Jobs |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Constrained 5% | Conservative | 31,189 | 16,481 | 10% | -147,080 | -235.79 |
| Constrained 5% | Base | 31,189 | 16,481 | 25% | 100,135 | 160.53 |
| Constrained 5% | Optimistic | 31,189 | 16,481 | 50% | 512,160 | 821.08 |
| Balanced 7.36% | Conservative | 45,909 | 24,056 | 10% | -218,530 | -350.34 |
| Balanced 7.36% | Base | 45,909 | 24,056 | 25% | 142,310 | 228.15 |
| Balanced 7.36% | Optimistic | 45,909 | 24,056 | 50% | 743,710 | 1,192.30 |
| High Coverage 10% | Conservative | 62,377 | 24,973 | 10% | -374,040 | -599.65 |
| High Coverage 10% | Base | 62,377 | 24,973 | 25% | 555 | 0.89 |
| High Coverage 10% | Optimistic | 62,377 | 24,973 | 50% | 624,880 | 1,001.79 |

## Break-Even Prevention Rate

Under the current cost assumptions:

| Policy | Break-even prevention |
| --- | ---: |
| Constrained 5% | 18.92% |
| Balanced 7.36% | 19.08% |
| High Coverage 10% | 24.98% |

The High-Coverage policy is therefore much more sensitive to the assumed
ability to prevent correctly detected failures.

## Development Policy Decision

Balanced 7.36% is the recommended default development policy.

Reasons:

1. It captures 90.22% of Validation failures.
2. It retains approximately 52.40% precision.
3. It sits at the operational elbow identified in the capacity analysis.
4. Under the current illustrative Base assumptions, it provides the largest
   expected net benefit of the three reviewed policies.
5. Moving to 10% capacity requires substantially more reviews for relatively
   few additional detected failures.

The recommendation is conditional on the stated assumptions.

It must not be presented as an empirically proven production-optimal policy.

## Alternative Policies

### Constrained 5%

Use when review capacity is limited.

It reduces investigation volume substantially, at the cost of lower failure
coverage.

### High Coverage 10%

Use when missed failures are believed to be substantially more expensive,
review capacity is available, or investigation cost is lower than assumed.

Under the current Base assumptions this policy is almost exactly at break-even.

## Conservative Scenario

All three policies produce negative expected net benefit when only 10% of
correctly detected failures are assumed preventable.

This result is intentionally retained.

The project does not force a positive ROI and instead exposes the conditions
under which the alert-review program would or would not be economically
attractive.

## Product Interpretation

The ML model produces a risk score.

The risk queue converts scores into an investigation priority.

The capacity policy limits how many Jobs are reviewed.

The business simulator then evaluates that policy under explicit assumptions.

These are separate decision layers and should not be conflated with model
accuracy or calibrated failure probability.

## Status

Model ladder: CLOSED

Threshold analysis: CLOSED

Capacity analysis: CLOSED

Business scenario analysis: CLOSED

Default development operating policy: Balanced 7.36%

Next work should focus on product and engineering hardening rather than further
model tuning.

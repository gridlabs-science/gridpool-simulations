# Consensus Selection Audit Results

Status: reviewed wide pass.

## Runs Reviewed

First-pass honest split run:

```bash
./run_consensus_selection_audit.py \
  --out-dir reports/generated/consensus_selection_audit_long \
  --trials 10000 \
  --jobs 4 \
  --heartbeat-seconds 60
```

Wide scoring and adversarial profile run:

```bash
./run_consensus_selection_audit.py \
  --out-dir reports/generated/consensus_selection_wide_long \
  --trials 10000 \
  --profiles honest,minority_floor_flood,minority_reserve_fill \
  --jobs 4 \
  --heartbeat-seconds 60
```

Generated outputs:

- `reports/generated/consensus_selection_wide_long/report.md`
- `reports/generated/consensus_selection_wide_long/summary_by_rule.csv`
- `reports/generated/consensus_selection_wide_long/summary_by_profile_and_rule.csv`
- `reports/generated/consensus_selection_wide_long/consensus_selection_results.csv`
- `reports/generated/consensus_selection_wide_long/charts/index.html`

Eligibility-floor follow-up run:

```bash
./run_consensus_selection_audit.py \
  --out-dir reports/generated/consensus_selection_eligibility_long \
  --trials 10000 \
  --profiles honest,minority_floor_flood,minority_reserve_fill \
  --eligibility-modes none,active_snapshot_floor \
  --eligibility-alphas 0.25,0.5,0.75,1.0 \
  --jobs 4 \
  --heartbeat-seconds 60
```

Generated outputs:

- `reports/generated/consensus_selection_eligibility_long/report.md`
- `reports/generated/consensus_selection_eligibility_long/summary_by_rule.csv`
- `reports/generated/consensus_selection_eligibility_long/summary_by_profile_and_rule.csv`
- `reports/generated/consensus_selection_eligibility_long/consensus_selection_results.csv`
- `reports/generated/consensus_selection_eligibility_long/charts/index.html`

## Question

When two valid GridPool states diverge during a race, which scoring rule best
selects the side with more active hashrate?

The current node implementation uses summed proof difficulty as the primary
"heaviest state" comparison. That is intuitive as an accumulated-proof-work
metric, but proof difficulty above a floor has a heavy Pareto tail:

```text
P(D >= x | D >= floor) = floor / x
```

That tail means one monster proof can dominate a raw sum even when it came from
the smaller side of a split.

## Main Honest-Mode Result

In honest split conditions, the current raw sum rule is clearly not the best
estimator of the larger active team.

Across 60 honest variants with 10,000 trials each:

| Rule | Mean tie-adjusted accuracy | Mean minority pick | Monster-minority pick |
| --- | ---: | ---: | ---: |
| `bottom_1_times_count` | 87.6424% | 11.7225% | 6.8205% |
| `p10_times_count` | 87.2882% | 12.0157% | 7.0208% |
| `bottom_3_mean_times_count` | 86.6680% | 12.7358% | 7.6492% |
| `p25_times_count` | 86.6079% | 12.5885% | 7.4533% |
| `log_sum` | 85.7963% | 14.2032% | 10.5968% |
| `sum_capped_10x_floor` | 85.1217% | 14.8775% | 10.4890% |
| `sum_workset_difficulty` | 75.2516% | 24.7478% | 23.0877% |
| `snapshot_sum_difficulty` | 73.9146% | 25.9040% | 24.2742% |

The bottom-of-reserve/order-statistic family was strongest in honest mode.
This makes statistical sense: if the Work Set keeps the top `k` proofs, the
lowest retained proof is itself an order statistic that estimates how many
total proofs/hash attempts were needed to fill that reserve.

## Simple "Sum Minus Top N" Result

Removing a fixed number of the largest outliers helps, but does not dominate.

Honest-mode mean tie-adjusted accuracy:

| Rule | Mean tie-adjusted accuracy |
| --- | ---: |
| `sum_minus_top_3` | 81.0121% |
| `sum_minus_top_10` | 80.7993% |
| `sum_minus_top_1` | 78.7759% |
| `sum_workset_difficulty` | 75.2516% |

This confirms the intuition that monster Poisson outliers are the problem, but
fixed top-N stripping is a blunter tool than log/capped/order-statistic
estimators.

## Adversarial Profile Result

The wide run added two low-difficulty spam profiles:

- `minority_floor_flood`: the minority appends many minimum-difficulty proofs.
- `minority_reserve_fill`: the minority attempts to fill its reserve with floor
  proofs.

These profiles are intentionally adversarial stress tests. They do not
represent honest hashrate, but they reveal which scoring rules are secretly
proof-count estimators.

Profile-specific leaders:

| Profile | Best rule | Mean tie-adjusted accuracy | Mean minority pick |
| --- | --- | ---: | ---: |
| `honest` | `bottom_1_times_count` | 87.6424% | 11.7225% |
| `minority_floor_flood` | `top_1pct_trimmed_sum` | 68.7180% | 31.2817% |
| `minority_reserve_fill` | `snapshot_sum_difficulty` | 56.2751% | 43.5442% |

The important lesson is not that `snapshot_sum_difficulty` is good. It is not
great. The lesson is that if low-difficulty spam can enter the scored Work Set,
many elegant hashrate estimators become attack surfaces.

## Interpretation

There are two different problems:

1. Estimate which state represents more real active hashrate.
2. Prevent low-difficulty proof spam from changing the estimator.

Order-statistic estimators solve problem 1 well in honest conditions, but are
vulnerable to problem 2 if admission control is weak. Trimmed sums resist some
floor-flood behavior better, but give up honest-mode accuracy. Raw sum is
simple and proof-work-like, but overly sensitive to monster outliers.

This suggests the consensus selection rule should not be changed in isolation.
It should be paired with explicit scoring-admission rules.

## Current Recommendation

Do not freeze the current raw-sum state-selection rule for Umbrel/Start9 launch
without more work.

The most promising direction is a two-layer rule:

1. Score only proofs that are eligible to influence state selection.
2. Use a tail-aware estimator on those eligible proofs.

Possible admission rule:

```text
state_score_eligible(proof) =
  proof is in the retained reserve
  AND proof.difficulty >= max(global_floor, active_snapshot_floor * alpha)
```

Where `alpha` needs modeling. The goal is to prevent floor-share reserve filling
from influencing state selection while still letting new honest miners enter
the reserve.

The eligibility-floor follow-up tested this exact candidate-local
`active_snapshot_floor * alpha` idea and did **not** validate it as a sufficient
fix. It barely changed honest results at `alpha = 0.25`, degraded honest
accuracy at higher thresholds, and did not materially improve the adversarial
floor-flood or reserve-fill profiles.

Profile leaders from the eligibility run:

| Profile | Eligibility | Alpha | Best rule | Mean tie-adjusted accuracy |
| --- | --- | ---: | --- | ---: |
| `honest` | `none` | 0 | `bottom_1_times_count` | 87.6497% |
| `honest` | `active_snapshot_floor` | 0.25 | `bottom_1_times_count` | 87.6528% |
| `minority_floor_flood` | `none` | 0 | `top_1pct_trimmed_sum` | 68.7723% |
| `minority_floor_flood` | `active_snapshot_floor` | 0.25 | `top_1pct_trimmed_sum` | 68.6180% |
| `minority_reserve_fill` | `none` | 0 | `snapshot_sum_difficulty` | 56.2328% |
| `minority_reserve_fill` | `active_snapshot_floor` | 0.25 | `snapshot_sum_difficulty` | 56.3568% |

Splitting the run by common-state maturity clarified the result:

- With a mature shared reserve, order-statistic estimators such as
  `bottom_1_times_count` remain strong at roughly 88% accuracy. In that mode,
  the low-difficulty spam profiles are mostly neutralized because both sides
  already share a full retained reserve.
- With an empty or thin common reserve, low-difficulty reserve-fill attacks are
  still pathological. `snapshot_sum_difficulty` was the least-bad rule in that
  profile, but still selected the true majority only about 40% of the time in
  the empty-reserve aggregate.
- Higher candidate-local thresholds, such as `alpha = 0.5`, `0.75`, or `1.0`,
  reduced honest-mode accuracy and still did not fix the adversarial cases.

The likely reason is that candidate-local eligibility is self-referential. A
candidate state can lower or define its own active snapshot floor, so filtering
against that candidate's own floor does not reliably distinguish real
high-hashrate work from low-difficulty reserve stuffing.

The next scoring-admission model should use a non-self-referential reference
floor, such as:

- the local node's current canonical active snapshot floor before considering
  the candidate
- the local node's current canonical reserve floor before considering the
  candidate
- a recent rolling network floor that cannot be lowered by the candidate bundle
  being evaluated
- a hybrid rule that uses order-statistic scoring only after a minimum common
  reserve maturity threshold is satisfied

Candidate score families after admission control:

- `bottom_1_times_count` or `p10_times_count` if order-statistic estimation
  remains robust after filtering.
- `log_sum` if we prefer an additive transformed score with fewer ties and
  simpler intuition.
- `sum_capped_10x_floor` if we want a very simple capped-work estimator.
- `top_1pct_trimmed_sum` if adversarial flood resistance dominates honest-mode
  estimator accuracy.

## Not Ready For Consensus Change Yet

Before changing production consensus, run a narrower follow-up model with:

- explicit eligible-proof floors instead of allowing all minimum-difficulty
  proofs into the scoring set
- several `alpha` thresholds tied to active snapshot floor or reserve floor
- honest entry by new miners after a mature reserve exists
- equal-work low-difficulty/high-count versus high-difficulty/low-count
  strategies
- stale/late proof imports after split recovery
- score tie behavior under real reserve sizes

## Practical Near-Term Takeaway

The old "heaviest list" language should be sharpened. GridPool does not just
need the state with the largest raw proof-difficulty sum. It needs the state
whose proof set is the best verifiable estimator of active hashrate, while
remaining resistant to low-difficulty spam.

Raw sum is probably acceptable for the current tiny beta because all real
participants are known and low-difficulty spam can be operationally detected.
It is not a satisfying final rule for packaged public nodes.

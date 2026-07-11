# GridPool Simulation Findings For July 17 Developer Meeting

Status: working draft.

Purpose: summarize which GridPool claims are currently supported by reproducible
models, which claims need careful caveats, and which questions should remain
open during the July 17 developer discussion.

Source repo: `/home/keegreil/Documents/GitHub/gridpool-simulations`.

Curated chart packet:

- `reports/generated/july17_chart_packet/INDEX.md`

## Evidence Status At A Glance

| Topic | Current Evidence | Meeting Posture |
| --- | --- | --- |
| Payout variance | Reproducible variance sweep using actual BTC paid, with reviewed 300/100/10-slot comparisons. | Strong model-backed claim. |
| Pool hopping | Economic sweeps with deterministic FPPS and solo outside options; mechanical proof claims are explicit. | Strong mechanical claim; small/caveated economic effect. |
| Block withholding | Fee-sensitivity sweep over honest, withhold-all, and selective-withholding strategies. | Strong model-backed evidence against straightforward profit-seeking withholding. |
| Relay latency | Network latency model and generated charts; live telemetry plan exists but public-node data is not clean enough yet. | Model evidence only; field proof pending. |
| Consensus scoring | Wide honest/adversarial scoring audit, eligibility follow-up, and delayed-snapshot economics model. | Open research; V2.1 boundary-finality rule is the near-term launch-hardening point. |

## What This Does And Does Not Prove

| Supported By Current Work | Not Proven Yet |
| --- | --- |
| GridPool can replace trusted pool accounting with independently verifiable proof-of-work claims against explicit payout snapshots. | GridPool is immune to majority attackers, state-sponsored griefing, or every network-partition scenario. |
| Under modeled assumptions, 300 shared payout slots materially reduce actual BTC payout variance versus solo mining once team cadence is meaningful. | Every miner gets smooth near-term payouts at tiny launch scale. |
| Pool hopping cannot create fake work or steal other miners' earned proof claims. | Pool hopping is impossible or never rational under all outside-pool fee/liquidity/variance conditions. |
| Straightforward profit-seeking block withholding is unattractive in the current model. | Griefing is impossible when the attacker has external utility. |
| Compact relay lowers modeled snapshot-split risk relative to full JSON relay. | UDP/compact relay has been field-proven to reduce global split risk by a measured percentage. |
| V2.1 should reject/quarantine late previous-parent proofs across a locally observed Bitcoin-block boundary. | The final public-node consensus scoring rule has been selected and fully validated. |

## Recommended Framing

GridPool V2 has several promising, model-backed properties, but the correct
developer-facing posture is not "all attacks are solved." The stronger framing
is:

> GridPool replaces trusted pool accounting with independently verifiable
> proof-of-work claims against explicit payout snapshots. Simulations support
> the core variance-reduction and block-withholding-resistance arguments, while
> consensus selection under adversarial splits remains active research.

That framing is accurate and difficult for competent critics to dismiss.

## Publishable Findings

### 1. Large Payout Lists Reduce Variance Once Team Cadence Is Meaningful

Best source:

- `reports/generated/sweeps/payout_variance_fee_long`
- Chart packet figures:
  - `reports/generated/july17_chart_packet/charts/payout_variance__variance_reduction_by_slots.svg`
  - `reports/generated/july17_chart_packet/charts/payout_variance__zero_payout_probability_by_slots.svg`

The variance model treats actual BTC paid as the miner utility target, not just
slot inclusion. This matters because if team hashrate doubles, a miner may get
half as many slots per team block but team blocks arrive twice as often. Expected
BTC stays the same; variance changes because payments are more or less clumped.

Strong public claim:

> A 300-slot payout list substantially reduces payout variance compared with
> smaller lists once the team finds blocks often enough for the miner to receive
> recurring shared payouts.

Useful example from the reviewed June findings:

- `1 PH` miner, 300 slots, team multiplier `10000`: variance reduction versus
  solo about `271.7x`; zero-payout probability about `11.9%` over the modeled
  period.
- Same miner, 100 slots: variance reduction about `96.7x`; zero-payout
  probability about `48.8%`.
- Same miner, 10 slots: variance reduction about `10.0x`; zero-payout
  probability about `93.1%`.

Caveat:

Tiny miners on tiny teams remain lottery-like because expected paid events are
still rare. GridPool improves variance as team block cadence and payout-list
width become relevant.

### 2. Pool Hopping Does Not Create Fake Work

Best sources:

- `reports/generated/sweeps/pool_hopping_external_mode_299_long`
- `reports/generated/sweeps/pool_hopping_solo_target_share_299_long`
- Chart packet figures:
  - `reports/generated/july17_chart_packet/charts/pool_hopping__deterministic_fpps_delta_by_external_fee.svg`
  - `reports/generated/july17_chart_packet/charts/pool_hopping__deterministic_fpps_absolute_ev_by_external_fee.svg`
  - `reports/generated/july17_chart_packet/charts/pool_hopping__solo_delta_by_target_share.svg`

The most defensible claim is mechanical:

> Pool hopping cannot create unpaid shares or steal slots. A miner can only
> retain claims to proof-of-work it already contributed.

The economic result is more nuanced. With a zero-fee outside option, the model
can show a small free-option effect because old GridPool proofs remain payable
while the miner earns elsewhere. That is not theft; it is a consequence of
paid-once proof claims being real claims.

Useful examples:

- Idealized zero-fee deterministic FPPS outside option: hopper EV ratios in the
  reviewed sweep were around `1.0006` to `1.0020`.
- 0.5% outside fee: hopper EV ratios fell below fair gross network EV in the
  deterministic FPPS case.
- 2% outside fee: hopping clearly underperformed.
- Zero-fee solo outside option remained noisy and needs careful wording because
  variance, not just EV, changes sharply.

Safe public claim:

> Simulations found at most a small free-option effect under idealized zero-fee
> outside mining. This is not a way to forge work or steal other miners' shares,
> and realistic fees, variance, and operational costs can erase or reverse it.

Avoid:

- "Pool hopping is impossible."
- "Pool hopping is never profitable."

### 3. Block Withholding Looks Expensive

Best source:

- `reports/generated/sweeps/block_withholding_fee_sensitivity_long`
- Chart packet figures:
  - `reports/generated/july17_chart_packet/charts/block_withholding__attacker_ev_by_fees_btc.svg`
  - `reports/generated/july17_chart_packet/charts/block_withholding__attacker_delta_by_fees_btc.svg`

Modeled strategies:

- honest mining;
- withhold every valid Bitcoin block;
- withhold only when the attacker is underrepresented in the active snapshot.

Attacker EV ratios from the reviewed run:

- Withhold all, fees `0.0 BTC`: about `0.8345`.
- Withhold all, fees `0.05 BTC`: about `0.8214`.
- Withhold all, fees `0.25 BTC`: about `0.7727`.
- Withhold all, fees `1.0 BTC`: about `0.6322`.
- Selective underrepresentation withholding also underperformed honest mining.

Safe public claim:

> In the current model, withholding valid GridPool blocks is costly because the
> finder gives up slot 0, transaction fees, and the acceleration of its own
> existing shared payout claims.

Caveat:

This does not prove that griefing is impossible. It shows that straightforward
profit-seeking withholding is unattractive under the modeled assumptions.

### 4. Compact Relay Reduces Modeled Snapshot-Split Risk

Best source:

- `reports/generated/sweeps/latency_peer_degree_long`
- Chart packet figures:
  - `reports/generated/july17_chart_packet/charts/latency__split_rate_by_node_count_degree_8.svg`
  - `reports/generated/july17_chart_packet/charts/latency__payload_by_node_count_degree_8.svg`

Relay profiles:

- JSON/HTTP relay: share mean `650 ms`, block mean `850 ms`, payload `2200 B`.
- Compact WebSocket relay: share mean `190 ms`, block mean `850 ms`, payload
  `900 B`.
- UDP-fast relay with fallback: share mean `35 ms`, block mean `850 ms`,
  payload `900 B`, fallback probability `1%`.

Selected degree-8 model results:

- 16 nodes: JSON split rate `0.0050`, compact WebSocket `0.00083`, UDP `0.0`.
- 24 nodes: JSON `0.00542`, compact WebSocket `0.00208`, UDP `0.0`.
- 48 nodes: JSON `0.01333`, compact WebSocket `0.00542`, UDP `0.00083`.

Safe public claim:

> The network model suggests compact relay materially reduces snapshot splits
> compared with full JSON relay, and UDP-fast relay may reduce them further.

Caveat:

This is model evidence. Real-world measurement is still needed.

### 5. Consensus Boundary Finality Is The Main V2 Launch Risk

Best sources:

- `docs/consensus-selection-audit-results-2026-06.md`
- `reports/generated/consensus_selection_wide_long`
- `reports/generated/consensus_selection_eligibility_long`
- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.0001`
- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.001`
- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.01`
- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.03`
- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.10`
- Chart packet figures:
  - `reports/generated/july17_chart_packet/charts/consensus__honest_mature_accuracy_split_900.svg`
  - `reports/generated/july17_chart_packet/charts/consensus__floor_flood_empty_accuracy_split_900.svg`
  - `reports/generated/july17_chart_packet/charts/consensus__reserve_fill_empty_active_snapshot_floor_0p25_accuracy.svg`

Raw summed proof difficulty is simple and Bitcoin-like, but proof difficulty has
a heavy Pareto tail:

```text
P(D >= x | D >= floor) = floor / x
```

In honest split simulations, the current raw sum rule was not the best estimator
of which side had more active hashrate. Order-statistic estimators such as
`bottom_1_times_count` and `p10_times_count` were much stronger in honest
conditions.

Honest-mode mean tie-adjusted accuracy from the wide run:

- `bottom_1_times_count`: about `87.64%`.
- `p10_times_count`: about `87.29%`.
- `log_sum`: about `85.80%`.
- `sum_workset_difficulty`: about `75.25%`.
- `snapshot_sum_difficulty`: about `73.91%`.

But adversarial floor-fill profiles remain unresolved. Candidate-local
eligibility floors did not fix the issue.

The delayed-snapshot attack model separated two questions that had been blended
together:

- Honest same-boundary scoring: which valid Work Set best estimates the
  stronger team?
- Retroactive boundary replacement: can stale-parent proofs that arrive after a
  node observed a Bitcoin block rewrite that node's already-created payout
  snapshot?

The second question is the short-term V2.1 launch-hardening point. In the model, a stale
branch attacker intentionally mines invalid-for-tip work for one Bitcoin block
to create a delayed branch with more attacker-favorable shared slots. Those
slots are now survival-discounted: easy low-difficulty proofs on a weak early
list are unlikely to remain in the top shared slots by the time the team finds a
real GridPool block.

With a mature reserve, the strategy becomes economically unattractive once
GridPool is a meaningful share of Bitcoin network hashrate. At small launch
scale it can still look mildly profitable if retroactive snapshot replacement is
allowed, but the edge is much smaller than an obsolete immediate-slot model
suggested.

The intended V2.1 rule closes that retroactive stale-branch entry door without
discarding ordinary split recovery:

- previous-parent proofs that arrive after the local Bitcoin-block boundary are
  rejected or quarantined from the canonical reserve and do not rewrite the
  already-active payout snapshot;
- current-parent proofs mined against a divergent retained payout snapshot can
  still merge forward into the unpaid Work Set after full validation;
- established nodes should not replace an already-active snapshot merely
  because a same-round peer branch claims to be heavier.

One-block stale-window examples with a mature `897`-proof reserve:

- Pool at `0.1%` of Bitcoin network, attacker at `51%` of GridPool:
  reward/cost about `2.14x`, expected net about `+0.00185 BTC`.
- Pool at `1%` of Bitcoin network, attacker at `51%` of GridPool:
  reward/cost about `0.94x`, expected net about `-0.00095 BTC`.
- Pool at `3%` of Bitcoin network, attacker at `51%` of GridPool:
  reward/cost about `0.50x`, expected net about `-0.02449 BTC`.

Safe public claim:

> The current V2.1 rule is acceptable for small live beta testing if nodes
> reject/quarantine late previous-parent proofs while still merging valid
> current-parent divergent proofs forward. Packaged release should wait until
> this behavior is covered by regression tests and live multi-node soak data.

This is deliberately narrower than saying that the consensus scoring problem is
solved. It says the launch path should not depend on retroactive replacement of
a locally finalized payout snapshot.

Avoid:

- "GridPool is immune to 51% attacks."
- "Heaviest-state branch replacement is the normal convergence rule."

## Recommended Slide / Paper Structure

1. Problem: centralized pool custody/accounting and variance tradeoffs.
2. GridPool mechanism: slot-0 finder plus verifiable shared payout snapshot.
3. V2 snapshot/reserve mechanics: Bitcoin-block snapshots, paid-once proof
   lineage.
4. Variance model: why 300 slots matter.
5. Pool hopping: earned claims versus fake claims.
6. Block withholding: why finder-owned slot 0 and fees change incentives.
7. Latency model: split risk and compact relay.
8. Open research: snapshot-boundary finality and consensus scoring under
   adversarial splits.
9. Roadmap: real network measurements, boundary-finality tests, scoring model,
   and packaging after consensus version freeze.

## Claims To Avoid On July 17

- GridPool is final.
- GridPool has no latency incentives.
- GridPool cannot split.
- GridPool is immune to majority miners.
- Pool hopping can never have a positive EV edge.
- UDP relay is proven in production.

## Work Still Worth Doing Before July 17

1. Run one focused consensus-selection follow-up using non-self-referential
   floors.
2. Collect preliminary live relay telemetry from the current public nodes if
   Main, Dallas, and Evomining are synced and UDP observations are visible.
3. Write a one-page FAQ answer for pool hopping and block withholding.
4. If the chart packet should be committed, promote the reviewed generated
   packet out of ignored `reports/generated/` into a tracked review directory.

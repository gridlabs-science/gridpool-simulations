# Recommended Simulation Runs Before July 17

Status: draft.

This file lists the remaining runs that would most improve the July 17
developer-meeting package.

Current packet status as of 2026-07-10:

- A curated chart packet exists at
  `reports/generated/july17_chart_packet/INDEX.md`.
- Core long-run charts are already gathered for payout variance, pool hopping,
  block withholding, latency, and consensus-selection caveats.
- The highest-value remaining compute task is still the reserve-floor
  consensus-selection follow-up below. It is useful for research discussion, but
  the V2.1 boundary-finality launch posture should not depend on proving a final
  scoring rule before July 17.

## Run 1: Canonical V2 Baseline Refresh

Purpose: regenerate the core public charts using the current V2 parameters:
299 shared slots, 300 total slots, 3x reserve, paid-once reserve, no custom
decay/punishment rules.

Command:

```bash
cd /home/keegreil/Documents/GitHub/gridpool-simulations

nohup ./run_research_batch.sh \
  --jobs 4 \
  --heartbeat-seconds 60 \
  > reports/generated/research_batch_july17_refresh.log 2>&1 &
```

Watch:

```bash
tail -f reports/generated/research_batch_july17_refresh.log
```

Expected value:

- Confirms the old reviewed findings still reproduce.
- Refreshes charts with the current plotting labels.

## Run 2: Focused Consensus Scoring Follow-Up

Purpose: test non-self-referential scoring floors. The previous eligibility run
used candidate-local active snapshot floor and did not solve adversarial
floor-fill cases.

The current runner already supports `reserve_floor`, which is less
self-referential than candidate-local `active_snapshot_floor`. A targeted smoke
was completed at:

- `reports/generated/consensus_selection_reserve_floor_targeted_smoke`

Long-run command:

```bash
cd /home/keegreil/Documents/GitHub/gridpool-simulations

python3 run_consensus_selection_audit.py \
  --out-dir reports/generated/consensus_selection_reserve_floor_july17_long \
  --trials 10000 \
  --majority-shares 0.51,0.55,0.60,0.67,0.75,0.90 \
  --split-proofs 10,30,100,300,900 \
  --common-modes empty,mature \
  --profiles honest,minority_floor_flood,minority_reserve_fill \
  --eligibility-modes none,reserve_floor \
  --eligibility-alphas 0.25,0.5,0.75,1.0 \
  --jobs 4 \
  --heartbeat-seconds 60
```

Expected value:

- Directly tests whether a candidate-independent reserve-floor eligibility
  filter improves the adversarial floor-fill problem.
- This is the highest value remaining modeling work because consensus scoring is
  the main unresolved launch-hardening question.

## Run 3: Longer Latency Peer-Degree Run

Purpose: improve confidence intervals for the compact/UDP latency model and
regenerate charts with clearer payload labels.

Command:

```bash
cd /home/keegreil/Documents/GitHub/gridpool-simulations

python3 run_sweep.py \
  --sweep sweeps/latency_peer_degree_sweep.json \
  --out-dir reports/generated/sweeps/latency_peer_degree_july17_long \
  --jobs 4 \
  --heartbeat-seconds 60

python3 plot_sweep_results.py \
  --csv reports/generated/sweeps/latency_peer_degree_july17_long/sweep_results.csv \
  --out-dir reports/generated/sweeps/latency_peer_degree_july17_long/charts
```

Expected value:

- Better chart packet for the July 17 talk.
- Still model evidence, not field proof.

## Run 4: Pool-Hopping Target Share Recheck

Purpose: verify the solo outside-option result for 15%, 35%, 60%, and 80%
target team share.

Command:

```bash
cd /home/keegreil/Documents/GitHub/gridpool-simulations

python3 run_sweep.py \
  --sweep sweeps/pool_hopping_solo_target_share_299_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_solo_target_share_299_july17_long \
  --jobs 4 \
  --heartbeat-seconds 60

python3 analyze_pool_hopping_sweep.py \
  --csv reports/generated/sweeps/pool_hopping_solo_target_share_299_july17_long/sweep_results.csv \
  --out reports/generated/sweeps/pool_hopping_solo_target_share_299_july17_long/analysis.md

python3 plot_sweep_results.py \
  --csv reports/generated/sweeps/pool_hopping_solo_target_share_299_july17_long/sweep_results.csv \
  --out-dir reports/generated/sweeps/pool_hopping_solo_target_share_299_july17_long/charts
```

Expected value:

- Tightens the most likely critic question.
- Should be presented carefully because solo outside mining changes variance,
  not just expected value.

## Priority Order

1. Consensus scoring follow-up.
2. July 17 findings draft and chart cleanup.
3. Pool-hopping recheck.
4. Latency recheck.

If compute time is limited, do not spend it on V3 branch-market modeling before
July 17. V3 is interesting, but V2 consensus scoring and incentive claims are
more important for the meeting.

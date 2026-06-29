# Simulation Sweeps

Sweep files define parameter grids for `run_sweep.py`.

Supported engines:

- `economic`
- `network`
- `adversary`
- `variance`

Basic smoke:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_reserve_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_reserve_smoke \
  --quick \
  --max-variants 2
```

Use more cores for longer runs:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_reserve_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_reserve \
  --jobs 4
```

Generated sweep outputs:

- `summary.json`
- `sweep_results.csv`
- `report.md`
- `progress.json`
- `progress.log`

The generated report is a quick preview. Use the CSV for real analysis and
plotting.

Long sweeps checkpoint after every completed variant, so partial results survive
an interrupt or early stop. `progress.json` contains the latest status and ETA.
`progress.log` is append-only and can be tailed while a run is active:

```bash
tail -f reports/generated/sweeps/pool_hopping_focused_299_long/progress.log
```

## Fire-And-Forget Research Batch

To run the main pending research sweeps sequentially:

```bash
nohup run_research_batch.sh \
  --jobs 4 \
  --heartbeat-seconds 60 \
  > reports/generated/research_batch.log 2>&1 &
```

Watch the top-level batch log:

```bash
tail -f reports/generated/research_batch.log
```

Watch a specific active sweep:

```bash
tail -f reports/generated/sweeps/pool_hopping_external_mode_299_long/progress.log
```

The batch currently runs:

- `pool_hopping_external_mode_299_sweep.json`
- `payout_variance_fee_sweep.json`
- `latency_peer_degree_sweep.json`
- `majority_cartel_share_sweep.json`

The batch skips a sweep if its `progress.json` already says `complete`, so it is
safe to rerun after an interruption. It also writes
`analysis.md` for the pool-hopping external-mode sweep, plus `charts.md` and SVG
charts for every sweep.

## Incentive Research Batch

To run the next pool-hopping and incentive-design batch:

```bash
nohup run_incentive_research_batch.sh \
  --jobs 4 \
  --heartbeat-seconds 60 \
  > reports/generated/incentive_research_batch.log 2>&1 &
```

Watch the top-level batch log:

```bash
tail -f reports/generated/incentive_research_batch.log
```

Watch a specific active sweep:

```bash
tail -f reports/generated/sweeps/pool_hopping_physical_scale_solo_299_long/progress.log
```

The incentive batch currently runs:

- `pool_hopping_universal_solo_299_sweep.json`: tests whether the apparent hopping edge survives if every miner can use the same solo-outside option.
- `pool_hopping_physical_scale_solo_299_sweep.json`: tests 100 PH, 300 PH, 1 EH, and 3 EH miners on 1 EH to 10 EH GridPool teams, assuming a 600 EH Bitcoin network.
- `pool_hopping_fee_sensitivity_299_sweep.json`: tests whether higher Bitcoin transaction fees strengthen the stay-on-GridPool incentive through the slot-0 fee bonus.
- `block_withholding_fee_sensitivity_sweep.json`: tests whether higher Bitcoin transaction fees change block-withholding incentives.
- `pool_hopping_snapshot_policy_299_sweep.json`: compares current paid-once reserve consensus against the old clear-each-Bitcoin-block concept.

The economic sweeps now report `mean_inactive_snapshot_slots`,
`mean_inactive_snapshot_fraction`, and `mean_active_team_hashrate_share`. These
metrics are useful for separating the emotional objection to pool hopping from
the measurable burden of old earned claims remaining in the active payout list.

You can generate charts for any completed sweep directly:

```bash
python3 plot_sweep_results.py \
  --csv reports/generated/sweeps/pool_hopping_focused_299_long/sweep_results.csv \
  --out-dir reports/generated/sweeps/pool_hopping_focused_299_long/charts
```

## Long-Run Suggestions

Pool-hopping reserve/slot sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_reserve_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_reserve_long \
  --jobs 4
```

Focused 299-slot pool-hopping sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_focused_299_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_focused_299_long \
  --jobs 4 \
  --heartbeat-seconds 60
```

Analyze the completed focused sweep:

```bash
python3 analyze_pool_hopping_sweep.py \
  --csv reports/generated/sweeps/pool_hopping_focused_299_long/sweep_results.csv \
  --out reports/generated/sweeps/pool_hopping_focused_299_long/analysis.md
```

External-mode 299-slot pool-hopping sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_external_mode_299_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_external_mode_299_long \
  --jobs 4 \
  --heartbeat-seconds 60
```

This compares the current deterministic FPPS-like outside option against a solo
outside option. On this dev machine, expect it to be in the same ballpark as
the previous focused pool-hopping long run, but somewhat longer because it uses
`64` replications across `6` variants.

Targeted solo pool-hopping sweep by hopper team share:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_solo_target_share_299_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_solo_target_share_299_long \
  --jobs 4 \
  --heartbeat-seconds 60

python3 analyze_pool_hopping_sweep.py \
  --csv reports/generated/sweeps/pool_hopping_solo_target_share_299_long/sweep_results.csv \
  --out reports/generated/sweeps/pool_hopping_solo_target_share_299_long/analysis.md

python3 plot_sweep_results.py \
  --csv reports/generated/sweeps/pool_hopping_solo_target_share_299_long/sweep_results.csv \
  --out-dir reports/generated/sweeps/pool_hopping_solo_target_share_299_long/charts
```

This is the apples-to-apples solo comparison: GridPool has no pool fee, the
outside destination is solo mining with no pool fee, and the hopper's share of
the GridPool team varies from `15%` to `80%`.

Network latency peer-degree sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/latency_peer_degree_sweep.json \
  --out-dir reports/generated/sweeps/latency_peer_degree_long \
  --jobs 4
```

Majority/censorship cartel-share sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/majority_cartel_share_sweep.json \
  --out-dir reports/generated/sweeps/majority_cartel_share_long \
  --jobs 4
```

Variance scenarios can also be run directly without a sweep:

```bash
python3 run_variance_analysis.py \
  --scenario scenarios/payout_variance.json \
  --out-dir reports/generated/payout_variance
```

Payout variance fee/support sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/payout_variance_fee_sweep.json \
  --out-dir reports/generated/sweeps/payout_variance_fee_long \
  --jobs 4
```

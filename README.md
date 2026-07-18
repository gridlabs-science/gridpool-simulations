# GridPool Simulations

Modeling and simulations for the GridPool reward-sharing protocol.

Current July 17 research update:

- [GridPool V2.1 research update](reports/july17/gridpool-july17-research-update-v1.md)
- [Printable PDF](reports/july17/gridpool-july17-research-update-v1.pdf)
- [Live network appendix](reports/july17/live-telemetry/live-network-appendix.md)

Superseded handouts and the editor-annotated source are retained under
`reports/july17/archive/`.

This repository is intentionally separate from the live GridPool node implementation. That keeps mechanism-design research, long Monte Carlo sweeps, generated charts, and academic notes from dirtying the runtime codebase when urgent node fixes need to ship.

## Goals

The simulator exists to turn GridPool claims into reproducible evidence:

- payout fairness under V2 snapshot/reserve consensus
- actual BTC payout variance across miner sizes
- comparison against solo mining and idealized FPPS
- pool-hopping incentives and outside-pool strategies
- block-withholding incentives
- majority-miner, censorship, and private-team split behavior
- latency-driven snapshot splits across bounded peer graphs
- bandwidth and payload scaling across network size and peer degree

The models are not consensus code. They are research tools. Once a mechanism invariant is stable, it can be ported into the main GridPool node test suite.

## Repository Layout

- `gridpool_sim/`: shared simulation engine and reporting helpers
- `scenarios/`: runnable scenario configs
- `sweeps/`: parameter sweep configs for longer batch runs
- `reports/`: reviewed/promoted report outputs
- `reports/generated/`: ignored local output directory for long runs
- `docs/modeling-and-simulation-roadmap.md`: roadmap and claims still needing stronger modeling
- `docs/critic-faq.md`: technical FAQ and argument map for critics
- `docs/consensus-selection-audit-results-2026-06.md`: first-pass findings on state-selection scoring
- `docs/july-17-developer-meeting-findings.md`: publishable/caveated findings draft for the July 17 developer meeting
- `docs/next-runs-before-july-17.md`: prioritized remaining sweeps and commands before the meeting
- `docs/live-relay-telemetry-plan.md`: plan for collecting preliminary public-node relay latency data

## Quick Start

Use Python 3.10+.

```bash
python3 run_simulation.py \
  --scenario scenarios/honest_baseline.json \
  --out-dir reports/generated/honest_baseline
```

Faster smoke run:

```bash
python3 run_simulation.py \
  --scenario scenarios/pool_hopping.json \
  --out-dir reports/generated/smoke \
  --quick
```

Each ordinary run writes:

- `summary.json`
- `miner_results.csv`
- `paired_strategy_deltas.csv`
- `report.md`

Variance runs write `variance_results.csv`.

## Common Runs

Pool-hopping strategy comparison:

```bash
python3 run_simulation.py \
  --scenario scenarios/pool_hopping.json \
  --out-dir reports/generated/pool_hopping
```

Block-withholding comparison:

```bash
python3 run_simulation.py \
  --scenario scenarios/block_withholding.json \
  --out-dir reports/generated/block_withholding
```

Majority-miner / censorship abstraction:

```bash
python3 run_adversary_simulation.py \
  --scenario scenarios/majority_censorship.json \
  --out-dir reports/generated/majority_censorship
```

Latency and relay profile comparison:

```bash
python3 run_network_simulation.py \
  --scenario scenarios/latency_splits.json \
  --out-dir reports/generated/latency_splits
```

Payout variance benchmark against solo and idealized FPPS:

```bash
python3 run_variance_analysis.py \
  --scenario scenarios/payout_variance.json \
  --out-dir reports/generated/payout_variance
```

Consensus-selection scoring audit:

```bash
python3 run_consensus_selection_audit.py \
  --out-dir reports/generated/consensus_selection_audit \
  --trials 10000 \
  --profiles honest,minority_floor_flood,minority_reserve_fill \
  --eligibility-modes none,active_snapshot_floor \
  --eligibility-alphas 0.25,0.5,0.75,1.0 \
  --jobs 4 \
  --heartbeat-seconds 60
```

V3 branch-market resource envelope:

```bash
python3 run_branch_market_resource_model.py \
  --out-dir reports/generated/branch_market_resource_model
```

V2.1 disagreement persistence through cutoff displacement and payment:

```bash
python3 run_v21_disagreement_persistence.py \
  --out-dir reports/generated/v21_disagreement_persistence \
  --blocks 10000 \
  --replications 12 \
  --jobs 8
```

V2.1 selective-inclusion and merge-forward incentive test:

```bash
python3 run_v21_selective_inclusion.py \
  --out-dir reports/generated/v21_selective_inclusion \
  --blocks 3000 \
  --replications 20
```

This run compares an inclusive honest baseline with a miner that excludes
other proofs while either relaying its own proofs (`free_ride`) or withholding
them (`private_split`). See `docs/v21-selective-inclusion-model.md` for the
threat model and interpretation gates.

Ranked-proof aggregate and per-miner sampling calibration:

```bash
python3 run_ranked_proof_calibration.py \
  --out-dir reports/generated/ranked_proof_calibration \
  --trials 250000
```

Parameter sweep:

```bash
python3 run_sweep.py \
  --sweep sweeps/pool_hopping_reserve_sweep.json \
  --out-dir reports/generated/sweeps/pool_hopping_reserve \
  --jobs 4
```

## Long Research Batch

For the current incentive-research batch:

```bash
nohup ./run_incentive_research_batch.sh \
  --jobs 4 \
  --heartbeat-seconds 60 \
  > reports/generated/incentive_research_batch.log 2>&1 &
```

Watch progress:

```bash
tail -f reports/generated/incentive_research_batch.log
```

Analyze a completed pool-hopping sweep:

```bash
python3 analyze_pool_hopping_sweep.py \
  --csv reports/generated/sweeps/pool_hopping_focused_299_long/sweep_results.csv \
  --out reports/generated/sweeps/pool_hopping_focused_299_long/analysis.md
```

Generate charts:

```bash
python3 plot_sweep_results.py \
  --csv reports/generated/sweeps/pool_hopping_focused_299_long/sweep_results.csv \
  --out-dir reports/generated/charts
```

## Model Notes

The simulator uses scaled Bitcoin-block intervals. Each interval represents one ordinary Bitcoin block found by the wider network.

For each interval:

1. Active GridPool miners generate share proofs above the configured admission floor.
2. Share difficulty is sampled from the expected heavy-tailed proof-of-work distribution.
3. If a share exceeds scaled network difficulty, GridPool found the Bitcoin block and pays the currently active snapshot.
4. Paid proof IDs are removed from the unpaid Work Set.
5. A new snapshot is built from the highest-ranked unpaid proofs.

The scaled network difficulty is chosen so that:

```text
expected_gridpool_blocks_per_bitcoin_block = pool_network_share
```

This keeps simulations compact without changing the Poisson mechanics relevant to Work Set competition.

For payout variance, snapshot inclusion is treated as an intermediate mechanism, not the miner utility target. The variance model measures actual BTC paid over a fixed period. GridPool is modeled as a compound Poisson process: team blocks arrive at a rate proportional to team hashrate, and each team block pays a miner approximately `Binomial(K, p)` shared slots, where `K` is the number of shared payout slots and `p` is the miner's fraction of team hashrate.

If team hashrate grows while a miner's hashrate is fixed, blocks arrive more often and `p` shrinks. Those effects cancel in expected BTC. Variance changes because payouts become more or less clumped across blocks.

## Limitations

The economic simulator assumes honest, instant propagation and a single shared view of the Work Set. The network simulator adds relay latency and bounded peer topology, but it is still an approximation rather than a packet-level emulator.

The majority/censorship simulator is a two-team abstraction. It is useful for testing whether censorship steals expected value or mostly creates a separate team with worse variance and UX. It is not yet a full peer-network or heaviest-state adoption model.

The pool-hopping reports support `external_payout_mode`:

- `deterministic_fpps` credits inactive hashrate with deterministic outside-pool expected value. This is intentionally generous and isolates expected-value strategy effects from external variance.
- `solo` gives inactive hashrate the same expected outside value, but pays it only when it stochastically finds an outside block.

Neither mode is a full model of FPPS/PPLNS economics. Real external pools add fees, stale policy, payout thresholds, solvency/counterparty risk, withdrawal timing, and operator-specific transaction-fee policy.

FPPS in the variance report is an idealized zero-variance benchmark at configured fee rate. It does not model pool counterparty risk, payout thresholds, stale share policies, transaction-fee policy, or operator solvency.

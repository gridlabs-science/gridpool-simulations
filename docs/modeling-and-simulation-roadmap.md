# GridPool Modeling And Simulation Roadmap

Status: draft.

Purpose: define the rigorous, open-source modeling work needed to evaluate
GridPool's fairness, incentive compatibility, network dynamics, bandwidth, and
attack resistance.

This is not a marketing checklist. The goal is to make GridPool legible to
technically competent critics by publishing reproducible models, assumptions,
source code, and results.

## Guiding Principles

1. Model adversaries explicitly.
2. Separate protocol claims from current implementation performance.
3. Use deterministic seeds so every graph and table can be reproduced.
4. Compare against relevant baselines: solo mining, centralized PPLNS/FPPS-style
   pools, and sharechain-style decentralized pools.
5. Publish failures. A model that finds an edge-case weakness is useful.
6. Keep simulations parameterized so assumptions can be challenged.

## Core Mathematical Model

Mining can be modeled as a Poisson process.

For a miner with hashrate `h`, the expected rate of shares above difficulty `d`
is approximately:

```text
lambda(d) = h / (d * 2^32)
```

This gives a natural simulation basis:

- block arrivals are Poisson events at network difficulty
- share arrivals above an admission floor are Poisson events
- share difficulty has a heavy-tailed distribution
- top-k Work Set selection can be modeled through order statistics
- payout snapshots are deterministic functions of the ranked unpaid Work Set

The heavy tail matters. A miner can occasionally produce a share far above its
typical contribution. The modeling suite must account for that directly rather
than smoothing everything into normal distributions.

## Model A: Honest Baseline Fairness

Question:

Does GridPool pay miners in proportion to contributed hashrate over time under
honest continuous mining?

Inputs:

- number of miners
- miner hashrate distribution
- network difficulty
- transaction fee assumptions
- payout slot count
- support slot on/off
- reserve depth
- Work Set admission floor
- simulation duration

Outputs:

- expected payout by miner
- actual payout variance by miner over fixed time windows
- time-to-first-payout distribution
- paid slot distribution
- payout-event frequency
- realized payout / expected payout ratio
- comparison to solo variance
- comparison to idealized FPPS/PPLNS

Initial pass criteria:

- long-run mean payout converges near hashrate share after accounting for slot 0,
  transaction fees, and support slot settings
- variance reduction approaches the expected slot-count behavior for miners large
  enough to appear in snapshots regularly
- small miners show lottery-like behavior without systematic bias
- miners are evaluated by BTC paid over time, not merely by snapshot inclusion

## Model B: Pool-Hopping Strategies

Question:

Can a miner improve expected value by mining GridPool only until it earns a high
difficulty proof or payout slots, then leaving?

Strategies to simulate:

- always mine GridPool
- leave after first snapshot slot
- leave after `N` snapshot slots
- leave after one outlier proof above threshold `X`
- join only after fee spikes
- split hashrate between GridPool and another pool
- switch to FPPS/PPLNS after a lucky GridPool streak
- intermittent solar/off-grid miner with random uptime

Metrics:

- expected value
- variance
- downside tail risk
- harm or benefit to remaining miners
- average time old proofs stay payable after miner exits
- reserve displacement time after exit

Expected hypothesis:

Leaving after a lucky proof should not create positive expected value relative
to continuous mining, because the miner gives up future proof production and
slot-0 block-finder upside. But this must be demonstrated, not asserted.

Current status:

The first focused 299-slot long sweep showed no catastrophic pool-hopping
exploit, but it did expose a small free-option effect under an idealized
zero-fee deterministic FPPS-like outside option. In that model, already-earned
GridPool proofs remain payable while the miner temporarily earns expected value
elsewhere. Realistic outside-pool fees reduced or eliminated the apparent edge
in the tested runs. A later solo-outside target-share sweep showed that large
miners can sometimes create a low-single-digit free-option edge by mining solo
after earning GridPool claims. That finding is not the same as forged work or
theft from other miners, but it deserves direct modeling. Future reports should
therefore separate:

- absolute EV versus theoretical network-hashrate EV
- paired delta versus the always-on GridPool baseline
- deterministic outside-pool expected value
- stochastic solo-style outside mining variance
- inactive snapshot-slot burden on miners who remain in GridPool
- whether the apparent edge remains when every miner can use the same strategy

Important distinction:

A miner may rationally prefer another pool because of lower variance, different
fees, operational simplicity, or liquidity needs. That is not the same as a
pool-hopping exploit.

## Model C: Majority Miner And Intentional Forks

Question:

What happens when a miner or cartel controls a large fraction of GridPool
hashrate and refuses to relay or accept other miners' proofs?

Adversary configurations:

- 51 percent
- 67 percent
- 75 percent
- 90 percent
- 99 percent

Strategies:

- reject one target address
- reject all non-cartel shares
- build a private Work Set
- reveal a heavier private state only near block events
- relay selectively to partition peers
- mine honestly but delay proof relay

Metrics:

- probability of durable team split
- attacker expected value
- victim expected value
- honest miner convergence time
- percentage of work wasted on minority snapshots
- conditions under which honest miners should switch teams

Questions to answer:

- Is the attack profitable, or just griefing?
- Can a majority miner steal, or only split?
- Does the "heaviest valid payout state" rule converge under selective relay?
- How much honest relay connectivity is required to defeat targeted censorship?

Current implementation:

- `run_adversary_simulation.py`
- `scenarios/majority_censorship.json`
- two-team abstraction for honest single team, cartel private split, target-only
  censorship, and unsafe naive-target behavior
- first-pass metrics for team blocks won, miner EV ratio, rejected-by-team
  proofs, and snapshot-slot observations

## Model D: Block Withholding

Question:

Does GridPool materially reduce or remove the classic pool-layer block
withholding incentive?

Strategies:

- honest mining
- withhold valid Bitcoin blocks while still submitting non-block shares
- withhold only when attacker has low snapshot share
- withhold only when attacker has high snapshot share
- withhold to grief the team rather than maximize profit

Cost model:

- forfeited slot-0 reward
- forfeited transaction fees
- forfeited attacker's own snapshot payouts
- delayed or reduced team block rate
- effect on attacker's future snapshot share

Metrics:

- attacker expected value
- honest miner expected value
- break-even conditions
- griefing cost ratio
- detectability signals, such as high share contribution with suspiciously low
  block-finder rate over long windows

Expected hypothesis:

Because the finder receives slot 0 plus fees directly, withholding a real block
is expensive. GridPool may be more resistant than centralized pools where the
attacker can earn pool shares while hiding blocks. This should be modeled with
actual fee and slot assumptions.

Current implementation:

- `run_simulation.py`
- `scenarios/block_withholding.json`
- strategy variants for honest mining, withholding all valid blocks, and
  withholding only while underrepresented in the active snapshot
- first-pass metrics for mean published block finds, withheld blocks, GridPool
  payout, external payout, and gross hashrate EV ratio

## Model E: Network Latency And Snapshot Splits

Question:

How often do nodes disagree on the active payout snapshot, and how much work is
lost before convergence?

Network parameters:

- node count
- peer degree
- graph topology
- propagation delay distribution
- packet loss
- peer churn
- node outage/rejoin behavior
- compact relay enabled/disabled
- UDP relay enabled/disabled

Event parameters:

- Bitcoin block rate
- share arrival rate
- shares arriving near Bitcoin block boundaries
- simultaneous or near-simultaneous snapshots

Metrics:

- snapshot divergence frequency
- divergence duration p50/p95/p99
- percent of hashrate mining minority snapshot
- stale or rejected share burst size
- convergence time after peer outage
- benefit of compact relay versus JSON relay
- benefit of UDP relay versus WebSocket/HTTP relay

Comparison target:

This model should explicitly compare GridPool's latency sensitivity with
P2Pool-style sharechains. P2Pool v1 suffered because 30-second share blocks made
propagation latency economically meaningful. GridPool snapshots occur on Bitcoin
block cadence, but late high-difficulty shares around snapshot boundaries can
still create team splits. The model should quantify that difference.

## Model F: Actual Payout Variance And Utility

Question:

How much variance reduction does GridPool provide to miners of different sizes,
and how does that compare with pure solo mining and idealized FPPS?

Core distinction:

Snapshot inclusion is not the miner utility target. The relevant metric is
actual BTC paid over a fixed period. If a miner with fixed hashrate joins a
larger GridPool team, it appears in fewer slots per team block, but the team
finds blocks more often. Those effects cancel in expected BTC.

Approximate model:

```text
p = miner_hashrate / team_hashrate
K = shared payout slots
team_blocks ~ Poisson(lambda_team)
shared_slots_per_team_block ~ Binomial(K, p)
```

Expected shared slots per period:

```text
E[paid_shared_slots] = lambda_team * K * p
```

Because `lambda_team` grows linearly with team hashrate while `p` shrinks
linearly, expected payout is driven by the miner's own hashrate over time, not
by per-block slot inclusion frequency.

Metrics:

- BTC mean, standard deviation, and coefficient of variation over fixed periods
- probability of zero payout in the period
- paid slots per period
- payout events per period
- variance reduction versus pure solo
- distance from idealized FPPS
- sensitivity to payout-list size
- sensitivity to transaction fees in slot 0
- sensitivity to team size relative to the miner

Current implementation:

- `run_variance_analysis.py`
- `scenarios/payout_variance.json`
- analytic compound-Poisson benchmark for GridPool, pure solo, and idealized
  FPPS

Interpretation target:

This model should support precise claims such as:

> For a miner with fixed hashrate, increasing total team hashrate does not
> reduce expected BTC. It changes payout clumping. Larger payout lists reduce
> variance by increasing the number of independent payout quanta per GridPool
> block, subject to slot-0 fee variance.

## Model G: Bandwidth And Storage Scaling

Question:

Can GridPool scale to many miners and many nodes without turning public seed
nodes into central infrastructure?

Parameters:

- peer count
- bounded peer degree
- share proof size
- reserve depth
- snapshot context retention
- accepted Work Set share rate
- rejected share rate
- state-bundle fetch frequency
- peer polling interval

Metrics:

- bytes/sec per node
- bytes/sec at seed nodes
- CPU time per proof validation
- memory footprint
- disk writes per hour
- state bundle size
- rejoin sync time after outage

Scenarios:

- home miner with outbound-only connectivity
- public seed node
- regional VPS node
- hostile peer sending low-difficulty spam
- 2500 DATUM clients connected to one GridPool node
- 100 independent GridPool peers with bounded degree

Pass criteria should be tied to concrete launch targets from
`docs/stress-test-plan.md`.

## Model H: DoS And Low-Difficulty Spam

Question:

Can proof-of-work itself be used as an anti-DoS primitive without rejecting
honest miners during low-hashrate bootstrap conditions?

Strategies:

- spam invalid shares
- spam valid but too-low-difficulty shares
- spam duplicate valid shares
- repeatedly fetch state bundles
- peer identity churn
- reconnect storm

Mitigations to test:

- admission floor hints
- disconnect peers that ignore floor hints repeatedly
- cheap pre-validation before expensive validation
- per-peer and per-IP rate limits
- proof-of-work attached to non-share messages
- bounded state bundle fetches

Outputs:

- attack cost per accepted byte
- node CPU per rejected request
- false positive rate against honest weak miners
- recovery time after attack stops

## Model I: Coinbase Size Compatibility Variants

Question:

Can firmware with smaller coinbase limits participate without splitting into
many separate subpools or breaking incentives?

Candidate mechanisms:

- deterministic coverage variants
- coverage-weighted effective difficulty
- minimum coverage threshold for GridPool block validity
- deterministic subset selection from active snapshot
- smaller-team compatibility tiers

Adversarial tests:

- miner chooses small payout set to favor itself
- miner omits low-ranked recipients
- miner alternates between full and partial coverage based on private advantage
- miner griefs by finding blocks that underpay the team

This is not a launch blocker for the strict 300-slot beta, but it is a major
future adoption problem and deserves its own model.

## Repository Structure

Simulation work now lives in a dedicated repository:

```text
README.md
gridpool_sim/
scenarios/
sweeps/
reports/
  generated/
```

Python is probably the fastest path for research because of NumPy, pandas, and
plotting libraries. Critical invariants can later be ported into .NET property
tests for the reference implementation.

## First Three Deliverables

## Current Sweep Tooling

Sensitivity sweeps are now handled by:

- `run_sweep.py`
- `sweeps/pool_hopping_reserve_sweep.json`
- `sweeps/pool_hopping_focused_299_sweep.json`
- `sweeps/pool_hopping_external_mode_299_sweep.json`
- `sweeps/latency_peer_degree_sweep.json`
- `sweeps/majority_cartel_share_sweep.json`
- `run_variance_analysis.py`
- `scenarios/payout_variance.json`
- `analyze_pool_hopping_sweep.py`

The sweep runner applies a JSON parameter matrix to a base scenario and writes:

- `summary.json`
- `sweep_results.csv`
- `report.md`

Generated sweep outputs belong under `reports/generated/` and are
ignored by git. Promote only reviewed reports that support a public claim.

Economic strategy sweeps now emit both raw outcome rows and `paired_delta` rows
when the scenario enables `paired_strategy_seeds`. For pool-hopping claims,
paired deltas against the honest baseline should be treated as more informative
than comparing raw strategy means produced by unrelated random streams.

### Deliverable 1: Honest Baseline Notebook/Script

Goal:

Show that honest miners converge to expected payout share under V2 snapshot and
reserve rules.

Output:

- CSV
- plots
- markdown report
- deterministic seed

Current implementation:

- `run_simulation.py`
- `scenarios/honest_baseline.json`
- generated reports under `reports/generated/`

### Deliverable 2: Pool-Hopping Report

Goal:

Directly answer the strongest current critique: "Can I earn slots, leave, and
make other miners pay me?"

Output:

- strategy comparison table
- expected value table
- variance table
- sensitivity analysis over reserve depth and team hashrate
- plain-English conclusion with caveats

Current implementation:

- `run_simulation.py`
- `scenarios/pool_hopping.json`
- strategy variants for continuous mining, leaving while in snapshot, leaving
  after several slots, and leaving while any reserve proof remains
- `analyze_pool_hopping_sweep.py` for claim-oriented interpretation
  of completed sweep CSVs
- `external_payout_mode = deterministic_fpps` for an idealized FPPS-like outside
  option
- `external_payout_mode = solo` for stochastic solo outside mining

Next evidence pass:

```bash
nohup run_incentive_research_batch.sh \
  --jobs 4 \
  --heartbeat-seconds 60 \
  > reports/generated/incentive_research_batch.log 2>&1 &
```

This batch covers universal hopping, physical miner/team scale, Bitcoin fee
sensitivity, block-withholding fee sensitivity, and the discarded
clear-each-Bitcoin-block snapshot policy.

### Deliverable 3: Latency And Team-Split Report

Goal:

Quantify snapshot disagreement windows and the value of compact/UDP relay.

Output:

- divergence frequency
- divergence duration
- lost-work percentage
- bandwidth comparison by relay mode
- recommended peer degree and relay settings

Current implementation:

- `run_network_simulation.py`
- `scenarios/latency_splits.json`
- relay profile comparison for JSON/HTTP-style relay, compact WebSocket relay,
  and UDP-fast relay with fallback
- first-pass metrics for split rate, hashrate on canonical snapshot,
  convergence delay, and rough payload size

### Deliverable 4: Actual Payout Variance Report

Goal:

Show how GridPool changes real BTC payout variance over time for miners ranging
from micro lottery miners to industrial miners, compared with solo and FPPS.

Output:

- monthly BTC mean/std/CV by miner size
- zero-payout probability by miner size
- variance reduction versus solo
- payout-list-size sensitivity
- team-size sensitivity using team hashrate as a multiple of miner hashrate
- clear explanation that lower per-block slot inclusion on a larger team does
  not imply lower expected BTC over time

Current implementation:

- `run_variance_analysis.py`
- `scenarios/payout_variance.json`
- `variance_results.csv` and `report.md` outputs

## Definition Of Done For A Claim

A GridPool claim is ready for serious public use only when it has:

1. a precise statement
2. explicit assumptions
3. model source code
4. reproducible seed/config
5. generated report
6. caveats and known failure modes

Example:

Bad:

> GridPool is immune to pool hopping.

Better:

> Under the published Poisson mining model, with V2 snapshot rules, fixed reserve
> depth `3x`, and honest relay, the tested pool-hopping strategies did not show
> a meaningful positive absolute EV under realistic external-pool fees. A
> zero-fee deterministic FPPS outside option can create a small free-option
> effect because earned GridPool proofs remain payable while the miner earns
> elsewhere. They changed variance and liquidity exposure. See report X.

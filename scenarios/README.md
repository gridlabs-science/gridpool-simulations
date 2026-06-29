# Simulation Scenarios

## `honest_baseline.json`

First-pass Model A scenario.

Purpose:

- test whether V2 snapshot/reserve mechanics pay honest miners roughly in
  proportion to hashrate over time
- include slot-0 rewards and snapshot proof payouts
- provide a deterministic baseline before adversarial variants

## `pool_hopping.json`

First-pass Model B scenario.

Purpose:

- compare continuous GridPool mining with simple pool-hopping strategies
- credit inactive hashrate with a configurable outside option
- test whether leaving after earning slots creates obvious excess expected value

Current strategy variants:

- honest continuous mining
- leave while the target miner has any active snapshot slot
- leave for several Bitcoin blocks after earning several active snapshot slots
- leave while the target miner has any proof in the unpaid reserve

These are not the final word on pool hopping. They are executable starting
points for tightening the question.

This scenario uses paired strategy seeds. The strongest evidence should come
from paired deltas against `honest_all_miners`, especially in long focused
sweeps, rather than from comparing unrelated Monte Carlo averages.

Outside mining modes:

- `deterministic_fpps` models an idealized outside pool that pays expected value
  every Bitcoin block, minus `external_fee_rate`.
- `solo` models the same outside expected value but with block-level solo
  variance.

The deterministic mode is deliberately generous to the hopper. If hopping does
not produce compelling positive absolute EV there, it is unlikely to become
more attractive after realistic external-pool fees and operational risks.

## `block_withholding.json`

First-pass Model D scenario.

Purpose:

- compare honest mining with a miner that withholds valid Bitcoin blocks while
  still submitting non-block GridPool shares
- quantify forfeited slot-0 and fee upside
- make the block-withholding-resistance claim testable instead of rhetorical

Current strategy variants:

- honest continuous mining
- target miner withholds every valid Bitcoin block it finds
- target miner withholds only while it is underrepresented in the active
  snapshot

This first pass does not model detection, reputation, or long-term miner
response. It only asks whether withholding looks profitable under the direct
GridPool payout mechanics.

This scenario also uses paired strategy seeds so withholding strategies can be
compared against an honest baseline under common replication seeds.

## `majority_censorship.json`

First-pass Model C scenario.

Purpose:

- model a large cartel miner that refuses to count some or all non-cartel proofs
- distinguish value theft from team splitting
- expose the unsafe case where a naive miner keeps mining a team that rejects
  their valid proofs

Current strategy variants:

- honest single team
- cartel mines a private cartel-only team while everyone else mines the
  inclusive team
- cartel censors only the target while other non-target miners follow the cartel
  team
- naive target keeps mining the censoring team even though its proofs are not
  counted

Current limitations:

- two-team abstraction only
- no peer graph or relay-latency behavior
- no dynamic heaviest-state adoption
- no miner UI response or automatic team-switching logic

This scenario is designed to answer a narrow question first: can a cartel steal
value by rejecting valid proofs, or does it mostly create a separate team and
increase variance/coordination risk?

## `latency_splits.json`

First-pass Model E scenario.

Purpose:

- estimate how often nodes build different active snapshots at Bitcoin-block
  notification time
- compare JSON/HTTP-style relay, compact WebSocket relay, and UDP-fast relay
  assumptions
- quantify convergence delay, canonical-snapshot participation, and rough
  payload differences

Current limitations:

- no intentional censorship or private-state adversary
- no packet-level network emulation
- no active heaviest-state adoption after split detection
- no payment-transition race modeling yet

This is a useful first lens on whether compact/UDP share relay materially
reduces snapshot-split windows.

## `payout_variance.json`

Analytic payout-variance benchmark.

Purpose:

- compare GridPool against pure solo and idealized FPPS using actual BTC payouts
  over a fixed period
- separate snapshot inclusion from miner utility
- quantify how payout-list size changes variance for miners from Bitaxe scale
  through EH scale
- test the effect of larger or smaller teams by varying team hashrate as a
  multiple of the miner's hashrate

Current assumptions:

- pure solo block discovery is a Poisson process
- FPPS is deterministic expected value at the configured fee rate
- GridPool team blocks are Poisson; each paid block assigns shared slots to the
  miner approximately as `Binomial(K, p)`, where `K` is shared slot count and
  `p` is miner share of team hashrate
- slot 0 receives the residual slot plus transaction fees

Important interpretation:

If a miner's hashrate is fixed and the team gets larger, that miner appears in
fewer slots per team block, but team blocks happen more often. Expected BTC over
time is unchanged. Variance changes because payouts are less or more clumped.

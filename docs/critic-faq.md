# GridPool Critic FAQ

Status: draft.

Audience: Bitcoin miners, pool operators, protocol developers, and reviewers who
already understand mining pools, P2Pool-style sharechains, DATUM, and block
template construction.

This document answers recurring technical objections. It is intentionally more
careful than promotional language. Some claims are implemented properties of the
current reference node; others are hypotheses that need modeling, simulation, and
large-scale testing.

## Short Version

GridPool is not a PPLNS server, not FPPS, and not a sharechain. It is a
coinbase-payout coordination protocol.

Miners build Bitcoin block templates that pay:

1. slot 0 to the block finder
2. optional canonical support slot
3. the active GridPool payout snapshot

Miners submit high-difficulty share proofs into a bounded unpaid Work Set. Every
Bitcoin block snapshots the current highest-ranked unpaid proofs into the active
payout template. A GridPool block pays that active snapshot directly from the
coinbase, and only the paid proof IDs are removed from the unpaid reserve.

The core bet is that reward sharing can be coordinated through verified
proof-of-work and coinbase commitments without a pool wallet, central share
ledger, or separate sharechain.

## Is GridPool Vulnerable To Pool Hopping?

The short answer is: the tested pool-hopping strategies do not look like a
catastrophic expected-value exploit, but the honest answer is nuanced.

Classic pool hopping exploits predictable changes in expected value during a
round. In some pool designs, a miner can join when shares are temporarily
overvalued and leave when they are undervalued.

GridPool is different:

- A miner is not paid for submitting lots of low-difficulty shares to a central
  account.
- A miner earns only if its verified high-difficulty proofs enter a payout
  snapshot and that snapshot is later paid by a real GridPool block.
- The unpaid Work Set is bounded and competitive. Old proofs decay naturally as
  stronger unpaid proofs displace them.
- Leaving after earning a strong proof does not create free expected value. It
  turns already-performed work into a lottery ticket, while forfeiting future
  proof opportunities and slot-0 block-finder upside.

A miner who gets lucky, earns several payout slots, and leaves is still only
holding claims produced by real previous work. If they keep mining GridPool,
they also have a chance to find the block that pays those unusually favorable
slots, collecting slot 0 plus transaction fees. If they leave for a different
pool, they give up that upside.

That said, "not a catastrophic exploit" is not the same as "impossible to gain
anything by leaving." The right way to settle this is to model explicit
strategies:

- always mine GridPool
- leave after earning one or more snapshot slots
- leave after a large outlier share
- join only during high-fee periods
- split hashrate between GridPool and another pool
- alternate between GridPool and low-variance FPPS/PPLNS

The required result is not that no rational miner ever leaves. Miners may leave
for lower variance, lower operational risk, better UX, or a different fee model.
The required result is that leaving after a lucky GridPool proof does not create
a meaningful systematic expected-value advantage over honest continuous mining.

Current modeling status:

- The first focused 299-slot long sweep tested a `15%` miner that leaves after
  earning snapshot/reserve position.
- Against an unlucky always-on GridPool seed path, hopping showed positive
  paired deltas. That is useful as a diagnostic, but it is not the clean public
  EV number.
- Against theoretical gross network-hashrate EV, hopping was roughly fair to
  mildly positive with a zero-fee deterministic FPPS-like outside option.
- At `0.5%` external fee, the hopper was slightly negative in the tested runs.
- At `2%` external fee, the strategy was clearly unattractive.

Interpretation: a zero-fee deterministic outside option can create a small
free-option effect because old GridPool proofs remain payable while the miner
temporarily earns elsewhere. That is not share forgery or value theft. It is a
variance/liquidity tradeoff, and realistic outside-pool fees appear to erase it
in the current model.

## Does A Departed Large Miner Hurt The Remaining Miners?

It can increase variance, but it should not steal value.

If a large miner contributes real work, earns many proof slots, then leaves, the
remaining miners may temporarily mine a payout snapshot that includes that
miner's previous work. This is not a bug by itself. It is the accounting rule:
snapshots pay recent strong unpaid proofs.

The important questions are:

- Were the departed miner's slots earned by valid proof-of-work?
- Are those proofs eventually displaced if the miner stops contributing?
- Does the strategy increase the departed miner's expected value at honest
  miners' expense?

The first two are direct protocol properties. The third is a modeling question.
Current simulations support the narrower claim that departed miners are paid
only for real work already contributed, and their old proofs are naturally
displaced as stronger unpaid work arrives. The remaining concern is whether
temporary departure can improve variance/liquidity enough to be strategically
attractive for some miners under specific outside-pool assumptions.

## Is GridPool Just "Loose Consensus"?

GridPool deliberately avoids a long-lived sharechain, but it still has consensus
rules.

Consensus-critical facts are not accepted by identity or reputation. A node
validates:

- block header proof-of-work
- Merkle root commitment
- coinbase output structure
- slot-0 attribution
- parent block context
- payout snapshot context
- duplicate proof status
- proof difficulty and ranking

When nodes disagree, they can exchange the proof bundle behind the competing
state. A heavier valid Work Set or payout snapshot is not just an opinion. It is
a set of independently verifiable proofs.

This is closer to "heaviest valid payout state" than to Nakamoto consensus over
a separate chain. That is a simpler object, but it also means GridPool must
measure convergence behavior carefully. The key open engineering question is
not whether nodes can verify a candidate state. They can. The key question is
how fast the peer network converges under latency, churn, and adversarial relay.

## Why Not Use A Sharechain Like P2Pool?

A sharechain solves decentralized accounting by creating a second blockchain
with much faster block times. That gives a clear chain-selection rule, but it
also introduces sharechain-specific problems:

- extra node complexity
- extra storage and synchronization
- stale sharechain blocks
- propagation-latency incentives
- sharechain reorg and private-mining strategy space
- a separate object that may be vulnerable to majority hash attacks

GridPool avoids the secondary chain entirely. It keeps only bounded current
state: the unpaid Work Set, active payout snapshot, recent paid snapshot
lineage, and enough retained context to validate unpaid proofs.

The tradeoff is that GridPool must prove that bounded-state gossip converges
well enough in practice. It replaces sharechain-finality analysis with
network-convergence and mechanism-design analysis.

## Is GridPool Vulnerable To A 51 Percent Sharechain Attack?

Not in the same way, because GridPool has no sharechain.

There is no separate chain for an attacker to privately mine, reorg, or majority
attack as a ledger. A majority miner can still do things that matter:

- dominate the unpaid Work Set honestly with real proof-of-work
- choose not to relay other miners' proofs
- mine on a private payout snapshot
- try to convince peers to follow its preferred payout state

Those are team-split and censorship-cartel problems, not sharechain reorg
problems. The intended defense is economic: nodes should follow the strongest
valid payout state they can verify, because that is the team most likely to find
blocks and reduce variance.

This needs adversarial modeling. In particular, the model should test whether a
large miner with more than 51 percent, 75 percent, or 95 percent of GridPool
hashrate can profit by censoring smaller miners' proofs, and how quickly
honest relay paths restore a stronger inclusive state.

## What If A Huge Miner Rejects Everyone Else's Shares?

If a huge miner refuses to include or relay other miners' valid proofs, it is
effectively choosing to form a smaller team around itself.

That does not let it forge the censored miners' proof-of-work or steal their
slot-0 attribution. It may, however, create a competing payout state. Other
nodes then face a coordination question: mine with the inclusive team, or mine
with the high-hashrate censoring team.

GridPool's working hypothesis is that miners should prefer the strongest valid
team that does not exclude their own proofs, and that open relay paths make
selective censorship economically unstable. But this is one of the highest-value
simulation targets. We should not hand-wave it.

## Is Transaction Censorship Detectable From GridPool Shares?

Usually no, not from the share message alone.

A GridPool share proof must reveal enough information to prove:

- the coinbase transaction
- the Merkle path from the coinbase to the block header Merkle root
- the block header hash

It does not reveal the full transaction set. A peer can verify that the coinbase
commits to the advertised payout template, but it cannot infer arbitrary
included or excluded transactions from the Merkle root alone.

If the miner finds a real Bitcoin block, the block's transaction set becomes
public like any other Bitcoin block. Before that, GridPool share relay is mostly
blind to transaction selection.

This is a censorship-resistance advantage, but not a magic shield. A miner can
still choose censored templates locally. A network adversary can still attack
connectivity. A miner who reveals more transaction data through some side
channel can still leak policy choices.

## Can Sybil Nodes Get More Payout Weight?

No, not directly.

Payout weight is earned by proof-of-work difficulty, not by accounts, IP
addresses, peer identities, or server count. A miner can split hashrate across
many identities, but the total expected proof production is still governed by
total hashrate.

Sybil nodes can still matter for networking:

- peer table pollution
- eclipse attempts
- relay delay
- bandwidth abuse
- fake node-health impressions

So Sybil resistance at the accounting layer does not remove the need for robust
peer selection, bounded peer degree, address hygiene, and anti-DoS rules.

## What About Duplicate Shares?

Duplicate proofs must not create duplicate payout weight.

The reference implementation treats share identity and proof validation as
consensus-critical. Replaying the same valid proof through multiple paths should
not add multiple Work Set entries. This is covered by regression tests, and it
should be part of every compatibility test suite for future implementations.

## Does GridPool Require 300 Coinbase Outputs?

The current main beta uses a 300-slot conceptual payout template:

- slot 0: block finder
- optional canonical Grid Labs support slot
- up to 298 or 299 shared proof slots, depending on support slot setting

That requires miner firmware and Stratum infrastructure capable of handling
large coinbase transactions. Some older firmware cannot.

For the current beta, shortened payout lists are consensus-invalid. Future
protocol versions may add deterministic smaller-coinbase compatibility tiers or
coverage-weighted payout variants, but that is not part of current consensus.

## What Evidence Would Make GridPool More Convincing?

The strongest evidence would be:

1. open-source pool-hopping expected-value simulations
2. adversarial simulations for majority miners, censorship, and private state
3. latency simulations with realistic peer graphs and propagation delays
4. measured bandwidth and convergence data from many nodes
5. stress tests with thousands of DATUM or DATUM-like clients
6. reproducible reports comparing GridPool with solo mining, centralized pools,
   and sharechain-style systems

GridPool's claims should become progressively more mathematical and empirical.
The right standard is not "sounds plausible." The right standard is "here is the
model, here are the assumptions, here is the code, here are the results, and
here is where the design still fails or needs work."

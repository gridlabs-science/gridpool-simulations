# GridPool V2.1 Consensus Note

Status: working technical note for the July 17, 2026 developer meeting.

## Short Version

V2.1 moves GridPool away from "heaviest stale branch wins" as the normal split-resolution model.

The rule is:

> Merge valid compatible work forward. Do not retroactively rewrite a locally observed Bitcoin-block payout snapshot with late previous-parent work.

This is the key update missing from older modeling drafts.

## Why The Earlier Model Was Too Pessimistic

Earlier adversarial-split models treated two diverged states as mutually exclusive branches. A node had to choose one list and discard the other. Under that framing, a majority miner might try to build a private favorable branch, reveal it later, and claim the rest of the network should follow it because it has more accumulated work.

That model is useful as a warning, but it is not the V2.1 launch rule.

In V2.1, many disagreements are not branch conflicts:

- If proofs are valid against compatible current-parent snapshot contexts, they merge into the unpaid Work Set.
- If proofs are duplicates, they are ignored.
- If proofs are invalid, they are rejected.
- If proofs are late previous-parent proofs trying to rewrite an already-observed Bitcoin-block boundary, they are rejected or quarantined from canonical state.

So most honest data divergence becomes synchronization, not consensus selection.

## Boundary Finality

Every Bitcoin block creates a payout snapshot from the local node's valid unpaid Work Set. Once a node has observed that Bitcoin block and created the active snapshot, a peer cannot later force a rewrite by saying, "I saw one more previous-parent proof before the boundary."

That peer may be honest. It may have genuinely seen the proof first. But allowing retroactive snapshot replacement creates the opening for intentional stale-branch attacks.

V2.1 accepts the smaller cost:

- occasional last-millisecond previous-parent work may miss the just-created snapshot;
- that is preferable to allowing stale branches to rewrite payout history;
- current-parent work after the boundary can still merge forward into later snapshots.

## Attack Reframing

### Old concern

An attacker with high GridPool hashrate privately mines a favorable stale branch, reveals it later, and wins because its branch is heavier.

### V2.1 answer

The attacker cannot use late stale-parent proofs to rewrite snapshots that honest nodes already finalized. The attacker's stale work is not a candidate for retroactive replacement.

The attacker can still:

- mine honestly and compete for reserve slots;
- censor shares it sees locally;
- isolate itself into a separate team;
- attempt network-level partitioning or denial of service.

Those are real risks, but they are not the same as retroactively stealing or rewriting proof claims.

## Latency Reframing

V2.1 does not make latency irrelevant.

Fast relay still matters because shares seen before a Bitcoin-block boundary have a better chance of entering the active snapshot. The difference from P2Pool is that GridPool does not create a continuous winner-take-all sharechain race. A late proof is usually either:

- valid current-parent work that can merge forward; or
- stale previous-parent work that missed the boundary and cannot rewrite it.

This makes latency a bounded inclusion risk, not the main engine of ongoing payout centralization.

## What The Old Scoring Simulations Still Mean

The consensus-selection simulations remain useful, but their role changes.

They show:

- raw summed proof difficulty is a weak estimator under heavy-tailed share difficulty;
- the lowest retained proof in a full reserve is a better estimator of total observed work;
- low-difficulty reserve-fill attacks are real if scoring admits arbitrary floor proofs;
- retroactive branch-selection rules are dangerous.

They no longer imply that launch requires a perfect global "which branch wins" scoring rule for every same-boundary divergence.

V2.1 mostly avoids that question by merging compatible proofs and rejecting stale boundary rewrites.

## What Still Needs Testing

Before packaging V2.1 for broader Umbrel/Start9-style deployment, the runtime implementation should have explicit tests for:

- previous-parent proof arriving after local Bitcoin-block observation does not rewrite active snapshot;
- valid current-parent proof from a peer's retained snapshot context can merge forward;
- two nodes with the same active snapshot but different Work Sets converge by merging proofs;
- paid proof IDs are removed exactly once after a GridPool block;
- non-paid reserve proofs survive payment and remain eligible;
- state bundles cannot smuggle stale proofs into canonical state by presenting them as a heavier branch.

## Suggested One-Sentence Claim

> V2.1 makes GridPool split recovery a proof-merge problem wherever possible, and treats late stale-parent work as ineligible for retroactive snapshot rewrites.

# V2.1 Selective-Inclusion And Merge-Forward Model

Status: model design, July 2026.

## Research Question

Does V2.1 merge-forward let a miner exclude other miners from its own payout
snapshot while still earning shared slots in the inclusive team's snapshots?

This is distinct from delayed stale-parent takeover:

- A stale-parent attacker mines after a Bitcoin boundary on obsolete work. It
  forfeits the chance to win a valid block during that window.
- A selective-inclusion attacker can omit honest proofs from its local Work Set,
  snapshot that private view at an ordinary Bitcoin boundary, and continue
  mining the current Bitcoin parent. It does not necessarily pay a stale-work
  cost.

The second strategy must therefore be tested independently. Assuming every
divergent context required stale mining would assume away the strongest case.

## Strategies

### Honest baseline

All proofs are relayed and included. Every miner builds on the same active
snapshot. This is paired with every attack run using the same proof luck and
block-finder schedule.

### Free ride

The attacker:

- excludes honest proofs from its private Work Set;
- relays its own current-parent proofs to honest nodes;
- mines the current Bitcoin parent against its private payout snapshot;
- receives shared payouts when honest miners find blocks if merge-forward
  credits its cross-context proofs;
- pays primarily itself when it finds a block on its private snapshot.

This is the central reciprocity test.

### Private split

The attacker excludes honest proofs and withholds its own proofs. This creates a
separate subteam. It is a control case: absent cross-credit, expected value
should remain approximately proportional to hashrate while payout variance and
branch behavior change.

### Stale-parent takeover

Keep this in `run_delayed_snapshot_attack.py`. It measures a different attack:
the attacker mines the previous Bitcoin parent and attempts retroactive branch
replacement. Its takeover reward is now a counterfactual upper bound because
V2.1 established-node local finality rejects that replacement.

## Merge Policies

### `merge_all_current_parent`

Deliberately permissive counterfactual. A valid proof on the current Bitcoin
parent enters the canonical unpaid reserve even when it was built on a
genuinely different active payout snapshot. The tested V2.1 candidate-import
path does **not** allow this transition: candidate IDs are anchored to the
active state.

### `canonical_context_only`

Runtime-boundary approximation. A proof is credited only while its active
payout snapshot matches the local active snapshot. This enforces reciprocal
template compatibility but does not by itself solve recovery from an honest
active-snapshot split.

Future models can add bounded-overlap or context-scoped quarantine policies
between these extremes.

## State Model

Each replication maintains:

- an inclusive honest Work Set and active snapshot;
- an attacker Work Set and active snapshot;
- a fixed 897-proof reserve and 299-proof payout snapshot by default;
- proof owner, achieved difficulty, proof ID, and payout context;
- paid-once removal when a GridPool block pays a snapshot.

Proof difficulty follows the expected Pareto tail for achieved mining
difficulty. Bitcoin boundaries occur once per interval. GridPool block events
occur with probability equal to GridPool's configured share of Bitcoin
hashrate, and the finder is sampled by attacker share.

When a block is paid:

- the finder's active snapshot determines shared outputs;
- slot 0 receives the subsidy remainder plus transaction fees;
- paid proof IDs are removed from both views where present;
- the block proof is retained according to the modeled strategy.

## Primary Metrics

- attacker BTC delta against its paired honest baseline;
- honest BTC delta against the same baseline;
- attacker reward share minus attacker hashrate share;
- attacker slots retained on the inclusive snapshot;
- attacker slots retained on its private snapshot;
- cross-context proofs credited or rejected;
- fraction of boundaries with divergent active snapshots;
- fraction where the private reserve floor exceeds the inclusive floor;
- payout conservation error.

Positive attacker delta paired with equal honest loss indicates transfer rather
than value creation. A persistent positive edge under
`merge_all_current_parent` means future recovery rules must not treat
current-parent validity alone as sufficient for cross-active-state credit.

The runtime regression
`CandidateImportRejectsCurrentParentProofFromDifferentActiveSnapshotAsync`
constructs the modeled exclusionary active state and confirms that candidate
import rejects it. The simulation is therefore a counterfactual design test,
not evidence that the current candidate-import path is exploitable.

## The 51 Percent Question

V2.1 established nodes do not replace an already-active snapshot merely because
a private branch has a stronger reserve score. The model records private-floor
wins as a diagnostic but keeps established-node forced switches at zero.

This directly contrasts V2.1 with the obsolete heaviest-branch rule:

- a majority miner may create and sustain a private team;
- it may dominate proof production;
- it cannot make an established honest node retroactively rewrite its local
  active snapshot through reserve strength alone.

Bootstrap behavior and newly joining nodes remain a separate question and
should be modeled after the established-node economics are understood.

## Interpretation Gates

1. If free riding has no positive expected-value edge, merge-forward is likely
   an availability tradeoff rather than an economic transfer.
2. If free riding gains BTC from honest miners, V2.1 needs a reciprocity or
   context-eligibility rule before strong incentive-compatibility claims.
3. If only private splitting is viable, the attacker has formed a smaller team
   rather than stolen work; compare variance and operational costs.
4. If a mitigation removes the edge but destroys honest split recovery, it is
   not automatically acceptable. It must be combined with the latency model.

## Limitations

- The first pass uses instantaneous propagation and deliberately excludes
  accidental boundary races.
- It models two collective views rather than every peer independently.
- It does not model sybil identities, new-node bootstrap selection, or operator
  retaliation.
- It treats all participants within the honest side as one economic class.
- It is an exploratory mechanism model, not proof that a production exploit is
  reachable through every current network path.
- It conservatively removes proof IDs paid by either branch from both modeled
  reserves. If a real node failed to recognize a divergent-context GridPool
  payment, repeated-credit behavior could be worse and requires an integration
  test.

The next pass should combine any observed economic edge with
`run_v21_disagreement_persistence.py` and real relay latency profiles.
Before changing consensus, add a runtime adversarial test that constructs a
proof-backed selective snapshot, relays current-parent proofs from it, and
confirms whether the reference implementation actually imports those proofs.

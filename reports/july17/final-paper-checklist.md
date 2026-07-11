# July 17 Final Paper Checklist

Status: working checklist for finishing the GridPool V2.1 paper before July 17.

Goal: make the paper independently checkable, falsifiable, connected to live evidence, and clearly grounded in V2.1 rather than older branch-selection framing.

## Highest-Leverage Additions

### 1. V2.1 State-Transition Diagram

Status: done in `reports/july17/gridpool-july17-handout.md` with `charts/v21_state_transition.svg`.

Purpose: make the protocol mechanics click faster than prose.

Show:

```text
Unpaid Work Set
  -> Bitcoin block observed
  -> Active Snapshot created
  -> GridPool block pays active snapshot
  -> paid proof IDs removed
  -> unpaid reserve proofs carry forward
```

Acceptance criteria:

- Diagram distinguishes `Unpaid Work Set`, `Active Snapshot`, `Snapshot Context`, and `Paid Lineage`.
- Diagram shows that snapshot creation does not clear the reserve.
- Diagram shows paid-once removal after a real GridPool block.
- Figure caption states this is V2.1 snapshot/reserve behavior.

### 2. Concrete Split/Merge Toy Example

Status: done in `reports/july17/gridpool-july17-handout.md` with `charts/v21_split_merge_example.svg`.

Purpose: answer the strongest critique directly: why no "heaviest stale branch" vote is needed for ordinary divergence.

Include a two-node example:

- Node A and Node B share the same active snapshot.
- A sees proof `p1`; B sees proof `p2`.
- A Bitcoin block boundary occurs.
- A late previous-parent proof `p_stale` arrives after the boundary.
- Compatible current-parent proofs merge forward.
- `p_stale` is rejected or quarantined from canonical state and does not rewrite the active snapshot.

Acceptance criteria:

- Explicitly labels which proofs merge, which proof is stale, and which snapshot is paid.
- Shows that valid current-parent divergence is synchronization, not branch selection.
- Shows why "heaviest stale branch wins" is not the V2.1 launch rule.

### 3. One-Page Claims Table

Status: done in `reports/july17/gridpool-july17-handout.md`.

Purpose: make the paper rigorous and prevent overclaiming.

Columns:

- `Claim`
- `Mechanism`
- `Evidence`
- `Caveat`

Minimum rows:

- 300-slot payout lists reduce actual BTC variance.
- Pool hopping cannot steal value or create fake work.
- Zero-fee outside options can create a small free-option effect.
- Block withholding is economically unattractive for profit-seeking miners.
- Compact relay reduces modeled snapshot-boundary disagreement.
- V2.1 prevents late stale-parent proofs from retroactively rewriting snapshots.
- Latency remains a bounded inclusion risk, not a continuous sharechain orphan race.

Acceptance criteria:

- Every claim has an evidence source.
- Every claim has a caveat.
- No row implies immunity to all majority, partition, censorship, or griefing attacks.

### 4. Threat Model Summary

Status: done in `reports/july17/gridpool-july17-handout.md`.

Purpose: centralize the caveats instead of scattering them through prose.

Columns:

- `Threat`
- `V2.1 Mechanism`
- `Current Evidence`
- `Still Open`

Minimum rows:

- pool hopping;
- block withholding;
- stale branch rewrite;
- majority miner censorship;
- network partition;
- latency disadvantage;
- state-bundle spam;
- external-motive griefing.

Acceptance criteria:

- Clearly separates protocol-mechanism protections from operational/network risks.
- States that V2.1 removes the stale-branch rewrite primitive, not every possible attack.

### 5. Regression Test Summary

Status: done by companion agent and incorporated in `reports/july17/gridpool-july17-handout.md`. Runtime verification reported: `dotnet test boot.tests/boot.tests.csproj` passed with 92 tests.

Purpose: make the project look engineered, not just theorized.

Add a table of consensus invariants and test status:

- paid-once lineage;
- merge compatible current-parent work;
- reject or quarantine late previous-parent rewrite;
- preserve unpaid reserve across snapshots;
- remove paid proof IDs exactly once;
- support-fee on/off payout validation;
- state bundle sync cannot smuggle stale proofs into canonical state.

Columns:

- `Invariant`
- `Why It Matters`
- `Test Status`
- `Source / Next Step`

Acceptance criteria:

- If tests exist, cite files or test names.
- If tests are missing, state them as near-term work without hiding the gap.
- Ideally add or link at least the highest-value V2.1 boundary-finality tests in `boot-protocol`.

### 6. Live Network Appendix

Status: partial in `reports/july17/gridpool-july17-handout.md` as `Public Network Summary`; Detroit node and clean telemetry window still pending.

Purpose: connect the paper to running public infrastructure without overstating field evidence.

Include:

- public nodes observed;
- synced state status;
- current/candidate state agreement;
- observed peers;
- relay/session health;
- UDP/WebSocket/HTTP observation counts if available;
- peer relay latency telemetry if available;
- snapshot-boundary disagreement count if available.

Required label:

> Field sanity check, not statistical proof.

Acceptance criteria:

- Do not claim UDP is proven in production.
- Include run window and node versions if available.
- State any data quality issues: unsynced nodes, missing UDP observations, restarts, stale peers.

### 7. Economic Intuition Box

Status: done in `reports/july17/gridpool-july17-handout.md`.

Purpose: explain why GridPool's incentives differ from centralized pools and P2Pool in plain language.

Cover:

- slot 0 plus transaction fees reward block publication;
- shared slots reward contributed high-difficulty proofs;
- there is no trusted operator ledger;
- paid proof IDs are removed once paid;
- unpaid reserve proofs carry forward;
- there is no continuous sharechain race.

Acceptance criteria:

- One page or less.
- Plain-language prose suitable for a technical funder who is not deep in pool mechanics.

### 8. Reproducibility Appendix

Status: done in `reports/july17/gridpool-july17-handout.md`, including the V2.1 boundary-inclusion model command and long-run output paths.

Purpose: make the claims independently checkable and falsifiable.

Include:

- repository path;
- commit hash or local dirty-state note;
- exact commands for:
  - payout variance;
  - pool hopping;
  - block withholding;
  - latency peer-degree sweep;
  - consensus scoring audit;
  - V2.1 split-recovery simulation if completed;
- generated report paths;
- chart packet path.

Acceptance criteria:

- Commands should be copy-paste runnable from repo root.
- Long-running commands should include expected output directory.
- Generated reports used in the paper should be listed explicitly.

### 9. Funding / Resource Roadmap

Status: done in `reports/july17/gridpool-july17-handout.md`.

Purpose: show what additional resources unlock.

Keep it technical:

- larger Monte Carlo sweeps and confidence intervals;
- multi-region public-node testnet;
- automated adversarial state-bundle regression suite;
- independent mining-template validation;
- compact/UDP relay hardening;
- Umbrel/Start9 packaging;
- public dashboards for relay and snapshot telemetry;
- third-party review/audit budget.

Acceptance criteria:

- Tie each resource request to risk reduction or delivery acceleration.
- Avoid generic fundraising language.

## Optional Model To Add If Completed

### V2.1 Split-Recovery / Boundary-Inclusion Simulation

Status: done and incorporated in `reports/july17/gridpool-july17-handout.md` with long-run outputs from `reports/generated/v21_latency_recovery_july17_long/`.

Purpose: directly support the updated V2.1 claim:

> Latency is a bounded snapshot-inclusion risk, not P2Pool-style continuous orphan pressure.

Model shape:

- nodes receive shares with random propagation delays;
- Bitcoin block creates a snapshot boundary;
- previous-parent late shares are rejected or quarantined;
- current-parent divergent Work Sets merge;
- measure honest work lost at boundaries by relay latency profile.

Suggested metrics:

- percent of honest previous-parent work missing the active snapshot;
- percent of valid current-parent work recovered by merge-forward;
- snapshot-boundary disagreement rate;
- late stale-parent rejection/quarantine count;
- sensitivity by JSON/HTTP, compact WebSocket, and UDP-fast relay profiles.

Acceptance criteria:

- Present as V2.1-specific evidence, not old branch-choice scoring.
- Include model assumptions near the chart.
- Avoid implying that latency is irrelevant.

## Lower Priority / Do Not Spend Time Before July 17

- More broad 51% modeling.
- New V3 branch-market modeling.
- Additional philosophical adversary taxonomy unless it improves the threat-model table.
- New charts that do not map to a specific paper claim.

Rationale:

The stronger framing is that V2.1 removes the stale-branch rewrite primitive. Remaining attacks are network partitions, censorship, or griefing, and those belong in the operational/networking roadmap rather than reopening unresolved branch-choice debates.

## Suggested Execution Order

1. Add V2.1 state-transition diagram.
2. Add concrete split/merge toy example.
3. Add claims table and threat model table.
4. Add regression test summary from `boot-protocol`.
5. Add live network appendix if data quality is acceptable.
6. Add economic intuition box.
7. Add reproducibility appendix.
8. Add funding/resource roadmap.
9. Incorporate V2.1 split-recovery simulation if the run completes in time.
10. Rebuild the PDF and do a print review.

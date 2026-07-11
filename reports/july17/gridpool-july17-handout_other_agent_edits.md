---
      2 -title: "GridPool V2.1 Modeling Findings"
      3 -subtitle: "Developer meeting handout - July 17, 2026"
      4 -author: "GridPool research packet"
      5 -date: "2026-07-17"
      6 -lang: en-US
      7 -toc: true
      8 -numbersections: true
      9 -geometry:
     10 -  - margin=0.75in
     11 -fontsize: 10pt
     12 ----
     13 -
     14 -# Executive Summary
     15 -
     16 -GridPool replaces trusted pool accounting with independently verifiable proof-of-work claims against explicit payout snapshots. The current evidence supports three core claims:
     17 -
     18 -- broad payout lists materially reduce actual BTC payout variance;
     19 -- pool hopping cannot create fake work or steal another miner's earned proof claims;
     20 -- straightforward profit-seeking block withholding is expensive because the finder gives up slot 0, fees, and the acceleration of its own shared claims.
     21 -
     22 -The most important recent protocol update is V2.1. Earlier modeling treated split resolution as a branch-selection problem: if two nodes disagreed, which list was "heavier"? That fr
         aming exposed real concerns around adversarial stale branches and majority-hashrate split attacks.
     23 -
     24 -V2.1 changes the problem. The normal rule is now:
     25 -
     26 -> Merge valid work forward. Do not retroactively rewrite a locally observed Bitcoin-block payout snapshot with late previous-parent work.
     27 -
     28 -That means most honest divergence is handled by merging proof sets, not choosing one branch and discarding the other. The stale-branch attack path is blocked at the boundary rule: p
         revious-parent proofs that arrive after a node has observed the next Bitcoin block are rejected or quarantined from the canonical reserve. This does not prove that GridPool is immun
         e to every network partition or griefing attack, but it significantly improves the launch posture compared with the older "heaviest list wins" framing.
     29 -
     30 -# Evidence Status
     31 -
     32 -| Topic | Current evidence | Meeting posture |
     33 -| --- | --- | --- |
     34 -| V2.1 split handling | Protocol analysis plus implementation direction: merge compatible Work Sets; finalize local snapshot boundaries. | Stronger than old branch-choice model; nee
         ds multi-node soak and regression tests. |
     35 -| Payout variance | Reproducible variance sweep using actual BTC paid, not just slot inclusion. | Strong model-backed claim. |
     36 -| Pool hopping | Economic sweeps plus explicit proof-claim mechanics. | Strong mechanical claim; small/caveated economic effect under idealized zero-fee outside options. |
     37 -| Block withholding | Fee-sensitivity sweep across honest, withhold-all, and selective withholding. | Strong model-backed evidence against straightforward profit-seeking withholding
         . |
     38 -| Relay latency | Network latency model and generated charts. | Useful model evidence; live field telemetry still needed. |
     39 -| Old consensus scoring | Honest/adversarial scoring audit and delayed-snapshot attack model. | Historical rationale for V2.1; no longer the primary launch rule. |
     40 -
     41 -# What V2.1 Changes
     42 -
     43 -## Definitions
     44 -
     45 -The V2.1 protocol uses four separate state concepts:
     46 -
     47 -| Term | Meaning |
     48 -| --- | --- |
     49 -| Unpaid Work Set | The bounded reserve of valid, unpaid share proofs. Default depth is `3x` the shared payout list, so `897` proofs for the current 300-slot team. |
     50 -| Active Snapshot | The payout template locked at a Bitcoin block boundary. This is the post-slot-0 list that miners build into candidate blocks. |
     51 -| Snapshot Context | The payout template a proof was mined against. Nodes retain contexts so old unpaid proofs can still be verified after later snapshots. |
     52 -| Paid Lineage | The proof IDs paid by a real GridPool block. Paid proof IDs are removed once paid; other reserve proofs remain eligible. |
     53 -
     54 -## Rules
     55 -
     56 -V2.1 can be summarized as:
     57 -
     58 -1. Every new Bitcoin block snapshots the current unpaid Work Set into the active payout template.
     59 -2. Snapshot creation does not clear the unpaid Work Set.
     60 -3. A real GridPool block pays the active snapshot.
     61 -4. After payment, remove only the proof IDs that were actually paid.
     62 -5. If two peers have compatible valid Work Set proofs, merge them and keep the best bounded reserve.
     63 -6. If a proof arrives too late for the previous Bitcoin parent, do not use it to rewrite the already-active snapshot.
     64 -7. A peer's "heavier" stale branch is not enough to retroactively replace a snapshot the local node already finalized.
     65 -
     66 -The important distinction is merge versus replace. Honest nodes do not need to pick one whole Work Set and throw the other away when both contain valid current-parent work. They mer
         ge valid proofs.
     67 -
     68 -# How This Reframes Earlier Attack Concerns
     69 -
     70 -## Latency Splits
     71 -
     72 -The old concern was that a last-millisecond share could create two different payout lists, and nodes might race to decide which list was canonical. That sounded uncomfortably close
         to P2Pool's latency-sensitive sharechain problem.
     73 -
     74 -V2.1 narrows the latency cost:
     75 -
     76 -- valid current-parent work can merge forward into the unpaid reserve;
     77 -- a missed last-second previous-parent proof may fail to enter that specific snapshot;
     78 -- it does not create an ongoing winner-take-all sharechain race;
     79 -- nodes are not expected to reorganize an already-observed snapshot because a peer later claims it saw a previous-parent proof first.
     80 -
     81 -Safe claim:
     82 -
     83 -> GridPool still cares about propagation latency, but V2.1 changes the failure mode from a continuous sharechain-orphan race into a bounded snapshot-boundary inclusion risk.
     84 -
     85 -This is materially different from P2Pool's 30-second sharechain cadence, where being first to the next share tip could repeatedly create outsized reward capture.
     86 -
     87 -## Adversarial Splits And "51%" Concerns
     88 -
     89 -Earlier models asked whether a miner with majority GridPool hashrate could create a private favorable branch and later convince others to follow it as the "heavier" list. That model
          assumed retroactive branch replacement was allowed.
     90 -
     91 -V2.1 removes the clean entry point for that attack:
     92 -
     93 -- stale previous-parent work cannot rewrite a snapshot after the local node observed the next Bitcoin block;
     94 -- current-parent work can be merged forward instead of forcing a branch choice;
     95 -- the attacker cannot forge another miner's proof or erase paid lineage by presenting a heavier stale branch;
     96 -- to continue a private stale branch, the attacker gives up normal current-tip mining opportunities, including slot 0 and transaction fees.
     97 -
     98 -This does not mean a majority miner cannot grief, censor, isolate peers, or leave to form a separate team. It means the previous direct path of "mine stale work, reveal a heavier br
         anch, force a retroactive payout-list rewrite" is not the launch rule.
     99 -
    100 -Safe claim:
    101 -
    102 -> V2.1 does not rely on outscoring adversarial stale branches. It makes late stale-parent proofs ineligible to retroactively rewrite finalized snapshots.
    103 -
    104 -## Work Set Conflicts
    105 -
    106 -If two nodes share the same active snapshot but have different unpaid proofs, there is usually no consensus conflict. The correct behavior is not "choose A or B." The correct behavi
         or is:
    107 -
    108 -1. validate each proof against its claimed parent and snapshot context;
    109 -2. discard duplicates and invalid proofs;
    110 -3. merge valid compatible proofs;
    111 -4. sort by achieved difficulty;
    112 -5. retain the top bounded reserve.
    113 -
    114 -This is the key insight missing from the older draft. Most Work Set disagreement is mergeable data synchronization, not Byzantine branch selection.
    115 -
    116 -# Finding 1: 300-Slot Payout Lists Reduce Actual BTC Variance
    117 -
    118 -The variance model treats actual BTC paid as the miner utility target, not just slot inclusion. This distinction matters: if team hashrate doubles, a fixed-size miner receives a sma
         ller fraction of slots per team block, but team blocks arrive more often. Expected BTC stays roughly the same; variance changes because payouts are less clumped.
    119 -
    120 -Reviewed example, `1 PH` miner at team multiplier `10000`:
    121 -
    122 -| Total payout slots | Variance reduction vs solo | Zero-payout probability |
    123 -| ---: | ---: | ---: |
    124 -| 300 | about `271.7x` | about `11.9%` |
    125 -| 100 | about `96.7x` | about `48.8%` |
    126 -| 10 | about `10.0x` | about `93.1%` |
    127 -
    128 -Safe claim:
    129 -
    130 -> A 300-slot payout list substantially reduces payout variance compared with smaller lists once the team finds blocks often enough for the miner to receive recurring shared payouts.
    131 -
    132 -Caveat: tiny miners on tiny teams remain lottery-like because expected paid events are still rare.
    133 -
    134 -![Variance reduction by payout list size](charts/payout_variance__variance_reduction_by_slots.svg)
    135 -
    136 -# Finding 2: Pool Hopping Cannot Create Fake Work
    137 -
    138 -The strongest claim is mechanical: a miner can only retain claims to proof-of-work it already contributed. Hopping cannot mint unpaid shares or steal slots from other miners.
    139 -
    140 -The economic result is more nuanced. With a zero-fee deterministic FPPS-like outside option, the model can show a small free-option effect because already-earned GridPool proofs rem
         ain payable while the miner earns elsewhere. In the reviewed sweep, zero-fee deterministic FPPS hopper EV ratios were roughly `1.0006` to `1.0020`. At 0.5% outside fee, deterministi
         c FPPS hopping fell below fair gross network EV; at 2%, it clearly underperformed.
    141 -
    142 -Safe claim:
    143 -
    144 -> Simulations found at most a small free-option effect under idealized zero-fee outside mining. This is not a way to forge work or steal other miners' shares, and realistic fees, va
         riance, and operational costs can erase or reverse it.
    145 -
    146 -Caveat: solo outside-option runs are noisy because variance changes sharply.
    147 -
    148 -![Pool hopping deterministic FPPS paired delta](charts/pool_hopping__deterministic_fpps_delta_by_external_fee.svg)
    149 -
    150 -# Finding 3: Block Withholding Looks Expensive
    151 -
    152 -The current model compares honest mining, withholding every valid GridPool block, and withholding only when the attacker is underrepresented in the active snapshot.
    153 -
    154 -Attacker EV ratios for withhold-all:
    155 -
    156 -| Transaction fees per block | Attacker EV ratio |
    157 -| ---: | ---: |
    158 -| `0.0 BTC` | about `0.8345` |
    159 -| `0.05 BTC` | about `0.8214` |
    160 -| `0.25 BTC` | about `0.7727` |
    161 -| `1.0 BTC` | about `0.6322` |
    162 -
    163 -Safe claim:
    164 -
    165 -> In the current model, withholding valid GridPool blocks is costly because the finder gives up slot 0, transaction fees, and the acceleration of its own existing shared payout clai
         ms.
    166 -
    167 -Caveat: this does not prove griefing is impossible. It shows that straightforward profit-seeking withholding is unattractive under modeled assumptions.
    168 -
    169 -![Block withholding attacker EV by fee level](charts/block_withholding__attacker_ev_by_fees_btc.svg)
    170 -
    171 -# Finding 4: Compact Relay Still Matters
    172 -
    173 -V2.1 reduces the harm from latency splits, but it does not make latency irrelevant. Fast share propagation still improves the chance that high-difficulty shares are seen by peers be
         fore the next Bitcoin-block snapshot boundary.
    174 -
    175 -The latency model compares three relay profiles:
    176 -
    177 -| Profile | Share mean | Block mean | Payload |
    178 -| --- | ---: | ---: | ---: |
    179 -| JSON/HTTP relay | `650 ms` | `850 ms` | `2200 B` |
    180 -| Compact WebSocket relay | `190 ms` | `850 ms` | `900 B` |
    181 -| UDP-fast relay with fallback | `35 ms` | `850 ms` | `900 B` |
    182 -
    183 -Selected degree-8 split rates:
    184 -
    185 -| Nodes | JSON/HTTP | Compact WebSocket | UDP-fast |
    186 -| ---: | ---: | ---: | ---: |
    187 -| 16 | `0.0050` | `0.00083` | `0.0` |
    188 -| 24 | `0.00542` | `0.00208` | `0.0` |
    189 -| 48 | `0.01333` | `0.00542` | `0.00083` |
    190 -
    191 -Safe claim:
    192 -
    193 -> The network model suggests compact relay materially reduces snapshot-boundary disagreements compared with full JSON relay, and UDP-fast relay may reduce them further.
    194 -
    195 -Caveat: this is model evidence. Live telemetry should be treated as preliminary until there is a clean multi-node UDP run.
    196 -
    197 -![Snapshot split scaling at degree 8](charts/latency__split_rate_by_node_count_degree_8.svg)
    198 -
    199 -# What Older Consensus Scoring Work Still Tells Us
    200 -
    201 -Proof difficulty above a floor has a heavy Pareto tail:
    202 -
    203 -```text
    204 -P(D >= x | D >= floor) = floor / x
    205 -```
    206 -
    207 -That tail means one monster proof can dominate raw summed difficulty even when it came from the smaller side of a split.
    208 -
    209 -Honest-mode mean tie-adjusted accuracy from the wide run:
    210 -
    211 -| Rule | Mean tie-adjusted accuracy |
    212 -| --- | ---: |
    213 -| `bottom_1_times_count` | about `87.64%` |
    214 -| `p10_times_count` | about `87.29%` |
    215 -| `log_sum` | about `85.80%` |
    216 -| `sum_workset_difficulty` | about `75.25%` |
    217 -| `snapshot_sum_difficulty` | about `73.91%` |
    218 -
    219 -The statistical result remains useful: the lowest retained proof in a full reserve is a good estimator of total work observed over comparable windows. But after V2.1, this is no lon
         ger the primary same-boundary conflict resolver for normal operation.
    220 -
    221 -Updated interpretation:
    222 -
    223 -- use reserve-floor/order-statistic metrics for diagnostics, research, and detecting suspicious state quality;
    224 -- do not use a peer's heavier stale branch to retroactively replace a locally finalized snapshot;
    225 -- merge valid compatible current-parent proofs whenever possible;
    226 -- treat non-mergeable stale work as rejected or quarantined, not as a competing canonical branch.
    227 -
    228 -![Honest mature-reserve scoring accuracy](charts/consensus__honest_mature_accuracy_split_900.svg)
    229 -
    230 -# Recommendations For The July 17 Paper
    231 -
    232 -Replace the old section title:
    233 -
    234 -> Consensus Selection Remains Open Research
    235 -
    236 -With:
    237 -
    238 -> V2.1 Reframes Consensus: Merge Valid Work, Finalize Snapshot Boundaries
    239 -
    240 -Specific edits:
    241 -
    242 -- Do not present adversarial split scoring as the main unresolved launch blocker.
    243 -- Present old scoring simulations as the evidence that motivated moving away from retroactive "heaviest stale branch" replacement.
    244 -- Keep the variance, pool-hopping, block-withholding, and latency results.
    245 -- Add V2.1 mechanics early, before attack analysis.
    246 -- Say that live beta still needs regression tests and soak data, but avoid implying that V2.1 still depends on solving a global branch-scoring rule before it can be coherent.
    247 -
    248 -# Claims To Use Carefully
    249 -
    250 -Good phrasing:
    251 -
    252 -- GridPool replaces trusted pool accounting with independently verifiable proof-of-work claims.
    253 -- V2.1 merges valid compatible Work Set proofs instead of choosing between whole branches.
    254 -- Late previous-parent proofs do not retroactively rewrite a locally observed Bitcoin-block payout snapshot.
    255 -- Latency still matters, but the risk is bounded around snapshot inclusion rather than continuous sharechain orphaning.
    256 -- A majority miner can grief or split off, but cannot forge work or force honest nodes to rewrite paid lineage through a stale branch.
    257 -
    258 -Avoid:
    259 -
    260 -- GridPool is immune to 51% attacks.
    261 -- GridPool cannot split.
    262 -- Latency does not matter.
    263 -- Pool hopping is impossible.
    264 -- UDP relay is proven in production.
    265 -- The current network has already field-proven V2.1 at scale.
    266 -
    267 -# Remaining Work Before Publication
    268 -
    269 -Highest-value remaining work:
    270 -
    271 -1. Add or cite regression tests for V2.1 merge behavior, late previous-parent rejection/quarantine, and paid-once lineage.
    272 -2. Run a clean multi-node soak with Main, Dallas, and Evomining on the same V2.1 version.
    273 -3. Collect live relay telemetry: peer observation latency, share relay path, and snapshot-boundary disagreement count.
    274 -4. Rebuild the PDF after this Markdown is reviewed.
    275 -5. Move older adversarial split simulations into an appendix titled "Historical Branch-Selection Models."
    276 -
    277 -# Source Pointers
    278 -
    279 -Primary docs:
    280 -
    281 -- `docs/HANDOFF-2026-07-10.md`
    282 -- `docs/july-17-developer-meeting-findings.md`
    283 -- `docs/consensus-selection-audit-results-2026-06.md`
    284 -- `docs/live-relay-telemetry-plan.md`
    285 -
    286 -Primary generated reports:
    287 -
    288 -- `reports/generated/sweeps/payout_variance_fee_long/report.md`
    289 -- `reports/generated/sweeps/pool_hopping_external_mode_299_long/analysis.md`
    290 -- `reports/generated/sweeps/block_withholding_fee_sensitivity_long/report.md`
    291 -- `reports/generated/sweeps/latency_peer_degree_long/report.md`
    292 -- `reports/generated/consensus_selection_wide_long/report.md`
    293 -- `reports/generated/consensus_selection_eligibility_long/report.md`
    294 -- `reports/generated/delayed_snapshot_attack_survival_poolshare_0.001/report.md`


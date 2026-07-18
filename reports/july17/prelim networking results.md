What Was Measured

  The clean 12-hour window contained 56 unique Bitcoin blocks. Dallas and Detroit each observed those same blocks, producing 112 node/block comparisons. Both
  lack local Bitcoin nodes, so their independent baseline was the Mempool.Space WebSocket notification.

  Evomining has a local Bitcoin ZMQ baseline. Its endpoint is reachable at http://evomining.farted.net, and all four nodes currently agree on current and
  candidate GridPool state.

  ### Chain-Tip Awareness

  For headers originating from Main:

   Receiver    Blocks    GridPool First    Baseline First    Median GridPool Lead    Mean Lead    P95 Lead
  ━━━━━━━━━━  ━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━
   Detroit         56                55                 1                  4.14 s       4.47 s      6.89 s
  ──────────  ────────  ────────────────  ────────────────  ──────────────────────  ───────────  ──────────
   Dallas          56                55                 1                  3.00 s       3.19 s      4.95 s
  ──────────  ────────  ────────────────  ────────────────  ──────────────────────  ───────────  ──────────
   Combined       112               110                 2     approximately 3.5 s       3.83 s      6.89 s

  The range was from GridPool arriving 783 ms behind to 13.69 seconds ahead.

  This does not mean GridPool is propagating full Bitcoin blocks faster than Bitcoin’s network. It means a small header message relayed from Main generally
  reached Dallas and Detroit several seconds before their Mempool.Space WebSocket fallback reported the block.

  ### UDP Versus Persistent Session

  Across Main-origin headers received by Detroit, Dallas, and Evomining:

   Result                      Count
  ━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━
   Header races                  166
  ──────────────────────────  ───────
   UDP first                     105
  ──────────────────────────  ───────
   Effective tie                  55
  ──────────────────────────  ───────
   Persistent session first        6
  ──────────────────────────  ───────
   Median UDP lead              2 ms
  ──────────────────────────  ───────
   P95 UDP lead                17 ms

  Detroit showed the clearest UDP advantage: UDP won all 56 races, normally by 5–18 ms. Dallas and Evomining frequently recorded effective ties because both
  messages arrived within the same millisecond.

  The honest conclusion is that UDP is usually a modest fast path, not an orders-of-magnitude breakthrough. The larger several-second advantage comes from peer-
  to-peer notification versus the external Mempool.Space baseline, not UDP versus WebSocket.

  ### Proof Relay

  Evomining’s latest pulse-proof sample is especially clean:

   Transport    Arrivals    First Arrivals    Share of First Arrivals    P95 Delta    Average Payload
  ━━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━
   UDP               696               580                      82.3%      3.05 ms              914 B
  ───────────  ──────────  ────────────────  ─────────────────────────  ───────────  ─────────────────
   WebSocket         696               105                      14.9%     14.64 ms            4,530 B
  ───────────  ──────────  ────────────────  ─────────────────────────  ───────────  ─────────────────
   HTTP JSON         700                20                       2.8%    307.53 ms        unavailable

  UDP’s payload was approximately 80% smaller than WebSocket. Across the dominant proof categories on Main, Dallas, and Detroit, UDP supplied approximately 68%
  of first arrivals, although those aggregate categories are not perfectly identical and should not be presented as a controlled benchmark.

  ### Evomining Anomaly

  Evomining received 54 Main-origin headers and compared them with local Bitcoin ZMQ:

  - 28 comparisons were within 30 seconds.
  - 26 showed the local Bitcoin notification arriving 75–605 seconds later.
  - Many delays clustered around exactly ten minutes.

  Those outliers make Evomining’s raw average meaningless as a latency benchmark. They point to an intermittent local Bitcoin/ZMQ delivery problem, delayed
  processing, or replay behavior. Evomining should remain in the state-convergence and proof-relay results but be excluded from aggregate chain-tip latency
  until this is diagnosed.

  This anomaly is itself useful: GridPool telemetry detected a local-node notification problem that ordinary service monitoring might miss.

  ## Paper Draft

  ### Preliminary Multi-Region Relay Telemetry

  A 12-hour field observation was collected from four public GridPool nodes. All four nodes reported UDP relay version 5, four known peers, and identical
  current and candidate state identifiers. This demonstrates basic state convergence across independently operated and geographically distributed nodes, but it
  is not evidence of Internet-scale consensus performance.

  The window contained 56 unique Bitcoin blocks. Dallas and Detroit, which use Mempool.Space as their independent chain-tip notification baseline, received
  Main’s GridPool header relay before that baseline for 55 of 56 blocks each. Across 112 node/block observations, GridPool arrived first 110 times. The median
  lead was approximately 3.5 seconds, with a p95 lead of 6.89 seconds.

  For the same Main-origin headers, UDP and the authenticated persistent peer session were raced independently. Across 166 receiver/block comparisons, UDP
  arrived first 105 times, the transports were effectively tied 55 times, and the persistent session arrived first six times. UDP’s median advantage was only 2
  ms and its p95 advantage was 17 ms. This indicates that the persistent session is already an effective fallback, while UDP usually removes a small amount of
  transport overhead.

  Pulse-proof telemetry provided a larger sample. At Evomining, UDP supplied 580 of 705 first proof arrivals, or 82.3%, with a p95 delta of 3.05 ms. Its compact
  payload averaged 914 bytes, compared with 4,530 bytes for the WebSocket representation. Similar behavior was observed at the other public nodes, although
  transport shares varied with topology.

  One node exhibited intermittent local Bitcoin/ZMQ delays of 75–605 seconds. Those samples were excluded from latency aggregates. This illustrates both the
  value and danger of peer header relay: it can expose or temporarily bridge a lagging local notification path, but a peer header must not be treated as trusted
  consensus evidence without local chain validation.

  > These measurements are a field sanity check, not statistical proof. They show that compact UDP relay operates across the public network, frequently supplies
  > the first proof copy, and can distribute chain-tip awareness ahead of an external WebSocket baseline. They do not establish global latency performance,
  > full-block propagation performance, or the safety of mining directly from an unvalidated peer header.

  ## The “So What”

  For GridPool today: UDP relay is working and worth retaining. It is compact, usually first, and backed by a persistent session and HTTP fallback. That is the
  correct reliability model: fast UDP when available, dependable authenticated delivery when it is not.

  For V2.1 snapshots: milliseconds matter only for proofs arriving extremely close to a Bitcoin-block boundary. The observed UDP improvement should reduce that
  narrow inclusion risk, but the current sample cannot quantify how many payout-relevant proofs it saves. It validates the mechanism, not its economic impact.

  For private and home nodes: Dallas and Detroit received useful chain-tip awareness without local Bitcoin nodes. This suggests public GridPool peers can
  provide a faster warning path than a centralized public WebSocket fallback. Nodes should still confirm the header through their own Bitcoin node before making
  consensus-sensitive transitions.

  For “poor man’s FIBRE”: the experiment supports continuing header relay, but not optimistic mining yet. The immediate practical use is synchronized awareness,
  snapshot preparation, telemetry, and detecting slow local Bitcoin notification paths. Full-block reconstruction and safe optimistic mining remain separate,
  substantially harder problems.

  For the networking roadmap: UDP hole punching remains desirable but not launch-critical. Persistent sessions performed within milliseconds of UDP in many
  races, so outbound-only nodes can participate adequately. Direct UDP connectivity offers incremental performance and better topology density rather than being
  a prerequisite for correctness.

  Before stronger claims, the experiment needs several days of clean data, more independent local Bitcoin baselines, corrected Evomining behavior, explicit
  stale-header filtering, and deduplication by block, sender, and transport.


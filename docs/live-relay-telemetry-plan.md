# Live Relay Telemetry Plan

Status: draft.

Purpose: define how to collect preliminary real-world GridPool relay latency
data from the public beta network without overstating what a small three-node
network can prove.

## Current Conclusion

The live network can provide a useful sanity check for the simulation paper, but
it should not be treated as statistically strong evidence yet.

Use field data for wording like:

> Early public-node telemetry confirms that the node can record relay transport,
> arrival order, duplicate arrivals, and payload sizes. Larger, cleaner runs are
> needed before using these measurements as proof of global latency behavior.

Do not use field data yet for wording like:

> UDP relay is proven to reduce real-world split risk by X%.

## Preconditions For A Clean Run

Before collecting data for the July 17 packet:

1. Main, Dallas, and Evomining must agree on `currentStateId` and
   `candidateStateId`.
2. Each node should advertise a reachable public endpoint.
3. Each public endpoint should avoid stale duplicate peer entries.
4. UDP port `5001` must be reachable both ways where UDP is being tested.
5. `/api/network/peer-relay-latency` must show `udp` transport rows, not only
   `websocket` or `http-json`.
6. The run window should be noted explicitly, because share flow depends on
   hashrate and admission floor.

## Current Snapshot From July 7

Observed through `/api/network/summary` and
`/api/network/peer-relay-latency`.

State:

- Main and Dallas matched on current and candidate state.
- Evomining was reachable, but split from Main/Dallas at the time sampled.
- All three nodes reported `udpRelayVersion = 3`.
- The latency endpoint showed WebSocket and HTTP JSON observations, but no UDP
  transport observations yet.

Transport observations:

- Main: 4 WebSocket observations, accepted, average compact payload about
  `3641 B`.
- Dallas: 4 WebSocket duplicate observations and 3 HTTP JSON accepted
  observations.
- Evomining: HTTP JSON/WebSocket duplicate observations, with stale delayed
  WebSocket arrivals due to the current state split.

Interpretation:

This is not yet a UDP benchmark. It is useful as evidence that relay telemetry
exists and can distinguish transport paths.

## Collection Commands

Run from the `boot-protocol` repo.

```bash
node scripts/peer-relay-latency-report.mjs \
  --url https://main.gridpool.net \
  --window 12h \
  --limit 1000
```

```bash
node scripts/peer-relay-latency-report.mjs \
  --url https://dallas.gridpool.net \
  --window 12h \
  --limit 1000
```

```bash
node scripts/peer-relay-latency-report.mjs \
  --url http://evomining.farted.net:5000 \
  --window 12h \
  --limit 1000
```

Filter to UDP only:

```bash
node scripts/peer-relay-latency-report.mjs \
  --url https://main.gridpool.net \
  --window 12h \
  --limit 1000 \
  --transport udp
```

## Minimum Useful Table

For each node and transport:

- observations;
- first arrivals;
- accepted;
- duplicates;
- average/median/p95 delta from first arrival;
- average/min/max payload bytes.

## Why Three Nodes Are Still Useful

A three-node network cannot characterize global topology, but it can validate
instrumentation:

- transport labels are recorded correctly;
- compact payload sizes are in the expected range;
- duplicate arrivals are visible;
- state splits show up as delayed duplicate/rejected arrivals;
- UDP reachability problems are visible as absence of UDP observations.

## Recommended Next Field Run

1. Fix Evomining state convergence and public endpoint cleanup.
2. Verify UDP `5001` forwarding/firewall on all public nodes.
3. Run at least 12 hours with steady hashrate and no manual node restarts.
4. Export latency reports from all nodes.
5. Include the field data as a small appendix, not as a primary proof.


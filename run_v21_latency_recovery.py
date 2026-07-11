#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.engine import sample_pareto_difficulty, sample_poisson
from gridpool_sim.network import RelayProfile, all_pairs_hops, build_peer_graph, relay_profiles_from_config


@dataclass
class Share:
    proof_id: int
    origin_node: int
    difficulty: float
    found_at: float
    parent_height: int
    arrival_times: list[float]


@dataclass
class BlockBoundaryMetric:
    replication: int
    profile: str
    block_height: int
    unique_snapshots: int
    nodes_on_ideal_snapshot: int
    missing_slot_pairs: int
    missing_reserve_pairs: int
    stale_slot_proofs_missed_by_any_node: int
    stale_slot_proofs_missed_by_majority: int
    mean_missing_slots_per_node: float
    p95_missing_slots_per_node: float
    max_missing_slots_on_node: int
    mean_snapshot_lag_ms: float
    p95_snapshot_lag_ms: float
    generated_shares: int
    relayable_shares: int
    estimated_payload_bytes: int


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate V2.1 snapshot-boundary split recovery under relay latency profiles."
    )
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated report files.")
    parser.add_argument("--blocks", type=int, default=2000, help="Bitcoin-block boundaries per replication.")
    parser.add_argument("--replications", type=int, default=8, help="Monte Carlo replications per profile.")
    parser.add_argument("--node-count", type=int, default=24, help="GridPool nodes in simulated network.")
    parser.add_argument("--peer-degree", type=int, default=8, help="Target undirected peer degree.")
    parser.add_argument("--shared-slots", type=int, default=299, help="Shared payout slots after slot 0/support.")
    parser.add_argument("--reserve-multiplier", type=float, default=3.0, help="Unpaid Work Set depth multiplier.")
    parser.add_argument("--shares-per-block", type=float, default=220.0, help="Accepted relay-worthy shares per Bitcoin block at full team.")
    parser.add_argument("--block-interval-seconds", type=float, default=600.0, help="Bitcoin block interval represented by each boundary.")
    parser.add_argument("--admission-floor", type=float, default=1.0, help="Minimum normalized share difficulty.")
    parser.add_argument("--hashrate-sigma", type=float, default=0.9, help="Lognormal sigma for node hashrate weights.")
    parser.add_argument("--seed", type=int, default=21021, help="Base random seed.")
    parser.add_argument("--profiles-json", type=Path, help="Optional JSON scenario containing relay_profiles.")
    parser.add_argument("--quick", action="store_true", help="Short smoke run.")
    parser.add_argument("--heartbeat-seconds", type=float, default=0.0, help="Reserved for CLI compatibility; no-op.")
    args = parser.parse_args()

    if args.quick:
        args.blocks = min(args.blocks, 200)
        args.replications = min(args.replications, 2)
        args.node_count = min(args.node_count, 16)
        args.peer_degree = min(args.peer_degree, 6)

    profiles = load_profiles(args)
    all_metrics: list[BlockBoundaryMetric] = []

    for profile_index, profile in enumerate(profiles):
        for replication in range(args.replications):
            seed = args.seed + (profile_index * 100_000) + replication
            simulator = V21LatencyRecoverySimulator(args, profile, seed, replication)
            all_metrics.extend(simulator.run())
            print(
                f"[v2.1-latency] profile={profile.label} replication={replication + 1}/{args.replications} done",
                flush=True,
            )

    write_outputs(args.out_dir, args, profiles, all_metrics)
    print(f"Wrote V2.1 latency recovery report to {args.out_dir / 'report.md'}")
    return 0


class V21LatencyRecoverySimulator:
    """Boundary-focused V2.1 split model.

    The model tracks what each node has seen when its Bitcoin-block notification
    arrives. Proofs found before that boundary but arriving afterward are counted
    as stale-parent boundary losses for that node; they do not retroactively
    rewrite its active snapshot. Proofs found after the boundary are not treated
    as branch-choice conflicts because V2.1 can merge compatible current-parent
    work forward after validation.
    """

    def __init__(self, args: argparse.Namespace, profile: RelayProfile, seed: int, replication: int):
        self.args = args
        self.profile = profile
        self.seed = seed
        self.replication = replication
        self.rng = random.Random(seed)

        self.reserve_limit = int(math.ceil(args.shared_slots * args.reserve_multiplier))
        self.hashrate_by_node = self._build_hashrate_distribution()
        self.graph = build_peer_graph(args.node_count, args.peer_degree, self.rng)
        self.hops = all_pairs_hops(self.graph)
        self.node_work_sets: list[dict[int, Share]] = [dict() for _ in range(args.node_count)]
        self.ideal_work_set: dict[int, Share] = {}
        self.next_proof_id = 1

    def run(self) -> list[BlockBoundaryMetric]:
        metrics: list[BlockBoundaryMetric] = []
        for block_height in range(1, self.args.blocks + 1):
            block_start = (block_height - 1) * self.args.block_interval_seconds
            block_end = block_height * self.args.block_interval_seconds
            shares = self._generate_shares(block_height, block_start)
            self._insert_ideal(shares)

            ideal_snapshot = top_shares(self.ideal_work_set.values(), self.args.shared_slots)
            ideal_reserve = top_shares(self.ideal_work_set.values(), self.reserve_limit)
            ideal_snapshot_ids = {share.proof_id for share in ideal_snapshot}
            ideal_reserve_ids = {share.proof_id for share in ideal_reserve}

            snapshot_times = [
                block_end + self._sample_block_notification_delay()
                for _ in range(self.args.node_count)
            ]

            signatures: list[tuple[int, ...]] = []
            missing_slots_by_node: list[int] = []
            missing_reserve_by_node: list[int] = []
            snapshot_lags_ms: list[float] = []

            for node_id, snapshot_time in enumerate(snapshot_times):
                for share in shares:
                    if share.proof_id not in ideal_reserve_ids:
                        continue
                    if share.arrival_times[node_id] <= snapshot_time:
                        self.node_work_sets[node_id][share.proof_id] = share

                self.node_work_sets[node_id] = retain_top_dict(self.node_work_sets[node_id], self.reserve_limit)
                node_snapshot = top_shares(self.node_work_sets[node_id].values(), self.args.shared_slots)
                node_snapshot_ids = {share.proof_id for share in node_snapshot}
                node_reserve_ids = set(self.node_work_sets[node_id].keys())

                signatures.append(tuple(share.proof_id for share in node_snapshot))
                missing_slots_by_node.append(len(ideal_snapshot_ids - node_snapshot_ids))
                missing_reserve_by_node.append(len(ideal_reserve_ids - node_reserve_ids))

                if ideal_snapshot:
                    latest_needed_arrival = max(share.arrival_times[node_id] for share in ideal_snapshot)
                    snapshot_lags_ms.append(max(0.0, (latest_needed_arrival - snapshot_time) * 1000.0))
                else:
                    snapshot_lags_ms.append(0.0)

                # V2.1 boundary finality: previous-parent shares that arrive
                # after this node's snapshot do not later rewrite that snapshot.
                # They are intentionally not inserted after this point.

            stale_slot_miss_counts = []
            for share in ideal_snapshot:
                misses = sum(1 for node_id, t in enumerate(snapshot_times) if share.arrival_times[node_id] > t)
                stale_slot_miss_counts.append(misses)

            relayable_count = sum(1 for share in shares if share.proof_id in ideal_reserve_ids)
            metrics.append(
                BlockBoundaryMetric(
                    replication=self.replication,
                    profile=self.profile.label,
                    block_height=block_height,
                    unique_snapshots=len(set(signatures)),
                    nodes_on_ideal_snapshot=sum(
                        1
                        for signature in signatures
                        if signature == tuple(share.proof_id for share in ideal_snapshot)
                    ),
                    missing_slot_pairs=sum(missing_slots_by_node),
                    missing_reserve_pairs=sum(missing_reserve_by_node),
                    stale_slot_proofs_missed_by_any_node=sum(1 for misses in stale_slot_miss_counts if misses > 0),
                    stale_slot_proofs_missed_by_majority=sum(
                        1 for misses in stale_slot_miss_counts if misses > (self.args.node_count / 2)
                    ),
                    mean_missing_slots_per_node=mean(missing_slots_by_node) if missing_slots_by_node else 0.0,
                    p95_missing_slots_per_node=percentile(missing_slots_by_node, 95),
                    max_missing_slots_on_node=max(missing_slots_by_node) if missing_slots_by_node else 0,
                    mean_snapshot_lag_ms=mean(snapshot_lags_ms) if snapshot_lags_ms else 0.0,
                    p95_snapshot_lag_ms=percentile(snapshot_lags_ms, 95),
                    generated_shares=len(shares),
                    relayable_shares=relayable_count,
                    estimated_payload_bytes=relayable_count * self.args.node_count * self.profile.payload_bytes,
                )
            )

        return metrics

    def _build_hashrate_distribution(self) -> list[float]:
        weights = [math.exp(self.rng.gauss(0.0, self.args.hashrate_sigma)) for _ in range(self.args.node_count)]
        total = sum(weights)
        return [weight / total for weight in weights]

    def _generate_shares(self, parent_height: int, block_start: float) -> list[Share]:
        count = sample_poisson(self.rng, self.args.shares_per_block)
        shares: list[Share] = []
        for _ in range(count):
            found_at = block_start + (self.rng.random() * self.args.block_interval_seconds)
            origin = weighted_choice(self.rng, self.hashrate_by_node)
            share = Share(
                proof_id=self.next_proof_id,
                origin_node=origin,
                difficulty=sample_pareto_difficulty(self.rng, self.args.admission_floor),
                found_at=found_at,
                parent_height=parent_height,
                arrival_times=[],
            )
            share.arrival_times = self._arrival_times_for_share(origin, found_at)
            self.next_proof_id += 1
            shares.append(share)
        return shares

    def _arrival_times_for_share(self, origin: int, found_at: float) -> list[float]:
        arrivals = []
        for node_id in range(self.args.node_count):
            hop_count = self.hops[origin][node_id]
            delay = 0.0
            for _ in range(max(0, hop_count)):
                delay += self._sample_share_hop_delay()
            if self.profile.fallback_probability > 0 and self.rng.random() < self.profile.fallback_probability:
                delay += self.profile.fallback_delay_ms / 1000.0
            arrivals.append(found_at + delay)
        return arrivals

    def _sample_share_hop_delay(self) -> float:
        ms = self.rng.gauss(self.profile.share_mean_ms, self.profile.share_jitter_ms)
        return max(0.001, ms / 1000.0)

    def _sample_block_notification_delay(self) -> float:
        ms = self.rng.gauss(self.profile.block_mean_ms, self.profile.block_jitter_ms)
        return max(0.001, ms / 1000.0)

    def _insert_ideal(self, shares: list[Share]) -> None:
        for share in shares:
            self.ideal_work_set[share.proof_id] = share
        self.ideal_work_set = retain_top_dict(self.ideal_work_set, self.reserve_limit)


def load_profiles(args: argparse.Namespace) -> list[RelayProfile]:
    if args.profiles_json:
        scenario = json.loads(args.profiles_json.read_text(encoding="utf-8"))
        return relay_profiles_from_config(scenario)

    scenario = {
        "relay_profiles": [
            {
                "label": "json_http_relay",
                "share_mean_ms": 650,
                "share_jitter_ms": 300,
                "block_mean_ms": 850,
                "block_jitter_ms": 450,
                "payload_bytes": 2200,
            },
            {
                "label": "compact_websocket_relay",
                "share_mean_ms": 190,
                "share_jitter_ms": 90,
                "block_mean_ms": 850,
                "block_jitter_ms": 450,
                "payload_bytes": 900,
            },
            {
                "label": "udp_fast_relay_with_fallback",
                "share_mean_ms": 35,
                "share_jitter_ms": 20,
                "block_mean_ms": 850,
                "block_jitter_ms": 450,
                "payload_bytes": 900,
                "fallback_probability": 0.01,
                "fallback_delay_ms": 800,
            },
        ]
    }
    return relay_profiles_from_config(scenario)


def write_outputs(
    out_dir: Path,
    args: argparse.Namespace,
    profiles: list[RelayProfile],
    metrics: list[BlockBoundaryMetric],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "v21_latency_boundary_metrics.csv", metrics)
    aggregate = aggregate_metrics(metrics, args.node_count, args.shared_slots)
    summary = {
        "scenario": {
            "blocks": args.blocks,
            "replications": args.replications,
            "node_count": args.node_count,
            "peer_degree": args.peer_degree,
            "shared_slots": args.shared_slots,
            "reserve_limit": int(math.ceil(args.shared_slots * args.reserve_multiplier)),
            "shares_per_block": args.shares_per_block,
            "block_interval_seconds": args.block_interval_seconds,
            "admission_floor": args.admission_floor,
            "hashrate_sigma": args.hashrate_sigma,
            "seed": args.seed,
            "relay_profiles": [profile.__dict__ for profile in profiles],
        },
        "aggregate": aggregate,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_report(out_dir / "report.md", summary)


def write_csv(path: Path, metrics: list[BlockBoundaryMetric]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(BlockBoundaryMetric.__dataclass_fields__.keys())
        for metric in metrics:
            writer.writerow([getattr(metric, field) for field in BlockBoundaryMetric.__dataclass_fields__])


def aggregate_metrics(metrics: list[BlockBoundaryMetric], node_count: int, shared_slots: int) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for profile in sorted({metric.profile for metric in metrics}):
        rows = [metric for metric in metrics if metric.profile == profile]
        total_boundaries = len(rows)
        possible_slot_pairs = total_boundaries * node_count * shared_slots
        aggregate[profile] = {
            "boundaries": total_boundaries,
            "split_rate": mean(1.0 if row.unique_snapshots > 1 else 0.0 for row in rows),
            "all_nodes_on_ideal_rate": mean(1.0 if row.nodes_on_ideal_snapshot == node_count else 0.0 for row in rows),
            "mean_unique_snapshots": mean(row.unique_snapshots for row in rows),
            "mean_nodes_on_ideal_snapshot": mean(row.nodes_on_ideal_snapshot for row in rows),
            "mean_missing_slots_per_node": mean(row.mean_missing_slots_per_node for row in rows),
            "p95_missing_slots_per_node": percentile([row.p95_missing_slots_per_node for row in rows], 95),
            "max_missing_slots_on_node": max(row.max_missing_slots_on_node for row in rows),
            "slot_pair_loss_rate": sum(row.missing_slot_pairs for row in rows) / max(1, possible_slot_pairs),
            "mean_stale_slot_proofs_missed_by_any_node": mean(row.stale_slot_proofs_missed_by_any_node for row in rows),
            "mean_stale_slot_proofs_missed_by_majority": mean(row.stale_slot_proofs_missed_by_majority for row in rows),
            "mean_snapshot_lag_ms": mean(row.mean_snapshot_lag_ms for row in rows),
            "p95_snapshot_lag_ms": percentile([row.p95_snapshot_lag_ms for row in rows], 95),
            "mean_generated_shares": mean(row.generated_shares for row in rows),
            "mean_relayable_shares": mean(row.relayable_shares for row in rows),
            "estimated_payload_mb": sum(row.estimated_payload_bytes for row in rows) / 1_000_000,
        }
    return aggregate


def write_report(path: Path, summary: dict[str, Any]) -> None:
    scenario = summary["scenario"]
    lines: list[str] = []
    lines.append("# GridPool V2.1 Latency Boundary Recovery Report")
    lines.append("")
    lines.append("Status: generated by `run_v21_latency_recovery.py`.")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append(
        "This model isolates the V2.1 rule: merge valid current-parent work forward, but do not retroactively rewrite a locally observed Bitcoin-block payout snapshot with late previous-parent work."
    )
    lines.append("")
    lines.append("It measures how relay latency changes:")
    lines.append("")
    lines.append("- snapshot-boundary disagreement rate;")
    lines.append("- stale previous-parent slot proofs missed at the boundary;")
    lines.append("- average and tail missing slots per node;")
    lines.append("- rough payload required by each relay profile.")
    lines.append("")
    lines.append("## Scenario")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("| --- | ---: |")
    for key in [
        "blocks",
        "replications",
        "node_count",
        "peer_degree",
        "shared_slots",
        "reserve_limit",
        "shares_per_block",
        "block_interval_seconds",
        "admission_floor",
        "hashrate_sigma",
        "seed",
    ]:
        lines.append(f"| `{key}` | `{scenario[key]}` |")
    lines.append("")
    lines.append("## Relay Profile Results")
    lines.append("")
    lines.append(
        "| Relay Profile | Split Rate | All Nodes On Ideal | Mean Unique Snapshots | Mean Nodes On Ideal | Mean Missing Slots / Node | P95 Missing Slots / Node | Max Missing Slots | Slot-Pair Loss Rate | Stale Slot Proofs Missed By Any Node | Stale Slot Proofs Missed By Majority | P95 Snapshot Lag ms | Payload MB |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for profile, data in summary["aggregate"].items():
        lines.append(
            "| {profile} | {split:.4%} | {all_ideal:.4%} | {uniq:.3f} | {nodes:.2f} | {miss:.4f} | {p95miss:.4f} | {maxmiss} | {loss:.6%} | {anymiss:.4f} | {majmiss:.4f} | {lag:.2f} | {payload:.2f} |".format(
                profile=profile,
                split=data["split_rate"],
                all_ideal=data["all_nodes_on_ideal_rate"],
                uniq=data["mean_unique_snapshots"],
                nodes=data["mean_nodes_on_ideal_snapshot"],
                miss=data["mean_missing_slots_per_node"],
                p95miss=data["p95_missing_slots_per_node"],
                maxmiss=data["max_missing_slots_on_node"],
                loss=data["slot_pair_loss_rate"],
                anymiss=data["mean_stale_slot_proofs_missed_by_any_node"],
                majmiss=data["mean_stale_slot_proofs_missed_by_majority"],
                lag=data["p95_snapshot_lag_ms"],
                payload=data["estimated_payload_mb"],
            )
        )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- `Split Rate` means at least two nodes produced different active snapshots at the Bitcoin-block boundary.")
    lines.append("- `Slot-Pair Loss Rate` counts ideal snapshot slot/node pairs missing at that node's local snapshot time.")
    lines.append("- Under V2.1, those late previous-parent proofs do not retroactively rewrite that node's active snapshot.")
    lines.append("- This is not modeled as permanent theft of work. Current-parent proofs after the boundary are mergeable into later Work Sets after full validation.")
    lines.append("- Fast relay is still valuable if it materially lowers `Split Rate`, `Slot-Pair Loss Rate`, or tail missing slots.")
    lines.append("")
    lines.append("## Paper-Ready Claim")
    lines.append("")
    lines.append(
        "> V2.1 makes latency primarily a bounded snapshot-boundary inclusion risk. Faster relay reduces that risk, but ordinary current-parent Work Set divergence is mergeable rather than a permanent branch-selection fight."
    )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- This is a propagation model, not runtime consensus code.")
    lines.append("- It does not model adversarial censorship, eclipse attacks, or invalid proof injection.")
    lines.append("- It assumes nodes can validate retained snapshot contexts for current-parent proof merge.")
    lines.append("- It does not model payment transitions after an actual GridPool block.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def top_shares(shares: Any, limit: int) -> list[Share]:
    return sorted(shares, key=lambda share: (-share.difficulty, share.proof_id))[:limit]


def retain_top_dict(shares: dict[int, Share], limit: int) -> dict[int, Share]:
    return {share.proof_id: share for share in top_shares(shares.values(), limit)}


def weighted_choice(rng: random.Random, weights: list[float]) -> int:
    marker = rng.random()
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if marker <= cumulative:
            return index
    return len(weights) - 1


def percentile(values: list[float] | list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


if __name__ == "__main__":
    raise SystemExit(main())

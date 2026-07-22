#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import statistics
from typing import Iterable


BITCOIN_INTERVAL_MS = 600_000.0


@dataclass(frozen=True)
class Proof:
    proof_id: int
    owner: str
    difficulty: float
    created_ms: float
    source_node: int
    kind: str


@dataclass(frozen=True)
class Variant:
    node_count: int
    peer_degree: int
    median_latency_ms: float
    strategy: str
    attacker_share: float
    pool_network_share: float
    stale_fraction: float
    reserve_age_fraction: float


@dataclass
class NodeResult:
    convergence_ms: float
    snapshot_changes: int
    final_snapshot_id: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Model GridPool V2.2 monotonic snapshot reconciliation under honest "
            "boundary races, selective omission, stale-proof insertion, and drip reveal."
        )
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--profile", choices=("quick", "standard", "overnight"), default="standard")
    parser.add_argument("--replications", type=int)
    parser.add_argument("--seed", type=int, default=220022)
    parser.add_argument("--nodes")
    parser.add_argument("--degrees")
    parser.add_argument("--latencies-ms")
    parser.add_argument("--attacker-shares")
    parser.add_argument("--pool-network-shares")
    parser.add_argument("--stale-fractions")
    parser.add_argument("--reserve-age-fractions")
    parser.add_argument("--strategies")
    parser.add_argument("--shared-slots", type=int, default=299)
    parser.add_argument("--reserve-limit", type=int, default=897)
    parser.add_argument("--boundary-proofs", type=float, default=8.0)
    parser.add_argument("--boundary-window-ms", type=float, default=2_000.0)
    parser.add_argument("--proofs-per-bitcoin-block", type=float, default=100.0)
    parser.add_argument("--validation-ms", type=float, default=2.0)
    parser.add_argument("--omission-count", type=int, default=3)
    parser.add_argument("--subsidy-btc", type=float, default=3.125)
    parser.add_argument("--fees-btc", type=float, default=0.05)
    args = parser.parse_args()

    apply_profile(args)
    validate_args(args)
    run_self_checks()
    variants = build_variants(args)
    total = len(variants) * args.replications
    rows: list[dict[str, object]] = []
    completed = 0
    for variant_index, variant in enumerate(variants):
        for replication in range(args.replications):
            seed = args.seed + variant_index * 1_000_003 + replication
            rows.append(run_replication(args, variant, replication, seed))
            completed += 1
            if completed == total or completed % max(1, total // 100) == 0:
                print(
                    f"[{completed}/{total}] nodes={variant.node_count} degree={variant.peer_degree} "
                    f"latency={variant.median_latency_ms:g}ms strategy={variant.strategy} "
                    f"attacker={variant.attacker_share:.0%}",
                    flush=True,
                )

    summaries = aggregate(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "v22_reconciliation_replications.csv", rows)
    write_csv(args.out_dir / "v22_reconciliation_summary.csv", summaries)
    metadata = build_metadata(args, variants)
    (args.out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_report(args.out_dir / "report.md", summaries, metadata)
    print(f"Wrote V2.2 reconciliation report to {args.out_dir / 'report.md'}")
    return 0


def apply_profile(args: argparse.Namespace) -> None:
    profiles = {
        "quick": {
            "replications": 3,
            "nodes": "4,16",
            "degrees": "2,4",
            "latencies_ms": "50,200",
            "attacker_shares": "0.35,0.51",
            "pool_network_shares": "0.001,0.03",
            "stale_fractions": "0.05,0.25",
            "reserve_age_fractions": "0.25,1.0",
            "strategies": "honest,omit,stale_batch,stale_drip",
        },
        "standard": {
            "replications": 25,
            "nodes": "4,16,64",
            "degrees": "2,4,8",
            "latencies_ms": "25,100,400",
            "attacker_shares": "0.10,0.35,0.51",
            "pool_network_shares": "0.001,0.01,0.03",
            "stale_fractions": "0.05,0.25,1.0",
            "reserve_age_fractions": "0.10,0.50,1.0",
            "strategies": "honest,omit,stale_batch,stale_drip",
        },
        "overnight": {
            "replications": 20,
            "nodes": "4,16,64",
            "degrees": "2,4,8",
            "latencies_ms": "25,100,400,1000",
            "attacker_shares": "0.10,0.35,0.51,0.67",
            "pool_network_shares": "0.0001,0.001,0.01,0.03",
            "stale_fractions": "0.01,0.05,0.25,1.0",
            "reserve_age_fractions": "0.05,0.25,1.0",
            "strategies": "honest,omit,stale_batch,stale_drip",
        },
    }
    selected = profiles[args.profile]
    for name, value in selected.items():
        if getattr(args, name) is None:
            setattr(args, name, value)


def validate_args(args: argparse.Namespace) -> None:
    if args.replications <= 0:
        raise SystemExit("--replications must be positive")
    if not 0 < args.shared_slots <= args.reserve_limit:
        raise SystemExit("--shared-slots must be positive and no larger than --reserve-limit")
    if args.boundary_proofs < 0 or args.proofs_per_bitcoin_block <= 0:
        raise SystemExit("proof rates must be non-negative, with block proof rate positive")
    valid_strategies = {"honest", "omit", "stale_batch", "stale_drip"}
    if not set(parse_strings(args.strategies)) <= valid_strategies:
        raise SystemExit(f"--strategies must be in {sorted(valid_strategies)}")
    for value in parse_floats(args.attacker_shares):
        if not 0 < value < 1:
            raise SystemExit("attacker shares must be in (0, 1)")
    for value in parse_floats(args.pool_network_shares):
        if not 0 < value <= 1:
            raise SystemExit("pool network shares must be in (0, 1]")
    for value in parse_floats(args.stale_fractions):
        if not 0 <= value <= 1:
            raise SystemExit("stale fractions must be in [0, 1]")
    for value in parse_floats(args.reserve_age_fractions):
        if not 0 <= value <= 1:
            raise SystemExit("reserve age fractions must be in [0, 1]")


def build_variants(args: argparse.Namespace) -> list[Variant]:
    variants: list[Variant] = []
    attacker_shares = parse_floats(args.attacker_shares)
    pool_shares = parse_floats(args.pool_network_shares)
    stale_fractions = parse_floats(args.stale_fractions)
    reserve_ages = parse_floats(args.reserve_age_fractions)
    strategies = parse_strings(args.strategies)
    for node_count in parse_ints(args.nodes):
        for degree in parse_ints(args.degrees):
            if degree >= node_count and node_count > 2:
                continue
            effective_degree = min(degree, node_count - 1)
            for latency in parse_floats(args.latencies_ms):
                if "honest" in strategies:
                    variants.append(Variant(node_count, effective_degree, latency, "honest", 0.35, 0.01, 0.0, 1.0))
                if "omit" in strategies:
                    for attacker_share in attacker_shares:
                        variants.append(Variant(node_count, effective_degree, latency, "omit", attacker_share, 0.01, 0.0, 1.0))
                for strategy in ("stale_batch", "stale_drip"):
                    if strategy not in strategies:
                        continue
                    for attacker_share in attacker_shares:
                        for pool_share in pool_shares:
                            for stale_fraction in stale_fractions:
                                for reserve_age in reserve_ages:
                                    variants.append(
                                        Variant(
                                            node_count,
                                            effective_degree,
                                            latency,
                                            strategy,
                                            attacker_share,
                                            pool_share,
                                            stale_fraction,
                                            reserve_age,
                                        )
                                    )
    return variants


def run_replication(args: argparse.Namespace, variant: Variant, replication: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    graph = build_graph(variant.node_count, variant.peer_degree, variant.median_latency_ms, rng)
    distances = all_pairs_shortest_paths(graph)
    attacker_node = 0
    next_id = 1

    expected_round_samples = args.proofs_per_bitcoin_block / variant.pool_network_share
    prior_reserve, next_id = sample_ranked_proofs(
        rng,
        expected_round_samples,
        args.reserve_limit,
        variant.attacker_share,
        next_id,
        "carried",
    )
    carried_unpaid = prior_reserve[args.shared_slots:]
    current_proofs, next_id = sample_ranked_proofs(
        rng,
        expected_round_samples * variant.reserve_age_fraction,
        args.reserve_limit,
        variant.attacker_share,
        next_id,
        "current",
    )
    common_reserve = top_proofs([*carried_unpaid, *current_proofs], args.reserve_limit)

    boundary_proofs: list[Proof] = []
    for _ in range(sample_poisson(rng, args.boundary_proofs)):
        source = rng.randrange(variant.node_count)
        owner = "attacker" if rng.random() < variant.attacker_share else "honest"
        boundary_proofs.append(
            Proof(next_id, owner, sample_pareto(rng, 1.0), rng.uniform(-args.boundary_window_ms, 0.0), source, "boundary")
        )
        next_id += 1

    initial_reserves: list[list[Proof]] = []
    for node in range(variant.node_count):
        arrived = [
            proof for proof in boundary_proofs
            if proof.created_ms + distances[proof.source_node][node] <= 0.0
        ]
        initial_reserves.append(top_proofs([*common_reserve, *arrived], args.reserve_limit))

    baseline_reserves = [list(reserve) for reserve in initial_reserves]
    baseline_members = [(0.0, node, reserve) for node, reserve in enumerate(baseline_reserves)]
    honest_final_reserve = union_top((reserve for _, _, reserve in baseline_members), args.reserve_limit)
    honest_final_snapshot = top_proofs(honest_final_reserve, args.shared_slots)

    if variant.strategy == "omit":
        attacker_known = initial_reserves[attacker_node]
        omitted = [proof for proof in attacker_known if proof.owner == "honest"][: args.omission_count]
        omitted_ids = {proof.proof_id for proof in omitted}
        initial_reserves[attacker_node] = top_proofs(
            [proof for proof in attacker_known if proof.proof_id not in omitted_ids], args.reserve_limit
        )

    honest_members = [(0.0, node, reserve) for node, reserve in enumerate(initial_reserves)]
    initial_snapshot_ids = {snapshot_id(top_proofs(reserve, args.shared_slots)) for reserve in initial_reserves}
    initial_split = len(initial_snapshot_ids) > 1

    stale_proofs: list[Proof] = []
    if variant.strategy.startswith("stale"):
        expected = args.proofs_per_bitcoin_block * variant.attacker_share * variant.stale_fraction
        for _ in range(sample_poisson(rng, expected)):
            stale_proofs.append(
                Proof(
                    next_id,
                    "attacker",
                    sample_pareto(rng, 1.0),
                    rng.uniform(0.0, variant.stale_fraction * BITCOIN_INTERVAL_MS),
                    attacker_node,
                    "stale",
                )
            )
            next_id += 1

    members = list(honest_members)
    if variant.strategy == "stale_batch" and stale_proofs:
        reveal_ms = max(proof.created_ms for proof in stale_proofs)
        attack_member = top_proofs([*initial_reserves[attacker_node], *stale_proofs], args.reserve_limit)
        members.append((reveal_ms, attacker_node, attack_member))
    elif variant.strategy == "stale_drip":
        attacker_member = list(initial_reserves[attacker_node])
        for proof in sorted(stale_proofs, key=lambda item: item.created_ms):
            attacker_member = top_proofs([*attacker_member, proof], args.reserve_limit)
            members.append((proof.created_ms, attacker_node, list(attacker_member)))

    final_reserve = union_top((reserve for _, _, reserve in members), args.reserve_limit)
    final_snapshot = top_proofs(final_reserve, args.shared_slots)
    final_id = snapshot_id(final_snapshot)
    node_results = [
        simulate_node_reconciliation(
            node, initial_reserves[node], members, distances, args.reserve_limit,
            args.shared_slots, args.validation_ms, final_id,
        )
        for node in range(variant.node_count)
    ]

    v22_converged = len({result.final_snapshot_id for result in node_results}) == 1
    v22_convergence_ms = max(result.convergence_ms for result in node_results)
    v21_converged = not initial_split
    template_changes = sum(result.snapshot_changes for result in node_results)
    max_node_changes = max(result.snapshot_changes for result in node_results)
    node_weights = node_hash_weights(variant.node_count, variant.attacker_share, attacker_node)
    superseded_work_fraction = sum(
        node_weights[node] * min(result.convergence_ms, BITCOIN_INTERVAL_MS) / BITCOIN_INTERVAL_MS
        for node, result in enumerate(node_results)
    )

    attacker_slots_before = owner_slots(honest_final_snapshot, "attacker")
    attacker_slots_after = owner_slots(final_snapshot, "attacker")
    accelerated_slots = max(0, attacker_slots_after - attacker_slots_before)
    stale_in_reserve = sum(proof.kind == "stale" for proof in final_reserve)
    stale_in_snapshot = sum(proof.kind == "stale" for proof in final_snapshot)
    slot_value = args.subsidy_btc / (args.shared_slots + 1)
    expected_accelerated_reward_btc = variant.pool_network_share * accelerated_slots * slot_value
    stale_opportunity_cost_btc = (
        variant.pool_network_share * variant.attacker_share * variant.stale_fraction * (args.subsidy_btc + args.fees_btc)
    )

    return {
        "node_count": variant.node_count,
        "peer_degree": variant.peer_degree,
        "median_latency_ms": variant.median_latency_ms,
        "strategy": variant.strategy,
        "attacker_share": variant.attacker_share,
        "pool_network_share": variant.pool_network_share,
        "stale_fraction": variant.stale_fraction,
        "reserve_age_fraction": variant.reserve_age_fraction,
        "replication": replication,
        "seed": seed,
        "initial_split": int(initial_split),
        "initial_snapshot_count": len(initial_snapshot_ids),
        "v21_converged_without_external_recovery": int(v21_converged),
        "v22_converged": int(v22_converged),
        "v22_convergence_ms": v22_convergence_ms,
        "total_template_changes": template_changes,
        "max_node_template_changes": max_node_changes,
        "superseded_work_fraction": superseded_work_fraction,
        "boundary_proof_count": len(boundary_proofs),
        "family_member_messages": len(members),
        "final_reserve_count": len(final_reserve),
        "stale_proof_count": len(stale_proofs),
        "stale_proofs_in_final_reserve": stale_in_reserve,
        "stale_proofs_in_active_snapshot": stale_in_snapshot,
        "attacker_slots_before_stale": attacker_slots_before,
        "attacker_slots_after_stale": attacker_slots_after,
        "accelerated_attacker_slots": accelerated_slots,
        "expected_accelerated_reward_btc": expected_accelerated_reward_btc,
        "stale_opportunity_cost_btc": stale_opportunity_cost_btc,
        "expected_attack_net_btc": expected_accelerated_reward_btc - stale_opportunity_cost_btc,
        "omission_changed_final_snapshot": int(
            variant.strategy == "omit" and snapshot_id(final_snapshot) != snapshot_id(honest_final_snapshot)
        ),
    }


def simulate_node_reconciliation(
    node: int,
    initial_reserve: list[Proof],
    members: list[tuple[float, int, list[Proof]]],
    distances: list[list[float]],
    reserve_limit: int,
    shared_slots: int,
    validation_ms: float,
    final_snapshot_id: str,
) -> NodeResult:
    known = {proof.proof_id: proof for proof in initial_reserve}
    active_id = snapshot_id(top_proofs(known.values(), shared_slots))
    changes = 0
    last_change_ms = 0.0
    events: list[tuple[float, int, list[Proof]]] = []
    for sequence, (created_ms, source, reserve) in enumerate(members):
        if source == node and created_ms == 0.0:
            continue
        events.append((created_ms + distances[source][node] + validation_ms, sequence, reserve))
    events.sort(key=lambda item: (item[0], item[1]))

    for arrival_ms, _, reserve in events:
        added = False
        for proof in reserve:
            if proof.proof_id not in known:
                known[proof.proof_id] = proof
                added = True
        if not added:
            continue
        bounded = top_proofs(known.values(), reserve_limit)
        known = {proof.proof_id: proof for proof in bounded}
        next_id = snapshot_id(top_proofs(bounded, shared_slots))
        if next_id != active_id:
            active_id = next_id
            changes += 1
            last_change_ms = arrival_ms
    convergence_ms = last_change_ms if active_id == final_snapshot_id else math.inf
    return NodeResult(convergence_ms, changes, active_id)


def build_graph(node_count: int, degree: int, median_latency_ms: float, rng: random.Random) -> list[dict[int, float]]:
    graph: list[dict[int, float]] = [dict() for _ in range(node_count)]
    if node_count == 2:
        add_edge(graph, 0, 1, sample_latency(rng, median_latency_ms))
        return graph
    for node in range(node_count):
        add_edge(graph, node, (node + 1) % node_count, sample_latency(rng, median_latency_ms))
    target = min(max(2, degree), node_count - 1)
    attempts = 0
    while any(len(neighbors) < target for neighbors in graph):
        candidates = [node for node, neighbors in enumerate(graph) if len(neighbors) < target]
        left = rng.choice(candidates)
        possible = [node for node in range(node_count) if node != left and node not in graph[left]]
        if not possible:
            break
        add_edge(graph, left, rng.choice(possible), sample_latency(rng, median_latency_ms))
        attempts += 1
        if attempts > node_count * node_count * 4:
            break
    return graph


def add_edge(graph: list[dict[int, float]], left: int, right: int, latency: float) -> None:
    graph[left][right] = latency
    graph[right][left] = latency


def sample_latency(rng: random.Random, median_latency_ms: float) -> float:
    return max(0.1, rng.lognormvariate(math.log(median_latency_ms), 0.35))


def all_pairs_shortest_paths(graph: list[dict[int, float]]) -> list[list[float]]:
    return [shortest_paths(graph, source) for source in range(len(graph))]


def shortest_paths(graph: list[dict[int, float]], source: int) -> list[float]:
    distances = [math.inf] * len(graph)
    distances[source] = 0.0
    queue = [(0.0, source)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        for neighbor, latency in graph[node].items():
            candidate = distance + latency
            if candidate < distances[neighbor]:
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return distances


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    keys = (
        "node_count",
        "peer_degree",
        "median_latency_ms",
        "strategy",
        "attacker_share",
        "pool_network_share",
        "stale_fraction",
        "reserve_age_fraction",
    )
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(tuple(row[key] for key in keys), []).append(row)
    metrics = (
        "initial_split", "initial_snapshot_count", "v21_converged_without_external_recovery",
        "v22_converged", "v22_convergence_ms", "total_template_changes",
        "max_node_template_changes", "superseded_work_fraction", "boundary_proof_count",
        "family_member_messages", "stale_proof_count", "stale_proofs_in_final_reserve",
        "stale_proofs_in_active_snapshot", "accelerated_attacker_slots",
        "expected_accelerated_reward_btc", "stale_opportunity_cost_btc",
        "expected_attack_net_btc", "omission_changed_final_snapshot",
    )
    summaries: list[dict[str, object]] = []
    for key, group in sorted(grouped.items(), key=lambda item: tuple(str(value) for value in item[0])):
        summary: dict[str, object] = dict(zip(keys, key))
        summary["replications"] = len(group)
        for metric in metrics:
            values = [float(row[metric]) for row in group]
            summary[f"mean_{metric}"] = statistics.fmean(values)
            summary[f"p95_{metric}"] = percentile(values, 0.95)
        split_group = [row for row in group if int(row["initial_split"]) == 1]
        split_convergence = [float(row["v22_convergence_ms"]) for row in split_group]
        split_work = [float(row["superseded_work_fraction"]) for row in split_group]
        summary["split_trials"] = len(split_group)
        summary["mean_split_convergence_ms"] = statistics.fmean(split_convergence) if split_convergence else 0.0
        summary["p95_split_convergence_ms"] = percentile(split_convergence, 0.95) if split_convergence else 0.0
        summary["mean_split_superseded_work_fraction"] = statistics.fmean(split_work) if split_work else 0.0
        summaries.append(summary)
    return summaries


def build_metadata(args: argparse.Namespace, variants: list[Variant]) -> dict[str, object]:
    return {
        "profile": args.profile,
        "replications_per_variant": args.replications,
        "variant_count": len(variants),
        "shared_slots": args.shared_slots,
        "reserve_limit": args.reserve_limit,
        "boundary_proofs_expected": args.boundary_proofs,
        "boundary_window_ms": args.boundary_window_ms,
        "proofs_per_bitcoin_block": args.proofs_per_bitcoin_block,
        "validation_ms": args.validation_ms,
        "model_scope": [
            "This is a mechanism model, not a proof of distributed consensus or production safety.",
            "All family members share one predecessor snapshot and one Bitcoin boundary; cross-family and reorg behavior is excluded.",
            "V2.1 persistence is represented by the absence of an automatic active-snapshot merge after an initial split.",
            "V2.2 nodes exchange complete boundary reserves and compute a proof-ID union followed by canonical top-K ranking.",
            "Omission variants remove honest proofs only from the attacker's advertised member; union should restore any proof advertised by another node.",
            "Stale variants let the attacker claim valid post-boundary stale proofs as family additions because peer timestamps cannot disprove the claim.",
            "The paired honest alternative gives those hashes the same future reserve opportunity on the current parent; modeled attack value is only accelerated active-snapshot eligibility before the next Bitcoin block.",
            "Expected accelerated reward equals next-block GridPool probability times added attacker slots times fixed slot value.",
            "Stale opportunity cost is the expected current-chain block reward forgone while the attacker mines stale work.",
            "Reserve strength uses proof order statistics: 598 unpaid proofs carry across a 299-slot payment and new work accumulates for the configured fraction of an expected GridPool round.",
            "Transaction propagation, ASIC job-switch delay, invalid proofs, Bitcoin reorgs, and implementation limits are excluded.",
        ],
    }


def write_report(path: Path, rows: list[dict[str, object]], metadata: dict[str, object]) -> None:
    honest = [row for row in rows if row["strategy"] == "honest"]
    omission = [row for row in rows if row["strategy"] == "omit"]
    stale = [row for row in rows if str(row["strategy"]).startswith("stale")]
    lines = [
        "# GridPool V2.2 Monotonic Snapshot Reconciliation Simulation", "",
        "Status: exploratory adversarial model. This is not a consensus proof.", "",
        "## Honest Boundary Recovery", "",
        "| Nodes | Degree | Median Link | Initial Split | V2.1 Auto-Convergence | V2.2 Convergence | Mean Split Convergence | P95 Split Convergence | Mean Template Changes | Split Superseded Work |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in honest:
        lines.append(
            "| {nodes} | {degree} | {latency:.0f} ms | {split:.1%} | {v21:.1%} | {v22:.1%} | {mean:.1f} ms | {p95:.1f} ms | {changes:.2f} | {work:.4%} |".format(
                nodes=row["node_count"], degree=row["peer_degree"], latency=float(row["median_latency_ms"]),
                split=float(row["mean_initial_split"]), v21=float(row["mean_v21_converged_without_external_recovery"]),
                v22=float(row["mean_v22_converged"]), mean=float(row["mean_split_convergence_ms"]),
                p95=float(row["p95_split_convergence_ms"]), changes=float(row["mean_total_template_changes"]),
                work=float(row["mean_split_superseded_work_fraction"]),
            )
        )
    lines.extend(["", "## Selective Omission", "", "| Nodes | Degree | Link | Attacker Hash | Omission Changed Final Snapshot | V2.2 Convergence | Mean Convergence |", "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in omission:
        lines.append(
            "| {nodes} | {degree} | {latency:.0f} ms | {attacker:.0%} | {changed:.2%} | {converged:.1%} | {mean:.1f} ms |".format(
                nodes=row["node_count"], degree=row["peer_degree"], latency=float(row["median_latency_ms"]),
                attacker=float(row["attacker_share"]), changed=float(row["mean_omission_changed_final_snapshot"]),
                converged=float(row["mean_v22_converged"]), mean=float(row["mean_v22_convergence_ms"]),
            )
        )
    lines.extend(["", "## Stale-Proof Insertion", "", "| Strategy | Nodes | Degree | Link | Attacker Hash | Pool Network Share | Reserve Age | Stale Window | Active Stale Proofs | Accelerated Slots | Reward BTC | Cost BTC | Net BTC | Template Changes |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in stale:
        lines.append(
            "| `{strategy}` | {nodes} | {degree} | {latency:.0f} ms | {attacker:.0%} | {pool:.3%} | {age:.0%} | {window:.0%} | {active:.3f} | {slots:.3f} | {reward:.8f} | {cost:.8f} | {net:+.8f} | {changes:.2f} |".format(
                strategy=row["strategy"], nodes=row["node_count"], degree=row["peer_degree"], latency=float(row["median_latency_ms"]),
                attacker=float(row["attacker_share"]), pool=float(row["pool_network_share"]), age=float(row["reserve_age_fraction"]), window=float(row["stale_fraction"]),
                active=float(row["mean_stale_proofs_in_active_snapshot"]), slots=float(row["mean_accelerated_attacker_slots"]),
                reward=float(row["mean_expected_accelerated_reward_btc"]), cost=float(row["mean_stale_opportunity_cost_btc"]),
                net=float(row["mean_expected_attack_net_btc"]), changes=float(row["mean_total_template_changes"]),
            )
        )
    lines.extend(["", "## Interpretation Limits", ""])
    lines.extend(f"- {item}" for item in metadata["model_scope"])
    lines.extend(["", "## Decision Guidance", "", "- Honest convergence should be read primarily for trials that began split; unsplit trials correctly converge at time zero.", "- Omission should never change the final union when at least one node advertises the omitted proof.", "- A positive stale-attack net value is a protocol warning, not proof of exploitability. A negative value does not address non-economic griefing.", "- Compare `stale_drip` template changes with `stale_batch` before selecting an activation rule."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_self_checks() -> None:
    a = Proof(1, "honest", 10.0, 0.0, 0, "test")
    b = Proof(2, "attacker", 20.0, 0.0, 0, "test")
    c = Proof(3, "honest", 15.0, 0.0, 0, "test")
    left = union_top(([a, b], [b, c]), 2)
    right = union_top(([b, c], [a, b]), 2)
    if proof_ids(left) != proof_ids(right) or proof_ids(left) != (2, 3):
        raise RuntimeError("union commutativity/deduplication self-check failed")
    if proof_ids(union_top((left, left), 2)) != proof_ids(left):
        raise RuntimeError("union idempotence self-check failed")
    if set(proof_ids(union_top(([a, b, c], [b]), 3))) != {1, 2, 3}:
        raise RuntimeError("omission monotonicity self-check failed")


def top_proofs(proofs: Iterable[Proof], limit: int) -> list[Proof]:
    unique: dict[int, Proof] = {}
    for proof in proofs:
        existing = unique.get(proof.proof_id)
        if existing is not None and existing != proof:
            raise RuntimeError(f"conflicting proof payload for ID {proof.proof_id}")
        unique[proof.proof_id] = proof
    return sorted(unique.values(), key=lambda proof: (-proof.difficulty, proof.proof_id))[:limit]


def union_top(reserves: Iterable[Iterable[Proof]], limit: int) -> list[Proof]:
    return top_proofs((proof for reserve in reserves for proof in reserve), limit)


def proof_ids(proofs: Iterable[Proof]) -> tuple[int, ...]:
    return tuple(proof.proof_id for proof in proofs)


def snapshot_id(proofs: Iterable[Proof]) -> str:
    payload = ",".join(str(proof_id) for proof_id in proof_ids(proofs)).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def owner_slots(proofs: Iterable[Proof], owner: str) -> int:
    return sum(proof.owner == owner for proof in proofs)


def node_hash_weights(node_count: int, attacker_share: float, attacker_node: int) -> list[float]:
    honest_weight = (1.0 - attacker_share) / max(1, node_count - 1)
    return [attacker_share if node == attacker_node else honest_weight for node in range(node_count)]


def sample_ranked_proofs(
    rng: random.Random,
    expected_count: float,
    limit: int,
    attacker_share: float,
    next_id: int,
    kind: str,
) -> tuple[list[Proof], int]:
    """Sample exact top order statistics without allocating every low proof."""
    sample_count = sample_poisson(rng, expected_count)
    retained_count = min(sample_count, limit)
    if retained_count == 0:
        return [], next_id

    spacings = [rng.expovariate(1.0) for _ in range(retained_count)]
    tail_shape = sample_count + 1 - retained_count
    tail = rng.gammavariate(tail_shape, 1.0) if tail_shape > 0 else 0.0
    total = sum(spacings) + tail
    cumulative = 0.0
    proofs: list[Proof] = []
    for spacing in spacings:
        cumulative += spacing
        normalized_order_statistic = cumulative / total
        owner = "attacker" if rng.random() < attacker_share else "honest"
        proofs.append(
            Proof(
                next_id,
                owner,
                1.0 / max(1e-300, normalized_order_statistic),
                -math.inf,
                0,
                kind,
            )
        )
        next_id += 1
    return proofs, next_id


def sample_pareto(rng: random.Random, floor: float) -> float:
    return floor / max(1e-15, 1.0 - rng.random())


def sample_poisson(rng: random.Random, expected: float) -> int:
    if expected <= 0:
        return 0
    if expected > 50:
        return max(0, round(rng.gauss(expected, math.sqrt(expected))))
    limit = math.exp(-expected)
    product = 1.0
    count = 0
    while product > limit:
        product *= rng.random()
        count += 1
    return count - 1


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def parse_strings(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_floats(value: str) -> list[float]:
    return [float(part) for part in parse_strings(value)]


def parse_ints(value: str) -> list[int]:
    return [int(part) for part in parse_strings(value)]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())

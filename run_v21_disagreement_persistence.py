#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import sys
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.engine import sample_pareto_difficulty, sample_poisson
from gridpool_sim.network import RelayProfile, all_pairs_hops, build_peer_graph, relay_profiles_from_config


@dataclass(frozen=True)
class Proof:
    proof_id: int
    miner_id: int
    difficulty: float
    parent_height: int


@dataclass
class BoundaryMetric:
    profile: str
    pool_network_share: float
    replication: int
    block_height: int
    gridpool_block: bool
    active_divergent_before_payment: bool
    unique_active_snapshots_before_payment: int
    paid_snapshot_differs_from_modal: bool
    paid_proof_slots_different_from_modal: int
    paid_recipient_slots_reallocated: int
    active_divergent_after_boundary: bool
    unique_active_snapshots_after_boundary: int
    mean_proof_slots_different_from_modal: float
    mean_recipient_slots_reallocated_from_modal: float
    all_nodes_on_modal_snapshot: int
    generated_shares: int
    reserve_relevant_shares: int


@dataclass
class EpisodeMetric:
    profile: str
    pool_network_share: float
    replication: int
    started_at_height: int
    ended_at_height: int | None
    duration_boundaries: int
    gridpool_blocks_during_episode: int
    max_unique_snapshots: int
    max_mean_proof_slots_different_from_modal: float
    max_mean_recipient_slots_reallocated_from_modal: float
    censored_at_end: bool


@dataclass
class ProofDisagreementMetric:
    profile: str
    pool_network_share: float
    replication: int
    proof_id: int
    miner_id: int
    started_at_height: int
    ended_at_height: int | None
    duration_boundaries: int
    resolution: str
    censored_at_end: bool


@dataclass(frozen=True)
class Task:
    args_dict: dict[str, Any]
    profile_dict: dict[str, Any]
    pool_network_share: float
    replication: int
    seed: int


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extend the V2.1 boundary model through cutoff displacement and actual "
            "GridPool payment transitions."
        )
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--blocks", type=int, default=2000, help="Bitcoin boundaries per task.")
    parser.add_argument("--replications", type=int, default=6)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--node-count", type=int, default=24)
    parser.add_argument("--peer-degree", type=int, default=8)
    parser.add_argument("--shared-slots", type=int, default=299)
    parser.add_argument("--reserve-multiplier", type=float, default=3.0)
    parser.add_argument("--shares-per-block", type=float, default=220.0)
    parser.add_argument("--block-interval-seconds", type=float, default=600.0)
    parser.add_argument("--admission-floor", type=float, default=1.0)
    parser.add_argument("--hashrate-sigma", type=float, default=0.9)
    parser.add_argument("--bootstrap-multiplier", type=float, default=10.0)
    parser.add_argument(
        "--pool-network-shares",
        default="0,0.001,0.01,0.1,0.5",
        help="Comma-separated GridPool fractions of total Bitcoin hashrate; zero is a no-payment persistence baseline.",
    )
    parser.add_argument("--profiles-json", type=Path)
    parser.add_argument("--seed", type=int, default=21031)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.blocks = min(args.blocks, 120)
        args.replications = 1
        args.node_count = min(args.node_count, 12)
        args.peer_degree = min(args.peer_degree, 4)
        args.pool_network_shares = "0,0.01,0.1"

    pool_shares = parse_float_list(args.pool_network_shares)
    if any(value < 0.0 or value > 1.0 for value in pool_shares):
        raise SystemExit("--pool-network-shares values must be in [0, 1].")

    profiles = load_profiles(args)
    args_dict = vars(args).copy()
    args_dict["out_dir"] = str(args.out_dir)
    args_dict["profiles_json"] = str(args.profiles_json) if args.profiles_json else None

    tasks: list[Task] = []
    for profile_index, profile in enumerate(profiles):
        for pool_index, pool_share in enumerate(pool_shares):
            for replication in range(args.replications):
                tasks.append(
                    Task(
                        args_dict=args_dict,
                        profile_dict=asdict(profile),
                        pool_network_share=pool_share,
                        replication=replication,
                        seed=args.seed + profile_index * 1_000_000 + pool_index * 10_000 + replication,
                    )
                )

    boundary_metrics: list[BoundaryMetric] = []
    episode_metrics: list[EpisodeMetric] = []
    proof_disagreement_metrics: list[ProofDisagreementMetric] = []
    if args.jobs <= 1:
        for index, task in enumerate(tasks, start=1):
            boundaries, episodes, proof_episodes = run_task(task)
            boundary_metrics.extend(boundaries)
            episode_metrics.extend(episodes)
            proof_disagreement_metrics.extend(proof_episodes)
            print_progress(index, len(tasks), task)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            futures = {executor.submit(run_task, task): task for task in tasks}
            completed = 0
            for future in as_completed(futures):
                boundaries, episodes, proof_episodes = future.result()
                boundary_metrics.extend(boundaries)
                episode_metrics.extend(episodes)
                proof_disagreement_metrics.extend(proof_episodes)
                completed += 1
                print_progress(completed, len(tasks), futures[future])

    write_outputs(
        args.out_dir,
        args,
        profiles,
        pool_shares,
        boundary_metrics,
        episode_metrics,
        proof_disagreement_metrics,
    )
    print(f"Wrote V2.1 disagreement persistence report to {args.out_dir / 'report.md'}")
    return 0


class PersistenceSimulator:
    def __init__(self, args: argparse.Namespace, profile: RelayProfile, pool_share: float, seed: int, replication: int):
        self.args = args
        self.profile = profile
        self.pool_share = pool_share
        self.replication = replication
        self.rng = random.Random(seed)
        self.reserve_limit = int(math.ceil(args.shared_slots * args.reserve_multiplier))
        self.hashrate = self._build_hashrate_distribution()
        self.graph = build_peer_graph(args.node_count, args.peer_degree, self.rng)
        self.hops = all_pairs_hops(self.graph)
        self.next_proof_id = 1
        common = self._bootstrap_reserve()
        self.work_sets: list[dict[int, Proof]] = [dict(common) for _ in range(args.node_count)]
        initial = top_proofs(common.values(), args.shared_slots)
        self.active_snapshots: list[tuple[int, ...]] = [tuple(proof.proof_id for proof in initial) for _ in range(args.node_count)]
        self.proofs: dict[int, Proof] = dict(common)

    def run(self) -> tuple[list[BoundaryMetric], list[EpisodeMetric], list[ProofDisagreementMetric]]:
        boundaries: list[BoundaryMetric] = []
        episodes: list[EpisodeMetric] = []
        proof_episodes: list[ProofDisagreementMetric] = []
        active_proof_disagreements: dict[int, int] = {}
        episode_start: int | None = None
        episode_grid_blocks = 0
        episode_max_unique = 0
        episode_max_proof_diff = 0.0
        episode_max_recipient_diff = 0.0

        for height in range(1, self.args.blocks + 1):
            before = list(self.active_snapshots)
            before_summary = summarize_snapshots(before, self.proofs)
            is_gridpool_block = self.pool_share > 0.0 and self.rng.random() < self.pool_share
            finder = weighted_choice(self.rng, self.hashrate) if is_gridpool_block else None
            paid_snapshot = before[finder] if finder is not None else tuple()
            paid_ids = set(paid_snapshot)
            modal_before = before_summary["modal_snapshot"]
            paid_proof_diff = proof_slot_difference(paid_snapshot, modal_before) if finder is not None else 0
            paid_recipient_diff = recipient_slot_difference(paid_snapshot, modal_before, self.proofs) if finder is not None else 0

            block_start = (height - 1) * self.args.block_interval_seconds
            block_end = height * self.args.block_interval_seconds
            generated, relevant = self._generate_and_deliver_shares(height, block_start, block_end)

            if is_gridpool_block:
                block_proof = self._make_block_proof(height, finder)
                self.proofs[block_proof.proof_id] = block_proof
                for node_id in range(self.args.node_count):
                    self.work_sets[node_id][block_proof.proof_id] = block_proof
                    for proof_id in paid_ids:
                        self.work_sets[node_id].pop(proof_id, None)

            for node_id in range(self.args.node_count):
                self.work_sets[node_id] = retain_top_dict(self.work_sets[node_id], self.reserve_limit)
                self.active_snapshots[node_id] = tuple(
                    proof.proof_id for proof in top_proofs(self.work_sets[node_id].values(), self.args.shared_slots)
                )

            after_summary = summarize_snapshots(self.active_snapshots, self.proofs)
            divergent_after = after_summary["unique_snapshots"] > 1
            proof_presence = Counter(
                proof_id for snapshot in self.active_snapshots for proof_id in set(snapshot)
            )
            disputed_proofs = {
                proof_id
                for proof_id, presence_count in proof_presence.items()
                if 0 < presence_count < self.args.node_count
            }
            for proof_id in set(active_proof_disagreements) - disputed_proofs:
                started = active_proof_disagreements.pop(proof_id)
                proof = self.proofs.get(proof_id)
                proof_episodes.append(
                    ProofDisagreementMetric(
                        profile=self.profile.label,
                        pool_network_share=self.pool_share,
                        replication=self.replication,
                        proof_id=proof_id,
                        miner_id=proof.miner_id if proof is not None else -1,
                        started_at_height=started,
                        ended_at_height=height,
                        duration_boundaries=max(1, height - started),
                        resolution="paid" if proof_id in paid_ids else "displaced_or_converged",
                        censored_at_end=False,
                    )
                )
            for proof_id in disputed_proofs - set(active_proof_disagreements):
                active_proof_disagreements[proof_id] = height
            boundaries.append(
                BoundaryMetric(
                    profile=self.profile.label,
                    pool_network_share=self.pool_share,
                    replication=self.replication,
                    block_height=height,
                    gridpool_block=is_gridpool_block,
                    active_divergent_before_payment=before_summary["unique_snapshots"] > 1,
                    unique_active_snapshots_before_payment=before_summary["unique_snapshots"],
                    paid_snapshot_differs_from_modal=bool(finder is not None and paid_snapshot != modal_before),
                    paid_proof_slots_different_from_modal=paid_proof_diff,
                    paid_recipient_slots_reallocated=paid_recipient_diff,
                    active_divergent_after_boundary=divergent_after,
                    unique_active_snapshots_after_boundary=after_summary["unique_snapshots"],
                    mean_proof_slots_different_from_modal=after_summary["mean_proof_diff"],
                    mean_recipient_slots_reallocated_from_modal=after_summary["mean_recipient_diff"],
                    all_nodes_on_modal_snapshot=after_summary["modal_count"],
                    generated_shares=generated,
                    reserve_relevant_shares=relevant,
                )
            )

            # Proof details are only needed while at least one node retains the
            # proof. This keeps long, high-pool-share runs memory bounded.
            retained_ids = set().union(*(work_set.keys() for work_set in self.work_sets))
            self.proofs = {proof_id: self.proofs[proof_id] for proof_id in retained_ids}

            if episode_start is not None and is_gridpool_block and before_summary["unique_snapshots"] > 1:
                episode_grid_blocks += 1
            if divergent_after:
                if episode_start is None:
                    episode_start = height
                    episode_grid_blocks = 0
                    episode_max_unique = 0
                    episode_max_proof_diff = 0.0
                    episode_max_recipient_diff = 0.0
                episode_max_unique = max(episode_max_unique, after_summary["unique_snapshots"])
                episode_max_proof_diff = max(episode_max_proof_diff, after_summary["mean_proof_diff"])
                episode_max_recipient_diff = max(episode_max_recipient_diff, after_summary["mean_recipient_diff"])
            elif episode_start is not None:
                episodes.append(
                    EpisodeMetric(
                        profile=self.profile.label,
                        pool_network_share=self.pool_share,
                        replication=self.replication,
                        started_at_height=episode_start,
                        ended_at_height=height,
                        duration_boundaries=max(1, height - episode_start),
                        gridpool_blocks_during_episode=episode_grid_blocks,
                        max_unique_snapshots=episode_max_unique,
                        max_mean_proof_slots_different_from_modal=episode_max_proof_diff,
                        max_mean_recipient_slots_reallocated_from_modal=episode_max_recipient_diff,
                        censored_at_end=False,
                    )
                )
                episode_start = None

        if episode_start is not None:
            episodes.append(
                EpisodeMetric(
                    profile=self.profile.label,
                    pool_network_share=self.pool_share,
                    replication=self.replication,
                    started_at_height=episode_start,
                    ended_at_height=None,
                    duration_boundaries=self.args.blocks - episode_start + 1,
                    gridpool_blocks_during_episode=episode_grid_blocks,
                    max_unique_snapshots=episode_max_unique,
                    max_mean_proof_slots_different_from_modal=episode_max_proof_diff,
                    max_mean_recipient_slots_reallocated_from_modal=episode_max_recipient_diff,
                    censored_at_end=True,
                )
            )
        for proof_id, started in active_proof_disagreements.items():
            proof = self.proofs.get(proof_id)
            proof_episodes.append(
                ProofDisagreementMetric(
                    profile=self.profile.label,
                    pool_network_share=self.pool_share,
                    replication=self.replication,
                    proof_id=proof_id,
                    miner_id=proof.miner_id if proof is not None else -1,
                    started_at_height=started,
                    ended_at_height=None,
                    duration_boundaries=self.args.blocks - started + 1,
                    resolution="censored_at_end",
                    censored_at_end=True,
                )
            )
        return boundaries, episodes, proof_episodes

    def _bootstrap_reserve(self) -> dict[int, Proof]:
        count = max(self.reserve_limit, int(math.ceil(self.reserve_limit * self.args.bootstrap_multiplier)))
        candidates: list[Proof] = []
        for _ in range(count):
            candidates.append(self._new_proof(0, weighted_choice(self.rng, self.hashrate)))
        return {proof.proof_id: proof for proof in top_proofs(candidates, self.reserve_limit)}

    def _generate_and_deliver_shares(self, parent_height: int, block_start: float, block_end: float) -> tuple[int, int]:
        count = sample_poisson(self.rng, self.args.shares_per_block)
        relevant = 0
        node_floors = [reserve_floor(work_set, self.reserve_limit) for work_set in self.work_sets]
        minimum_floor = min(node_floors)
        snapshot_times = [block_end + self._sample_block_notification_delay() for _ in range(self.args.node_count)]

        for _ in range(count):
            origin = weighted_choice(self.rng, self.hashrate)
            proof = self._new_proof(parent_height, origin)
            if proof.difficulty <= minimum_floor:
                continue
            relevant += 1
            self.proofs[proof.proof_id] = proof
            found_at = block_start + self.rng.random() * self.args.block_interval_seconds
            for node_id in range(self.args.node_count):
                if proof.difficulty <= node_floors[node_id]:
                    continue
                if found_at + self._sample_path_delay(origin, node_id) <= snapshot_times[node_id]:
                    self.work_sets[node_id][proof.proof_id] = proof
        return count, relevant

    def _new_proof(self, parent_height: int, miner_id: int, difficulty: float | None = None) -> Proof:
        proof = Proof(
            proof_id=self.next_proof_id,
            miner_id=miner_id,
            difficulty=difficulty if difficulty is not None else sample_pareto_difficulty(self.rng, self.args.admission_floor),
            parent_height=parent_height,
        )
        self.next_proof_id += 1
        return proof

    def _make_block_proof(self, parent_height: int, finder: int) -> Proof:
        # With a fixed relay share cadence, the normalized Bitcoin target scales
        # inversely with GridPool's network share. Condition on exceeding it.
        network_difficulty = self.args.shares_per_block * self.args.admission_floor / self.pool_share
        difficulty = network_difficulty / max(self.rng.random(), 1e-15)
        return self._new_proof(parent_height, finder, difficulty)

    def _build_hashrate_distribution(self) -> list[float]:
        weights = [math.exp(self.rng.gauss(0.0, self.args.hashrate_sigma)) for _ in range(self.args.node_count)]
        total = sum(weights)
        return [weight / total for weight in weights]

    def _sample_path_delay(self, origin: int, destination: int) -> float:
        delay_ms = 0.0
        for _ in range(max(0, self.hops[origin][destination])):
            delay_ms += max(1.0, self.rng.gauss(self.profile.share_mean_ms, self.profile.share_jitter_ms))
        if self.profile.fallback_probability > 0 and self.rng.random() < self.profile.fallback_probability:
            delay_ms += self.profile.fallback_delay_ms
        return delay_ms / 1000.0

    def _sample_block_notification_delay(self) -> float:
        return max(0.001, self.rng.gauss(self.profile.block_mean_ms, self.profile.block_jitter_ms) / 1000.0)


def run_task(task: Task) -> tuple[list[BoundaryMetric], list[EpisodeMetric], list[ProofDisagreementMetric]]:
    args_dict = dict(task.args_dict)
    args_dict["out_dir"] = Path(args_dict["out_dir"])
    if args_dict.get("profiles_json"):
        args_dict["profiles_json"] = Path(args_dict["profiles_json"])
    args = argparse.Namespace(**args_dict)
    profile = RelayProfile(**task.profile_dict)
    return PersistenceSimulator(args, profile, task.pool_network_share, task.seed, task.replication).run()


def load_profiles(args: argparse.Namespace) -> list[RelayProfile]:
    if args.profiles_json:
        return relay_profiles_from_config(json.loads(args.profiles_json.read_text(encoding="utf-8")))
    return relay_profiles_from_config(
        {
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
    )


def summarize_snapshots(snapshots: list[tuple[int, ...]], proofs: dict[int, Proof]) -> dict[str, Any]:
    counts = Counter(snapshots)
    modal_snapshot, modal_count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    proof_diffs = [proof_slot_difference(snapshot, modal_snapshot) for snapshot in snapshots]
    recipient_diffs = [recipient_slot_difference(snapshot, modal_snapshot, proofs) for snapshot in snapshots]
    return {
        "unique_snapshots": len(counts),
        "modal_snapshot": modal_snapshot,
        "modal_count": modal_count,
        "mean_proof_diff": mean(proof_diffs),
        "mean_recipient_diff": mean(recipient_diffs),
    }


def proof_slot_difference(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    return max(len(set(left) - set(right)), len(set(right) - set(left)))


def recipient_slot_difference(left: tuple[int, ...], right: tuple[int, ...], proofs: dict[int, Proof]) -> int:
    left_counts = Counter(proofs[proof_id].miner_id for proof_id in left if proof_id in proofs)
    right_counts = Counter(proofs[proof_id].miner_id for proof_id in right if proof_id in proofs)
    return sum(abs(left_counts[key] - right_counts[key]) for key in set(left_counts) | set(right_counts)) // 2


def top_proofs(proofs: Any, limit: int) -> list[Proof]:
    return sorted(proofs, key=lambda proof: (-proof.difficulty, proof.proof_id))[:limit]


def retain_top_dict(proofs: dict[int, Proof], limit: int) -> dict[int, Proof]:
    return {proof.proof_id: proof for proof in top_proofs(proofs.values(), limit)}


def reserve_floor(proofs: dict[int, Proof], limit: int) -> float:
    if len(proofs) < limit:
        return 0.0
    return min(proof.difficulty for proof in proofs.values())


def weighted_choice(rng: random.Random, weights: list[float]) -> int:
    marker = rng.random()
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if marker <= cumulative:
            return index
    return len(weights) - 1


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


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


def print_progress(completed: int, total: int, task: Task) -> None:
    print(
        "[v2.1-persistence] "
        f"task={completed}/{total} profile={task.profile_dict['label']} "
        f"pool_share={task.pool_network_share:g} replication={task.replication + 1} done",
        flush=True,
    )


def write_outputs(
    out_dir: Path,
    args: argparse.Namespace,
    profiles: list[RelayProfile],
    pool_shares: list[float],
    boundaries: list[BoundaryMetric],
    episodes: list[EpisodeMetric],
    proof_episodes: list[ProofDisagreementMetric],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dataclass_csv(out_dir / "boundary_metrics.csv", boundaries, BoundaryMetric)
    write_dataclass_csv(out_dir / "disagreement_episodes.csv", episodes, EpisodeMetric)
    write_dataclass_csv(out_dir / "proof_disagreement_lifetimes.csv", proof_episodes, ProofDisagreementMetric)
    aggregate = aggregate_metrics(boundaries, episodes, proof_episodes)
    hazard_projection = project_no_payment_episode_hazard(boundaries, proof_episodes)
    summary = {
        "scenario": {
            "blocks": args.blocks,
            "replications": args.replications,
            "node_count": args.node_count,
            "peer_degree": args.peer_degree,
            "shared_slots": args.shared_slots,
            "reserve_limit": int(math.ceil(args.shared_slots * args.reserve_multiplier)),
            "shares_per_block": args.shares_per_block,
            "pool_network_shares": pool_shares,
            "relay_profiles": [asdict(profile) for profile in profiles],
            "seed": args.seed,
        },
        "aggregate": aggregate,
        "no_payment_episode_hazard_projection": hazard_projection,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_report(out_dir / "report.md", summary)
    write_profile_svg(
        out_dir / "payment_recipient_change_by_pool_share.svg",
        aggregate,
        value_key="gridpool_block_recipient_change_rate",
        title="GridPool payments with recipient differences",
        y_label="Share of GridPool blocks",
        y_percent=True,
    )
    write_profile_svg(
        out_dir / "proof_disagreement_duration_by_pool_share.svg",
        aggregate,
        value_key="mean_proof_disagreement_duration_boundaries",
        title="Mean disputed-proof lifetime",
        y_label="Bitcoin-block boundaries",
        y_percent=False,
    )


def write_dataclass_csv(path: Path, rows: list[Any], row_type: type) -> None:
    fields = list(row_type.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def aggregate_metrics(
    boundaries: list[BoundaryMetric],
    episodes: list[EpisodeMetric],
    proof_episodes: list[ProofDisagreementMetric],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    keys = sorted({(row.profile, row.pool_network_share) for row in boundaries})
    for profile, pool_share in keys:
        rows = [row for row in boundaries if row.profile == profile and row.pool_network_share == pool_share]
        episode_rows = [row for row in episodes if row.profile == profile and row.pool_network_share == pool_share]
        completed_episodes = [row for row in episode_rows if not row.censored_at_end]
        proof_rows = [
            row
            for row in proof_episodes
            if row.profile == profile and row.pool_network_share == pool_share
        ]
        completed_proof_rows = [row for row in proof_rows if not row.censored_at_end]
        grid_blocks = [row for row in rows if row.gridpool_block]
        divergent_grid_blocks = [row for row in grid_blocks if row.active_divergent_before_payment]
        changed_grid_blocks = [row for row in grid_blocks if row.paid_recipient_slots_reallocated > 0]
        divergence_low, divergence_high = wilson_interval(
            sum(row.active_divergent_after_boundary for row in rows), len(rows)
        )
        disagreement_low, disagreement_high = wilson_interval(len(divergent_grid_blocks), len(grid_blocks))
        recipient_low, recipient_high = wilson_interval(len(changed_grid_blocks), len(grid_blocks))
        output.append(
            {
                "profile": profile,
                "pool_network_share": pool_share,
                "boundaries": len(rows),
                "post_boundary_divergence_rate": mean(row.active_divergent_after_boundary for row in rows),
                "post_boundary_divergence_ci95_low": divergence_low,
                "post_boundary_divergence_ci95_high": divergence_high,
                "mean_unique_snapshots": mean(row.unique_active_snapshots_after_boundary for row in rows),
                "mean_proof_slots_different_from_modal": mean(row.mean_proof_slots_different_from_modal for row in rows),
                "mean_recipient_slots_reallocated_from_modal": mean(
                    row.mean_recipient_slots_reallocated_from_modal for row in rows
                ),
                "episodes": len(episode_rows),
                "completed_episodes": len(completed_episodes),
                "censored_episodes": len(episode_rows) - len(completed_episodes),
                "mean_episode_duration_boundaries": mean(row.duration_boundaries for row in completed_episodes)
                if completed_episodes
                else None,
                "p95_episode_duration_boundaries": percentile(
                    [row.duration_boundaries for row in completed_episodes], 95
                )
                if completed_episodes
                else None,
                "max_completed_episode_duration_boundaries": max(
                    (row.duration_boundaries for row in completed_episodes), default=None
                ),
                "proof_disagreements": len(proof_rows),
                "completed_proof_disagreements": len(completed_proof_rows),
                "censored_proof_disagreements": len(proof_rows) - len(completed_proof_rows),
                "mean_proof_disagreement_duration_boundaries": mean(
                    row.duration_boundaries for row in completed_proof_rows
                )
                if completed_proof_rows
                else None,
                "p95_proof_disagreement_duration_boundaries": percentile(
                    [row.duration_boundaries for row in completed_proof_rows], 95
                )
                if completed_proof_rows
                else None,
                "gridpool_blocks": len(grid_blocks),
                "gridpool_blocks_during_disagreement": len(divergent_grid_blocks),
                "gridpool_block_disagreement_rate": len(divergent_grid_blocks) / len(grid_blocks) if grid_blocks else None,
                "gridpool_block_disagreement_ci95_low": disagreement_low,
                "gridpool_block_disagreement_ci95_high": disagreement_high,
                "gridpool_blocks_with_recipient_change": len(changed_grid_blocks),
                "gridpool_block_recipient_change_rate": len(changed_grid_blocks) / len(grid_blocks) if grid_blocks else None,
                "gridpool_block_recipient_change_ci95_low": recipient_low,
                "gridpool_block_recipient_change_ci95_high": recipient_high,
                "mean_recipient_slots_reallocated_when_changed": mean(
                    row.paid_recipient_slots_reallocated for row in changed_grid_blocks
                )
                if changed_grid_blocks
                else 0.0,
                "p95_recipient_slots_reallocated_when_changed": percentile(
                    [row.paid_recipient_slots_reallocated for row in changed_grid_blocks], 95
                )
                if changed_grid_blocks
                else 0.0,
            }
        )
    return output


def write_report(path: Path, summary: dict[str, Any]) -> None:
    scenario = summary["scenario"]
    lines = [
        "# GridPool V2.1 Disagreement Persistence And Settlement",
        "",
        "Status: generated by `run_v21_disagreement_persistence.py`.",
        "",
        "## Scope",
        "",
        "This model extends the immediate-boundary latency model across later Bitcoin blocks. "
        "It tracks cutoff displacement, continuous disagreement episodes, and actual GridPool "
        "payments made from the finding node's active snapshot.",
        "",
        "A payment difference is reported in recipient-slot units. Replacing one proof with another "
        "proof from the same miner does not count as a changed payout recipient.",
        "",
        "## Scenario",
        "",
        "| Parameter | Value |",
        "| --- | ---: |",
    ]
    for key in ["blocks", "replications", "node_count", "peer_degree", "shared_slots", "reserve_limit", "shares_per_block", "seed"]:
        lines.append(f"| `{key}` | `{scenario[key]}` |")
    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Relay | Pool Network Share | Boundary Divergence (95% CI) | Mean Global Episode | Mean Disputed-Proof Lifetime | P95 Proof Lifetime | GridPool Blocks | Blocks During Disagreement (95% CI) | Blocks Changing Recipient Slots (95% CI) | Mean Slots Reallocated When Changed |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["aggregate"]:
        lines.append(
            "| {profile} | {pool:.3%} | {div} | {duration} | {proof_duration} | {proof_p95} | {blocks} | {during} | {changed} | {slots:.3f} |".format(
                profile=row["profile"],
                pool=row["pool_network_share"],
                div=format_rate_ci(
                    row["post_boundary_divergence_rate"],
                    row["post_boundary_divergence_ci95_low"],
                    row["post_boundary_divergence_ci95_high"],
                ),
                duration=format_optional(row["mean_episode_duration_boundaries"], ".3f"),
                proof_duration=format_optional(row["mean_proof_disagreement_duration_boundaries"], ".3f"),
                proof_p95=format_optional(row["p95_proof_disagreement_duration_boundaries"], ".2f"),
                blocks=row["gridpool_blocks"],
                during=format_rate_ci(
                    row["gridpool_block_disagreement_rate"],
                    row["gridpool_block_disagreement_ci95_low"],
                    row["gridpool_block_disagreement_ci95_high"],
                ),
                changed=format_rate_ci(
                    row["gridpool_block_recipient_change_rate"],
                    row["gridpool_block_recipient_change_ci95_low"],
                    row["gridpool_block_recipient_change_ci95_high"],
                ),
                slots=row["mean_recipient_slots_reallocated_when_changed"],
            )
        )
    lines.extend(
        [
            "",
            "## Tiny-Team Payment Hazard Projection",
            "",
            "The no-payment baseline measures how long each individually disputed proof survives cutoff displacement without a GridPool payment. "
            "For each completed proof disagreement of length `L`, the probability that a team with Bitcoin-network share `q` finds at least one "
            "block before natural resolution is `1-(1-q)^L`. This avoids requiring millions of simulated Bitcoin blocks for tiny teams.",
            "",
            "| Relay | Projected Pool Network Share | Completed Baseline Proof Disagreements | Mean Probability Payment Precedes Natural Resolution |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in summary["no_payment_episode_hazard_projection"]:
        lines.append(
            f"| {row['profile']} | {row['projected_pool_network_share']:.5%} | {row['completed_baseline_episodes']} | "
            f"{format_optional(row['mean_payment_before_resolution_probability'], '.6%')} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Limits",
            "",
            "- This is a stylized proof-arrival and payout-lineage model, not runtime consensus code.",
            "- It assumes a validated GridPool block identifies the finding node's paid snapshot and all nodes remove exactly those proof IDs.",
            "- A finder paying a non-modal snapshot is not automatically invalid; the recipient-change metric quantifies the economic effect of the disagreement.",
            "- Relay-worthy share cadence is held fixed across pool sizes, representing vardiff-like normalization; normalized block-proof difficulty scales with pool network share.",
            "- It does not model invalid bundles, eclipse attacks, strategic withholding, or miner template incompatibility.",
            "- Very small pool-network-share variants need enough simulated Bitcoin blocks to observe a useful number of GridPool payments.",
            "- Relay profiles are synthetic until an explicitly labeled field-calibrated profile file is supplied.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_optional(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def project_no_payment_episode_hazard(
    boundaries: list[BoundaryMetric], proof_episodes: list[ProofDisagreementMetric]
) -> list[dict[str, Any]]:
    projected_pool_shares = [0.000001, 0.00001, 0.0001, 0.001, 0.01, 0.1]
    output: list[dict[str, Any]] = []
    profiles = sorted({row.profile for row in boundaries if row.pool_network_share == 0.0})
    for profile in profiles:
        baseline = [
            row
            for row in proof_episodes
            if row.profile == profile and row.pool_network_share == 0.0 and not row.censored_at_end
        ]
        for pool_share in projected_pool_shares:
            probabilities = [1.0 - (1.0 - pool_share) ** row.duration_boundaries for row in baseline]
            output.append(
                {
                    "profile": profile,
                    "projected_pool_network_share": pool_share,
                    "completed_baseline_episodes": len(baseline),
                    "mean_payment_before_resolution_probability": mean(probabilities) if probabilities else None,
                    "p95_payment_before_resolution_probability": percentile(probabilities, 95) if probabilities else None,
                }
            )
    return output


def format_rate_ci(value: float | None, low: float | None, high: float | None) -> str:
    if value is None or low is None or high is None:
        return "n/a"
    return f"{value:.4%} [{low:.4%}, {high:.4%}]"


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if trials <= 0:
        return None, None
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def write_profile_svg(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    title: str,
    y_label: str,
    y_percent: bool,
) -> None:
    usable = [
        row
        for row in rows
        if row[value_key] is not None and float(row["pool_network_share"]) > 0.0
    ]
    if not usable:
        return
    width, height = 1000, 620
    left, right, top, bottom = 110, 40, 80, 90
    chart_w, chart_h = width - left - right, height - top - bottom
    x_values = sorted({float(row["pool_network_share"]) for row in usable})
    y_max = max(float(row[value_key]) for row in usable) * 1.08
    y_max = max(y_max, 0.01 if y_percent else 1.0)
    colors = ["#12a594", "#f0a830", "#4aa3df", "#e06c75"]

    def x_pos(value: float) -> float:
        if len(x_values) == 1:
            return left + chart_w / 2
        return left + (math.log(value) - math.log(x_values[0])) / (
            math.log(x_values[-1]) - math.log(x_values[0])
        ) * chart_w

    def y_pos(value: float) -> float:
        return top + chart_h - value / y_max * chart_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1517"/>',
        f'<text x="{left}" y="38" fill="#f4f0df" font-family="sans-serif" font-size="26" font-weight="700">{title}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = y_pos(value)
        label = f"{value:.1%}" if y_percent else f"{value:.1f}"
        parts.extend(
            [
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}" stroke="#274044"/>',
                f'<text x="{left - 12}" y="{y + 5:.2f}" text-anchor="end" fill="#a9bdba" font-family="sans-serif" font-size="14">{label}</text>',
            ]
        )
    for value in x_values:
        x = x_pos(value)
        parts.append(
            f'<text x="{x:.2f}" y="{top + chart_h + 25}" text-anchor="middle" fill="#a9bdba" font-family="sans-serif" font-size="14">{value:.2%}</text>'
        )
    profiles = sorted({row["profile"] for row in usable})
    for index, profile in enumerate(profiles):
        profile_rows = sorted(
            (row for row in usable if row["profile"] == profile),
            key=lambda row: row["pool_network_share"],
        )
        color = colors[index % len(colors)]
        points = " ".join(
            f"{x_pos(float(row['pool_network_share'])):.2f},{y_pos(float(row[value_key])):.2f}"
            for row in profile_rows
        )
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="4"/>')
        for row in profile_rows:
            parts.append(
                f'<circle cx="{x_pos(float(row["pool_network_share"])):.2f}" cy="{y_pos(float(row[value_key])):.2f}" r="5" fill="{color}"/>'
            )
        legend_x = left + index * 270
        parts.extend(
            [
                f'<line x1="{legend_x}" y1="{height - 25}" x2="{legend_x + 35}" y2="{height - 25}" stroke="{color}" stroke-width="4"/>',
                f'<text x="{legend_x + 43}" y="{height - 20}" fill="#d8e3df" font-family="sans-serif" font-size="14">{profile}</text>',
            ]
        )
    parts.extend(
        [
            f'<text x="{left + chart_w / 2}" y="{height - 52}" text-anchor="middle" fill="#d8e3df" font-family="sans-serif" font-size="16">GridPool share of Bitcoin hashrate (log scale)</text>',
            f'<text x="26" y="{top + chart_h / 2}" transform="rotate(-90 26 {top + chart_h / 2})" text-anchor="middle" fill="#d8e3df" font-family="sans-serif" font-size="16">{y_label}</text>',
            '</svg>',
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

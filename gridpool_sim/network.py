from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
import random
from statistics import mean
from typing import Any

from .engine import sample_pareto_difficulty, sample_poisson


@dataclass(frozen=True)
class RelayProfile:
    label: str
    share_mean_ms: float
    share_jitter_ms: float
    block_mean_ms: float
    block_jitter_ms: float
    payload_bytes: int
    fallback_delay_ms: float = 0.0
    fallback_probability: float = 0.0


@dataclass
class NetworkShare:
    proof_id: int
    origin_node: int
    difficulty: float
    found_at: float
    arrival_times: list[float]


@dataclass
class LatencyBlockMetric:
    block_height: int
    unique_snapshots: int
    nodes_on_canonical: int
    hashrate_on_canonical: float
    convergence_delay_seconds: float
    p95_node_lag_seconds: float


@dataclass
class LatencyRunResult:
    label: str
    seed: int
    blocks: int
    node_count: int
    peer_degree: int
    split_blocks: int
    mean_unique_snapshots: float
    mean_nodes_on_canonical: float
    mean_hashrate_on_canonical: float
    p50_convergence_seconds: float
    p95_convergence_seconds: float
    p99_convergence_seconds: float
    p95_node_lag_seconds: float
    estimated_payload_mb: float
    metrics: list[LatencyBlockMetric] = field(default_factory=list)


class NetworkLatencySimulator:
    """Approximate GridPool snapshot split model.

    The model tracks bounded per-node Work Sets and a canonical global Work Set.
    It asks whether nodes have received the same top proofs by the time their
    Bitcoin-block notification arrives and a payout snapshot is built.
    """

    def __init__(self, config: dict[str, Any], profile: RelayProfile, seed: int):
        self.config = config
        self.profile = profile
        self.seed = seed
        self.rng = random.Random(seed)

        self.blocks = int(config["blocks"])
        self.node_count = int(config["node_count"])
        self.peer_degree = int(config["peer_degree"])
        self.block_interval_seconds = float(config.get("block_interval_seconds", 600.0))
        self.shared_slots = int(config.get("shared_slots", 299))
        self.reserve_limit = int(config.get("reserve_limit", math.ceil(self.shared_slots * float(config.get("reserve_multiplier", 3.0)))))
        self.shares_per_block = float(config["shares_per_network_block_at_full_team"])
        self.admission_floor = float(config.get("admission_floor", 1.0))

        self.hashrate_by_node = self._build_hashrate_distribution()
        self.graph = build_peer_graph(self.node_count, self.peer_degree, self.rng)
        self.hops = all_pairs_hops(self.graph)

        self.global_work_set: list[NetworkShare] = []
        self.node_work_sets: list[list[NetworkShare]] = [[] for _ in range(self.node_count)]
        self.pending: list[list[tuple[float, int, NetworkShare]]] = [[] for _ in range(self.node_count)]
        self.next_proof_id = 1
        self.total_generated_shares = 0
        self.total_relayed_shares = 0

    def run(self) -> LatencyRunResult:
        metrics: list[LatencyBlockMetric] = []

        for block_height in range(1, self.blocks + 1):
            block_start = (block_height - 1) * self.block_interval_seconds
            block_end = block_height * self.block_interval_seconds
            self._generate_block_shares(block_start)

            snapshot_times = [
                block_end + self._sample_block_notification_delay()
                for _ in range(self.node_count)
            ]

            signatures: list[tuple[int, ...]] = []
            for node_id, snapshot_time in enumerate(snapshot_times):
                self._ingest_pending(node_id, snapshot_time)
                signatures.append(snapshot_signature(self.node_work_sets[node_id], self.shared_slots))

            canonical = list(self.global_work_set[: self.shared_slots])
            canonical_signature = tuple(share.proof_id for share in canonical)
            nodes_on_canonical = sum(1 for signature in signatures if signature == canonical_signature)
            hashrate_on_canonical = sum(
                self.hashrate_by_node[node_id]
                for node_id, signature in enumerate(signatures)
                if signature == canonical_signature
            )

            node_lags = []
            for node_id in range(self.node_count):
                if not canonical:
                    node_lags.append(0.0)
                    continue
                last_required_arrival = max(share.arrival_times[node_id] for share in canonical)
                node_lags.append(max(0.0, last_required_arrival - snapshot_times[node_id]))

            convergence_delay = max(node_lags) if node_lags else 0.0
            metrics.append(
                LatencyBlockMetric(
                    block_height=block_height,
                    unique_snapshots=len(set(signatures)),
                    nodes_on_canonical=nodes_on_canonical,
                    hashrate_on_canonical=hashrate_on_canonical,
                    convergence_delay_seconds=convergence_delay,
                    p95_node_lag_seconds=percentile(node_lags, 95),
                )
            )

        convergence = [m.convergence_delay_seconds for m in metrics]
        return LatencyRunResult(
            label=self.profile.label,
            seed=self.seed,
            blocks=self.blocks,
            node_count=self.node_count,
            peer_degree=self.peer_degree,
            split_blocks=sum(1 for m in metrics if m.unique_snapshots > 1),
            mean_unique_snapshots=mean(m.unique_snapshots for m in metrics),
            mean_nodes_on_canonical=mean(m.nodes_on_canonical for m in metrics),
            mean_hashrate_on_canonical=mean(m.hashrate_on_canonical for m in metrics),
            p50_convergence_seconds=percentile(convergence, 50),
            p95_convergence_seconds=percentile(convergence, 95),
            p99_convergence_seconds=percentile(convergence, 99),
            p95_node_lag_seconds=percentile([m.p95_node_lag_seconds for m in metrics], 95),
            estimated_payload_mb=(self.total_relayed_shares * self.node_count * self.profile.payload_bytes) / 1_000_000,
            metrics=metrics,
        )

    def _build_hashrate_distribution(self) -> list[float]:
        configured = self.config.get("node_hashrate_weights")
        if configured:
            weights = [float(value) for value in configured]
            if len(weights) != self.node_count:
                raise ValueError("node_hashrate_weights length must equal node_count")
        else:
            sigma = float(self.config.get("hashrate_lognormal_sigma", 0.9))
            weights = [math.exp(self.rng.gauss(0.0, sigma)) for _ in range(self.node_count)]

        total = sum(weights)
        if total <= 0:
            raise ValueError("Node hashrate weights must sum to a positive value")
        return [weight / total for weight in weights]

    def _generate_block_shares(self, block_start: float) -> None:
        count = sample_poisson(self.rng, self.shares_per_block)
        block_shares: list[NetworkShare] = []
        for _ in range(count):
            found_at = block_start + (self.rng.random() * self.block_interval_seconds)
            origin = weighted_choice(self.rng, self.hashrate_by_node)
            share = NetworkShare(
                proof_id=self.next_proof_id,
                origin_node=origin,
                difficulty=sample_pareto_difficulty(self.rng, self.admission_floor),
                found_at=found_at,
                arrival_times=[],
            )
            self.next_proof_id += 1
            self.total_generated_shares += 1
            block_shares.append(share)
        self._insert_global_many(block_shares)
        relayable_ids = {share.proof_id for share in self.global_work_set}
        for share in block_shares:
            if share.proof_id not in relayable_ids:
                continue
            self.total_relayed_shares += 1
            share.arrival_times = self._arrival_times_for_share(share.origin_node, share.found_at)
            for node_id, arrival_time in enumerate(share.arrival_times):
                heapq.heappush(self.pending[node_id], (arrival_time, share.proof_id, share))

    def _arrival_times_for_share(self, origin: int, found_at: float) -> list[float]:
        arrivals = []
        for node_id in range(self.node_count):
            hop_count = self.hops[origin][node_id]
            if hop_count < 0:
                arrivals.append(float("inf"))
                continue
            delay = 0.0
            for _ in range(hop_count):
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

    def _insert_global_many(self, shares: list[NetworkShare]) -> None:
        if not shares:
            return
        self.global_work_set.extend(shares)
        self.global_work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
        if len(self.global_work_set) > self.reserve_limit:
            del self.global_work_set[self.reserve_limit :]

    def _ingest_pending(self, node_id: int, now: float) -> None:
        work_set = self.node_work_sets[node_id]
        changed = False
        while self.pending[node_id] and self.pending[node_id][0][0] <= now:
            _, _, share = heapq.heappop(self.pending[node_id])
            work_set.append(share)
            changed = True
        if changed:
            work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
            if len(work_set) > self.reserve_limit:
                del work_set[self.reserve_limit :]


def relay_profiles_from_config(config: dict[str, Any]) -> list[RelayProfile]:
    return [
        RelayProfile(
            label=item["label"],
            share_mean_ms=float(item["share_mean_ms"]),
            share_jitter_ms=float(item.get("share_jitter_ms", 0.0)),
            block_mean_ms=float(item.get("block_mean_ms", config.get("block_mean_ms", 500.0))),
            block_jitter_ms=float(item.get("block_jitter_ms", config.get("block_jitter_ms", 200.0))),
            payload_bytes=int(item.get("payload_bytes", 2000)),
            fallback_delay_ms=float(item.get("fallback_delay_ms", 0.0)),
            fallback_probability=float(item.get("fallback_probability", 0.0)),
        )
        for item in config["relay_profiles"]
    ]


def build_peer_graph(node_count: int, peer_degree: int, rng: random.Random) -> list[set[int]]:
    if peer_degree < 2:
        raise ValueError("peer_degree must be at least 2 for a connected graph")
    peer_degree = min(peer_degree, node_count - 1)
    graph = [set() for _ in range(node_count)]

    # Ring backbone guarantees connectivity.
    for node in range(node_count):
        connect(graph, node, (node + 1) % node_count)

    attempts = 0
    max_attempts = node_count * node_count * 20
    while min(len(peers) for peers in graph) < peer_degree and attempts < max_attempts:
        attempts += 1
        a = rng.randrange(node_count)
        b = rng.randrange(node_count)
        if a == b:
            continue
        if len(graph[a]) >= peer_degree or len(graph[b]) >= peer_degree:
            continue
        connect(graph, a, b)

    return graph


def connect(graph: list[set[int]], a: int, b: int) -> None:
    graph[a].add(b)
    graph[b].add(a)


def all_pairs_hops(graph: list[set[int]]) -> list[list[int]]:
    return [single_source_hops(graph, source) for source in range(len(graph))]


def single_source_hops(graph: list[set[int]], source: int) -> list[int]:
    hops = [-1] * len(graph)
    hops[source] = 0
    queue = [source]
    for node in queue:
        for peer in graph[node]:
            if hops[peer] >= 0:
                continue
            hops[peer] = hops[node] + 1
            queue.append(peer)
    return hops


def snapshot_signature(work_set: list[NetworkShare], shared_slots: int) -> tuple[int, ...]:
    return tuple(share.proof_id for share in work_set[:shared_slots])


def weighted_choice(rng: random.Random, weights: list[float]) -> int:
    marker = rng.random()
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if marker <= cumulative:
            return index
    return len(weights) - 1


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * (percent / 100.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from statistics import mean, pstdev
from typing import Any

from .stats import summarize


@dataclass(frozen=True)
class MinerConfig:
    miner_id: str
    hashrate: float


@dataclass
class ShareProof:
    proof_id: int
    miner_id: str
    difficulty: float
    mined_at_block: int
    mined_for_snapshot_id: int
    is_block_proof: bool = False


@dataclass
class MinerLedger:
    miner_id: str
    hashrate: float
    grid_shared_btc: float = 0.0
    grid_slot0_btc: float = 0.0
    external_btc: float = 0.0
    shared_slots_paid: int = 0
    shared_payout_events: int = 0
    slot0_payout_events: int = 0
    active_blocks: int = 0
    inactive_blocks: int = 0
    shares_submitted: int = 0
    block_finds: int = 0
    withheld_blocks: int = 0
    snapshot_slot_observations: int = 0
    first_grid_payout_block: int | None = None

    @property
    def total_btc(self) -> float:
        return self.grid_shared_btc + self.grid_slot0_btc + self.external_btc

    @property
    def grid_btc(self) -> float:
        return self.grid_shared_btc + self.grid_slot0_btc


@dataclass
class SimulationResult:
    label: str
    seed: int
    blocks: int
    pool_blocks: int
    snapshots: int
    final_work_set_count: int
    final_snapshot_count: int
    support_btc: float
    miners: dict[str, MinerLedger]
    metadata: dict[str, Any] = field(default_factory=dict)


class StrategyController:
    """Controls which miners are actively mining GridPool on each block."""

    def __init__(self, strategy: dict[str, Any], rng: random.Random):
        self.strategy = strategy or {"type": "always"}
        self.rng = rng
        self.inactive_until: dict[str, int] = {}

    def _applies_to_miner(self, miner_id: str, *, default_all: bool) -> bool:
        if self.strategy.get("apply_to") == "all":
            return True
        target_miners = self.strategy.get("target_miners")
        if target_miners is not None:
            return miner_id in {str(target) for target in target_miners}
        target = self.strategy.get("target_miner")
        if target is not None:
            return miner_id == str(target)
        return default_all

    def _snapshot_controlled_miners(
        self,
        active_snapshot: list[ShareProof],
        *,
        default_all: bool,
    ) -> list[str]:
        if self.strategy.get("apply_to") == "all":
            return sorted({proof.miner_id for proof in active_snapshot})
        target_miners = self.strategy.get("target_miners")
        if target_miners is not None:
            return sorted({str(target) for target in target_miners})
        target = self.strategy.get("target_miner")
        if target is not None:
            return [str(target)]
        if default_all:
            return sorted({proof.miner_id for proof in active_snapshot})
        return []

    def is_active(
        self,
        miner_id: str,
        block_height: int,
        active_snapshot: list[ShareProof],
        work_set: list[ShareProof],
    ) -> bool:
        strategy_type = self.strategy.get("type", "always")
        if strategy_type == "always":
            return True

        if strategy_type == "withhold_blocks":
            return True

        if strategy_type == "intermittent":
            uptime = float(self.strategy.get("uptime", 1.0))
            if not self._applies_to_miner(miner_id, default_all=True):
                return True
            return self.rng.random() < uptime

        if not self._applies_to_miner(miner_id, default_all=False):
            return True

        if strategy_type == "leave_when_snapshot_slots":
            min_slots = int(self.strategy.get("min_slots", 1))
            slots = sum(1 for proof in active_snapshot if proof.miner_id == miner_id)
            return slots < min_slots

        if strategy_type == "leave_when_reserve_proofs":
            min_proofs = int(self.strategy.get("min_proofs", 1))
            proofs = sum(1 for proof in work_set if proof.miner_id == miner_id)
            return proofs < min_proofs

        if strategy_type == "leave_for_blocks_after_snapshot_slots":
            until = self.inactive_until.get(miner_id, -1)
            return block_height >= until

        raise ValueError(f"Unknown strategy type: {strategy_type}")

    def should_publish_block(
        self,
        miner_id: str,
        active_snapshot: list[ShareProof],
    ) -> bool:
        strategy_type = self.strategy.get("type", "always")
        if strategy_type != "withhold_blocks":
            return True

        if not self._applies_to_miner(miner_id, default_all=True):
            return True

        condition = self.strategy.get("condition", "always")
        slots = sum(1 for proof in active_snapshot if proof.miner_id == miner_id)
        if condition == "always":
            return False
        if condition == "when_snapshot_slots_below":
            return slots >= int(self.strategy.get("threshold", 1))
        if condition == "when_snapshot_slots_at_least":
            return slots < int(self.strategy.get("threshold", 1))

        raise ValueError(f"Unknown withhold_blocks condition: {condition}")

    def after_snapshot(
        self,
        block_height: int,
        active_snapshot: list[ShareProof],
    ) -> None:
        strategy_type = self.strategy.get("type", "always")
        if strategy_type != "leave_for_blocks_after_snapshot_slots":
            return

        min_slots = int(self.strategy.get("min_slots", 1))
        duration = int(self.strategy.get("duration_blocks", 1))
        for miner_id in self._snapshot_controlled_miners(active_snapshot, default_all=False):
            slots = sum(1 for proof in active_snapshot if proof.miner_id == miner_id)
            if slots >= min_slots:
                self.inactive_until[miner_id] = max(
                    self.inactive_until.get(miner_id, -1),
                    block_height + duration,
                )


class GridPoolSimulator:
    def __init__(self, config: dict[str, Any], label: str, seed: int, strategy: dict[str, Any]):
        self.config = config
        self.label = label
        self.seed = seed
        self.rng = random.Random(seed)
        self.strategy = StrategyController(strategy, self.rng)
        self.miners = [MinerConfig(m["id"], float(m["hashrate"])) for m in config["miners"]]
        self.total_pool_hashrate = sum(m.hashrate for m in self.miners)
        if self.total_pool_hashrate <= 0:
            raise ValueError("Total pool hashrate must be positive")

        self.blocks = int(config["blocks"])
        self.pool_network_share = float(config["pool_network_share"])
        if not 0 < self.pool_network_share <= 1:
            raise ValueError("pool_network_share must be in (0, 1]")

        self.network_hashrate = self.total_pool_hashrate / self.pool_network_share
        self.shares_per_block_full_team = float(config["shares_per_network_block_at_full_team"])
        self.admission_floor = float(config.get("admission_floor", 1.0))
        self.network_difficulty = self.admission_floor * (
            self.shares_per_block_full_team / self.pool_network_share
        )

        self.total_slots = int(config.get("total_slots", 300))
        self.support_slot_enabled = bool(config.get("support_slot_enabled", False))
        self.shared_slots = int(config.get("shared_slots", self.total_slots - 1 - (1 if self.support_slot_enabled else 0)))
        self.reserve_multiplier = float(config.get("reserve_multiplier", 3.0))
        self.reserve_limit = int(config.get("reserve_limit", math.ceil(self.shared_slots * self.reserve_multiplier)))
        if self.shared_slots <= 0 or self.reserve_limit < self.shared_slots:
            raise ValueError("reserve_limit must be at least shared_slots")
        self.snapshot_policy = str(config.get("snapshot_policy", "paid_once_reserve"))
        if self.snapshot_policy not in {"paid_once_reserve", "clear_each_bitcoin_block"}:
            raise ValueError("snapshot_policy must be paid_once_reserve or clear_each_bitcoin_block")

        self.subsidy_btc = float(config.get("subsidy_btc", 3.125))
        self.fees_btc = float(config.get("fees_btc", 0.05))
        self.external_fee_rate = float(config.get("external_fee_rate", 0.0))
        self.external_payout_mode = str(config.get("external_payout_mode", "deterministic_fpps"))
        if self.external_payout_mode not in {"deterministic_fpps", "solo"}:
            raise ValueError("external_payout_mode must be deterministic_fpps or solo")
        self.slot_value_btc = self.subsidy_btc / self.total_slots

        self.work_set: list[ShareProof] = []
        self.active_snapshot: list[ShareProof] = []
        self.snapshot_id = 0
        self.next_proof_id = 1
        self.support_btc = 0.0
        self.pool_blocks = 0
        self.snapshots = 0
        self.activity_samples = 0
        self.inactive_snapshot_slots_sum = 0.0
        self.inactive_snapshot_fraction_sum = 0.0
        self.inactive_work_set_proofs_sum = 0.0
        self.inactive_work_set_fraction_sum = 0.0
        self.active_team_hashrate_share_sum = 0.0
        self.ledgers = {
            miner.miner_id: MinerLedger(miner.miner_id, miner.hashrate)
            for miner in self.miners
        }

    def run(self) -> SimulationResult:
        self._snapshot()
        self.strategy.after_snapshot(0, self.active_snapshot)

        for block_height in range(1, self.blocks + 1):
            active_by_miner = {
                miner.miner_id: self.strategy.is_active(
                    miner.miner_id,
                    block_height,
                    self.active_snapshot,
                    self.work_set,
                )
                for miner in self.miners
            }

            new_shares: list[ShareProof] = []
            block_candidates: list[ShareProof] = []

            for miner in self.miners:
                ledger = self.ledgers[miner.miner_id]
                if active_by_miner[miner.miner_id]:
                    ledger.active_blocks += 1
                    lam = self.shares_per_block_full_team * (miner.hashrate / self.total_pool_hashrate)
                    for _ in range(sample_poisson(self.rng, lam)):
                        share = self._new_share(miner.miner_id, block_height)
                        new_shares.append(share)
                        if share.is_block_proof:
                            block_candidates.append(share)
                        ledger.shares_submitted += 1
                else:
                    ledger.inactive_blocks += 1
                    ledger.external_btc += self._external_expected_btc(miner.hashrate)

            if new_shares:
                self._insert_shares(new_shares)

            if block_candidates:
                published_blocks = []
                for candidate in block_candidates:
                    if self.strategy.should_publish_block(candidate.miner_id, self.active_snapshot):
                        published_blocks.append(candidate)
                    else:
                        self.ledgers[candidate.miner_id].withheld_blocks += 1
                if published_blocks:
                    winning_block = max(published_blocks, key=lambda p: (p.difficulty, -p.proof_id))
                    self._pay_active_snapshot(winning_block, block_height)

            self._snapshot()
            self._record_activity_metrics(active_by_miner)
            self.strategy.after_snapshot(block_height, self.active_snapshot)

        return SimulationResult(
            label=self.label,
            seed=self.seed,
            blocks=self.blocks,
            pool_blocks=self.pool_blocks,
            snapshots=self.snapshots,
            final_work_set_count=len(self.work_set),
            final_snapshot_count=len(self.active_snapshot),
            support_btc=self.support_btc,
            miners=self.ledgers,
            metadata={
                "network_difficulty": self.network_difficulty,
                "pool_network_share": self.pool_network_share,
                "shares_per_network_block_at_full_team": self.shares_per_block_full_team,
                "shared_slots": self.shared_slots,
                "reserve_limit": self.reserve_limit,
                "snapshot_policy": self.snapshot_policy,
                "support_slot_enabled": self.support_slot_enabled,
                "external_payout_mode": self.external_payout_mode,
                "mean_inactive_snapshot_slots": safe_div(self.inactive_snapshot_slots_sum, self.activity_samples),
                "mean_inactive_snapshot_fraction": safe_div(self.inactive_snapshot_fraction_sum, self.activity_samples),
                "mean_inactive_work_set_proofs": safe_div(self.inactive_work_set_proofs_sum, self.activity_samples),
                "mean_inactive_work_set_fraction": safe_div(self.inactive_work_set_fraction_sum, self.activity_samples),
                "mean_active_team_hashrate_share": safe_div(self.active_team_hashrate_share_sum, self.activity_samples),
            },
        )

    def _new_share(self, miner_id: str, block_height: int) -> ShareProof:
        difficulty = sample_pareto_difficulty(self.rng, self.admission_floor)
        proof = ShareProof(
            proof_id=self.next_proof_id,
            miner_id=miner_id,
            difficulty=difficulty,
            mined_at_block=block_height,
            mined_for_snapshot_id=self.snapshot_id,
            is_block_proof=difficulty >= self.network_difficulty,
        )
        self.next_proof_id += 1
        return proof

    def _insert_shares(self, shares: list[ShareProof]) -> None:
        self.work_set.extend(shares)
        self.work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
        if len(self.work_set) > self.reserve_limit:
            del self.work_set[self.reserve_limit :]

    def _snapshot(self) -> None:
        self.work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
        self.active_snapshot = list(self.work_set[: self.shared_slots])
        self.snapshot_id += 1
        self.snapshots += 1
        for proof in self.active_snapshot:
            self.ledgers[proof.miner_id].snapshot_slot_observations += 1
        if self.snapshot_policy == "clear_each_bitcoin_block":
            self.work_set = []

    def _record_activity_metrics(self, active_by_miner: dict[str, bool]) -> None:
        self.activity_samples += 1
        inactive_snapshot_slots = sum(
            1 for proof in self.active_snapshot if not active_by_miner.get(proof.miner_id, True)
        )
        inactive_work_set_proofs = sum(
            1 for proof in self.work_set if not active_by_miner.get(proof.miner_id, True)
        )
        active_hashrate = sum(
            miner.hashrate for miner in self.miners if active_by_miner.get(miner.miner_id, True)
        )
        snapshot_count = len(self.active_snapshot)
        work_set_count = len(self.work_set)
        self.inactive_snapshot_slots_sum += inactive_snapshot_slots
        self.inactive_snapshot_fraction_sum += safe_div(inactive_snapshot_slots, snapshot_count)
        self.inactive_work_set_proofs_sum += inactive_work_set_proofs
        self.inactive_work_set_fraction_sum += safe_div(inactive_work_set_proofs, work_set_count)
        self.active_team_hashrate_share_sum += safe_div(active_hashrate, self.total_pool_hashrate)

    def _pay_active_snapshot(self, block_proof: ShareProof, block_height: int) -> None:
        self.pool_blocks += 1
        finder = self.ledgers[block_proof.miner_id]
        finder.block_finds += 1

        support_slots = 1 if self.support_slot_enabled else 0
        shared_outputs = len(self.active_snapshot)
        support_value = self.slot_value_btc if self.support_slot_enabled else 0.0
        slot0_value = self.subsidy_btc - (self.slot_value_btc * shared_outputs) - support_value + self.fees_btc

        finder.grid_slot0_btc += slot0_value
        finder.slot0_payout_events += 1
        if finder.first_grid_payout_block is None:
            finder.first_grid_payout_block = block_height

        if self.support_slot_enabled:
            self.support_btc += support_value

        paid_ids = set()
        shared_slots_by_miner: dict[str, int] = {}
        for proof in self.active_snapshot:
            ledger = self.ledgers[proof.miner_id]
            ledger.grid_shared_btc += self.slot_value_btc
            ledger.shared_slots_paid += 1
            shared_slots_by_miner[proof.miner_id] = shared_slots_by_miner.get(proof.miner_id, 0) + 1
            if ledger.first_grid_payout_block is None:
                ledger.first_grid_payout_block = block_height
            paid_ids.add(proof.proof_id)

        for miner_id in shared_slots_by_miner:
            self.ledgers[miner_id].shared_payout_events += 1

        if paid_ids:
            self.work_set = [proof for proof in self.work_set if proof.proof_id not in paid_ids]

    def _external_expected_btc(self, hashrate: float) -> float:
        gross = (hashrate / self.network_hashrate) * (self.subsidy_btc + self.fees_btc)
        net = gross * (1.0 - self.external_fee_rate)
        if self.external_payout_mode == "deterministic_fpps":
            return net

        # Solo outside mining has the same expected value, but leaves the miner
        # exposed to block-finding variance instead of an FPPS-like counterparty.
        if self.rng.random() < (hashrate / self.network_hashrate):
            return (self.subsidy_btc + self.fees_btc) * (1.0 - self.external_fee_rate)
        return 0.0


def sample_pareto_difficulty(rng: random.Random, floor: float) -> float:
    # For proof-of-work, P(D >= x | D >= floor) = floor / x.
    u = max(rng.random(), 1e-15)
    return floor / u


def sample_poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30.0:
        threshold = math.exp(-lam)
        k = 0
        product = 1.0
        while product > threshold:
            k += 1
            product *= rng.random()
        return k - 1

    # Normal approximation is adequate for the first research pass and avoids
    # adding a NumPy dependency. Scenario reports should note this assumption.
    return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def aggregate_results(results: list[SimulationResult]) -> dict[str, Any]:
    labels = sorted({result.label for result in results})
    summaries: dict[str, Any] = {}
    for label in labels:
        label_results = [result for result in results if result.label == label]
        miner_ids = sorted(label_results[0].miners)
        miner_summaries = {}
        for miner_id in miner_ids:
            total = [r.miners[miner_id].total_btc for r in label_results]
            grid = [r.miners[miner_id].grid_btc for r in label_results]
            external = [r.miners[miner_id].external_btc for r in label_results]
            blocks = [r.miners[miner_id].block_finds for r in label_results]
            withheld = [r.miners[miner_id].withheld_blocks for r in label_results]
            active_blocks = [r.miners[miner_id].active_blocks for r in label_results]
            slot_obs = [r.miners[miner_id].snapshot_slot_observations for r in label_results]
            shared_slots_paid = [r.miners[miner_id].shared_slots_paid for r in label_results]
            shared_payout_events = [r.miners[miner_id].shared_payout_events for r in label_results]
            slot0_payout_events = [r.miners[miner_id].slot0_payout_events for r in label_results]
            total_summary = summarize(total)
            miner_summaries[miner_id] = {
                "mean_total_btc": total_summary["mean"],
                "std_total_btc": total_summary["std_population"],
                "sample_std_total_btc": total_summary["std_sample"],
                "stderr_total_btc": total_summary["stderr"],
                "ci95_total_btc_low": total_summary["ci95_low"],
                "ci95_total_btc_high": total_summary["ci95_high"],
                "mean_grid_btc": mean(grid),
                "mean_external_btc": mean(external),
                "mean_shared_slots_paid": mean(shared_slots_paid),
                "mean_shared_payout_events": mean(shared_payout_events),
                "mean_slot0_payout_events": mean(slot0_payout_events),
                "mean_block_finds": mean(blocks),
                "mean_withheld_blocks": mean(withheld),
                "mean_active_blocks": mean(active_blocks),
                "mean_snapshot_slot_observations": mean(slot_obs),
            }

        summaries[label] = {
            "replications": len(label_results),
            "mean_pool_blocks": mean(r.pool_blocks for r in label_results),
            "std_pool_blocks": pstdev([r.pool_blocks for r in label_results]) if len(label_results) > 1 else 0.0,
            "mean_support_btc": mean(r.support_btc for r in label_results),
            "mean_inactive_snapshot_slots": mean(
                float(r.metadata.get("mean_inactive_snapshot_slots", 0.0)) for r in label_results
            ),
            "mean_inactive_snapshot_fraction": mean(
                float(r.metadata.get("mean_inactive_snapshot_fraction", 0.0)) for r in label_results
            ),
            "mean_inactive_work_set_proofs": mean(
                float(r.metadata.get("mean_inactive_work_set_proofs", 0.0)) for r in label_results
            ),
            "mean_inactive_work_set_fraction": mean(
                float(r.metadata.get("mean_inactive_work_set_fraction", 0.0)) for r in label_results
            ),
            "mean_active_team_hashrate_share": mean(
                float(r.metadata.get("mean_active_team_hashrate_share", 1.0)) for r in label_results
            ),
            "miners": miner_summaries,
        }

    return summaries

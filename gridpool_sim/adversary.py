from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from statistics import mean, pstdev
from typing import Any

from .engine import sample_pareto_difficulty, sample_poisson


@dataclass(frozen=True)
class AdversaryMiner:
    miner_id: str
    hashrate: float
    role: str


@dataclass
class TeamShare:
    proof_id: int
    miner_id: str
    team_id: str
    difficulty: float
    is_block_proof: bool = False


@dataclass
class AdversaryLedger:
    miner_id: str
    role: str
    hashrate: float
    btc: float = 0.0
    slot0_btc: float = 0.0
    shared_btc: float = 0.0
    block_finds: int = 0
    shares_submitted: int = 0
    shares_accepted: int = 0
    shares_rejected_by_team: int = 0
    snapshot_slot_observations: int = 0


@dataclass
class TeamState:
    team_id: str
    work_set: list[TeamShare] = field(default_factory=list)
    active_snapshot: list[TeamShare] = field(default_factory=list)
    blocks_won: int = 0
    empty_snapshot_blocks: int = 0


@dataclass
class AdversaryRunResult:
    label: str
    seed: int
    blocks: int
    pool_blocks: int
    miners: dict[str, AdversaryLedger]
    teams: dict[str, TeamState]
    metadata: dict[str, Any] = field(default_factory=dict)


class MajorityAdversarySimulator:
    def __init__(self, config: dict[str, Any], label: str, seed: int, strategy: dict[str, Any]):
        self.config = config
        self.label = label
        self.seed = seed
        self.strategy = strategy
        self.rng = random.Random(seed)
        self.miners = [
            AdversaryMiner(m["id"], float(m["hashrate"]), m.get("role", "honest"))
            for m in config["miners"]
        ]
        self.total_hashrate = sum(m.hashrate for m in self.miners)
        if self.total_hashrate <= 0:
            raise ValueError("Total hashrate must be positive")

        self.blocks = int(config["blocks"])
        self.pool_network_share = float(config["pool_network_share"])
        self.shares_per_block_full_team = float(config["shares_per_network_block_at_full_team"])
        self.admission_floor = float(config.get("admission_floor", 1.0))
        self.network_difficulty = self.admission_floor * (
            self.shares_per_block_full_team / self.pool_network_share
        )
        self.total_slots = int(config.get("total_slots", 300))
        self.shared_slots = int(config.get("shared_slots", self.total_slots - 1))
        self.reserve_limit = int(config.get("reserve_limit", math.ceil(self.shared_slots * float(config.get("reserve_multiplier", 3.0)))))
        self.subsidy_btc = float(config.get("subsidy_btc", 3.125))
        self.fees_btc = float(config.get("fees_btc", 0.05))
        self.slot_value_btc = self.subsidy_btc / self.total_slots

        self.next_proof_id = 1
        self.pool_blocks = 0
        self.ledgers = {
            miner.miner_id: AdversaryLedger(miner.miner_id, miner.role, miner.hashrate)
            for miner in self.miners
        }
        self.teams = {
            "inclusive": TeamState("inclusive"),
            "cartel": TeamState("cartel"),
        }

    def run(self) -> AdversaryRunResult:
        self._snapshot_all()
        for _ in range(1, self.blocks + 1):
            block_candidates: list[TeamShare] = []
            new_by_team: dict[str, list[TeamShare]] = {team_id: [] for team_id in self.teams}

            for miner in self.miners:
                team_id = self._team_for_miner(miner)
                lam = self.shares_per_block_full_team * (miner.hashrate / self.total_hashrate)
                for _share_index in range(sample_poisson(self.rng, lam)):
                    share = self._new_share(miner, team_id)
                    ledger = self.ledgers[miner.miner_id]
                    ledger.shares_submitted += 1
                    if self._team_accepts_share(team_id, miner):
                        ledger.shares_accepted += 1
                        new_by_team[team_id].append(share)
                    else:
                        ledger.shares_rejected_by_team += 1
                    if share.is_block_proof:
                        block_candidates.append(share)

            for team_id, shares in new_by_team.items():
                self._insert_shares(self.teams[team_id], shares)

            if block_candidates:
                winner = max(block_candidates, key=lambda p: (p.difficulty, -p.proof_id))
                self._pay_team_snapshot(winner)

            self._snapshot_all()

        return AdversaryRunResult(
            label=self.label,
            seed=self.seed,
            blocks=self.blocks,
            pool_blocks=self.pool_blocks,
            miners=self.ledgers,
            teams=self.teams,
            metadata={
                "network_difficulty": self.network_difficulty,
                "pool_network_share": self.pool_network_share,
                "shared_slots": self.shared_slots,
                "reserve_limit": self.reserve_limit,
            },
        )

    def _team_for_miner(self, miner: AdversaryMiner) -> str:
        mode = self.strategy.get("mode", "honest_single_team")
        if mode == "honest_single_team":
            return "inclusive"
        if mode == "cartel_private_split":
            return "cartel" if miner.role == "cartel" else "inclusive"
        if mode == "cartel_censors_target_others_follow":
            return "inclusive" if miner.role == "target" else "cartel"
        if mode == "naive_target_mines_excluding_team":
            return "cartel"
        raise ValueError(f"Unknown majority adversary mode: {mode}")

    def _team_accepts_share(self, team_id: str, miner: AdversaryMiner) -> bool:
        mode = self.strategy.get("mode", "honest_single_team")
        if team_id == "inclusive":
            return True
        if mode == "cartel_private_split":
            return miner.role == "cartel"
        if mode == "cartel_censors_target_others_follow":
            return miner.role != "target"
        if mode == "naive_target_mines_excluding_team":
            return miner.role != "target"
        return True

    def _new_share(self, miner: AdversaryMiner, team_id: str) -> TeamShare:
        difficulty = sample_pareto_difficulty(self.rng, self.admission_floor)
        proof = TeamShare(
            proof_id=self.next_proof_id,
            miner_id=miner.miner_id,
            team_id=team_id,
            difficulty=difficulty,
            is_block_proof=difficulty >= self.network_difficulty,
        )
        self.next_proof_id += 1
        return proof

    def _insert_shares(self, team: TeamState, shares: list[TeamShare]) -> None:
        if not shares:
            return
        team.work_set.extend(shares)
        team.work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
        if len(team.work_set) > self.reserve_limit:
            del team.work_set[self.reserve_limit :]

    def _snapshot_all(self) -> None:
        for team in self.teams.values():
            team.work_set.sort(key=lambda p: (-p.difficulty, p.proof_id))
            team.active_snapshot = list(team.work_set[: self.shared_slots])
            for proof in team.active_snapshot:
                self.ledgers[proof.miner_id].snapshot_slot_observations += 1

    def _pay_team_snapshot(self, block_proof: TeamShare) -> None:
        self.pool_blocks += 1
        team = self.teams[block_proof.team_id]
        team.blocks_won += 1
        finder = self.ledgers[block_proof.miner_id]
        finder.block_finds += 1

        shared_outputs = len(team.active_snapshot)
        slot0_value = self.subsidy_btc - (self.slot_value_btc * shared_outputs) + self.fees_btc
        finder.slot0_btc += slot0_value
        finder.btc += slot0_value
        if shared_outputs == 0:
            team.empty_snapshot_blocks += 1

        paid_ids = set()
        for proof in team.active_snapshot:
            ledger = self.ledgers[proof.miner_id]
            ledger.shared_btc += self.slot_value_btc
            ledger.btc += self.slot_value_btc
            paid_ids.add(proof.proof_id)

        if paid_ids:
            team.work_set = [proof for proof in team.work_set if proof.proof_id not in paid_ids]


def aggregate_adversary_results(results: list[AdversaryRunResult]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for label in sorted({result.label for result in results}):
        label_results = [result for result in results if result.label == label]
        miner_ids = sorted(label_results[0].miners)
        team_ids = sorted(label_results[0].teams)
        output[label] = {
            "replications": len(label_results),
            "mean_pool_blocks": mean(r.pool_blocks for r in label_results),
            "miners": {},
            "teams": {},
        }
        for miner_id in miner_ids:
            ledgers = [r.miners[miner_id] for r in label_results]
            btc = [ledger.btc for ledger in ledgers]
            output[label]["miners"][miner_id] = {
                "role": ledgers[0].role,
                "hashrate": ledgers[0].hashrate,
                "mean_btc": mean(btc),
                "std_btc": pstdev(btc) if len(btc) > 1 else 0.0,
                "mean_slot0_btc": mean(ledger.slot0_btc for ledger in ledgers),
                "mean_shared_btc": mean(ledger.shared_btc for ledger in ledgers),
                "mean_block_finds": mean(ledger.block_finds for ledger in ledgers),
                "mean_shares_submitted": mean(ledger.shares_submitted for ledger in ledgers),
                "mean_shares_accepted": mean(ledger.shares_accepted for ledger in ledgers),
                "mean_shares_rejected_by_team": mean(ledger.shares_rejected_by_team for ledger in ledgers),
                "mean_snapshot_slot_observations": mean(ledger.snapshot_slot_observations for ledger in ledgers),
            }
        for team_id in team_ids:
            teams = [r.teams[team_id] for r in label_results]
            output[label]["teams"][team_id] = {
                "mean_blocks_won": mean(team.blocks_won for team in teams),
                "mean_final_work_set_count": mean(len(team.work_set) for team in teams),
                "mean_final_snapshot_count": mean(len(team.active_snapshot) for team in teams),
            }
    return output


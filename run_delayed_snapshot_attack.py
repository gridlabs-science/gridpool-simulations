#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.engine import sample_pareto_difficulty, sample_poisson


@dataclass(frozen=True)
class Proof:
    difficulty: float
    owner: str


@dataclass(frozen=True)
class Variant:
    attacker_share: float
    attack_window_blocks: int


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estimate economics of delayed-snapshot stale-branch takeover attempts."
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--attacker-shares", default="0.35,0.51,0.60,0.75,0.90")
    parser.add_argument("--attack-windows", default="1,2,3,6,12")
    parser.add_argument("--shared-slots", type=int, default=299)
    parser.add_argument("--total-slots", type=int, default=300)
    parser.add_argument("--reserve-multiplier", type=float, default=3.0)
    parser.add_argument("--common-depth-multiplier", type=float, default=10.0)
    parser.add_argument("--admission-floor", type=float, default=1.0)
    parser.add_argument("--shares-per-network-block-at-full-team", type=float, default=350.0)
    parser.add_argument("--pool-network-share", type=float, default=0.03)
    parser.add_argument("--subsidy-btc", type=float, default=3.125)
    parser.add_argument("--fees-btc", type=float, default=0.05)
    parser.add_argument(
        "--shared-subsidy-fraction",
        type=float,
        default=None,
        help="Fraction of subsidy allocated to post-slot-0 shared slots. Default is shared_slots / total_slots.",
    )
    parser.add_argument(
        "--reward-model",
        choices=["survival-discounted", "immediate-slot"],
        default="survival-discounted",
        help="survival-discounted values proofs by probability they stay in the top slots until the next GridPool block; immediate-slot is an obsolete upper-bound.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    variants = [
        Variant(attacker_share=share, attack_window_blocks=window)
        for share in parse_floats(args.attacker_shares)
        for window in parse_ints(args.attack_windows)
    ]
    reserve_limit = int(math.ceil(args.shared_slots * args.reserve_multiplier))
    common_samples = int(math.ceil(reserve_limit * args.common_depth_multiplier))
    metadata = {
        "trials": args.trials,
        "seed": args.seed,
        "shared_slots": args.shared_slots,
        "total_slots": args.total_slots,
        "reserve_limit": reserve_limit,
        "common_samples": common_samples,
        "common_depth_multiplier": args.common_depth_multiplier,
        "admission_floor": args.admission_floor,
        "shares_per_network_block_at_full_team": args.shares_per_network_block_at_full_team,
        "pool_network_share": args.pool_network_share,
        "network_difficulty": network_difficulty(args),
        "subsidy_btc": args.subsidy_btc,
        "fees_btc": args.fees_btc,
        "shared_subsidy_fraction": shared_subsidy_fraction(args),
        "slot0_subsidy_fraction": 1.0 - shared_subsidy_fraction(args),
        "reward_model": args.reward_model,
        "notes": [
            "The attacker diverts all attacker hashrate to stale templates for the attack window.",
            "Stale work can improve the attacker's delayed branch but cannot find a valid Bitcoin block on the public chain.",
            "Cost is expected gross BTC forfeited by not mining valid work during the stale window.",
            "Default reward is survival-discounted: extra attacker proofs are valued by probability of staying in the top shared slots until the next GridPool block.",
            "The immediate-slot reward model is preserved only as an upper-bound / obsolete comparison.",
            "This is attacker-favorable: it ignores detection, coordination failure, and future miner response.",
        ],
    }
    rows = [
        run_variant(
            variant,
            args=args,
            reserve_limit=reserve_limit,
            common_samples=common_samples,
            variant_index=index,
        )
        for index, variant in enumerate(variants, start=1)
    ]
    write_csv(args.out_dir / "delayed_snapshot_attack_results.csv", rows)
    (args.out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_report(args.out_dir / "report.md", rows, metadata)
    print(f"Wrote delayed-snapshot attack report to {args.out_dir / 'report.md'}")
    return 0


def run_variant(
    variant: Variant,
    *,
    args: argparse.Namespace,
    reserve_limit: int,
    common_samples: int,
    variant_index: int,
) -> dict[str, float | int | str]:
    rng = random.Random(args.seed + (variant_index * 1000003))
    slot_value_btc = (args.subsidy_btc * shared_subsidy_fraction(args)) / args.shared_slots
    gross_block_reward_btc = args.subsidy_btc + args.fees_btc
    network_diff = network_difficulty(args)
    stale_cost_btc = (
        variant.attacker_share
        * args.pool_network_share
        * variant.attack_window_blocks
        * gross_block_reward_btc
    )

    successes = 0
    attack_floor_values: list[float] = []
    honest_floor_values: list[float] = []
    attacker_slot_deltas: list[int] = []
    attacker_survival_value_deltas: list[float] = []
    reward_values: list[float] = []
    roi_values: list[float] = []

    for _ in range(args.trials):
        common = sample_common_reserve(
            rng,
            samples=common_samples,
            reserve_limit=reserve_limit,
            floor=args.admission_floor,
            attacker_share=variant.attacker_share,
        )
        attack_new = sample_new_proofs(
            rng,
            expected_count=args.shares_per_network_block_at_full_team
            * variant.attack_window_blocks
            * variant.attacker_share,
            floor=args.admission_floor,
            owner="attacker",
        )
        honest_new = sample_new_proofs(
            rng,
            expected_count=args.shares_per_network_block_at_full_team
            * variant.attack_window_blocks
            * (1.0 - variant.attacker_share),
            floor=args.admission_floor,
            owner="honest",
        )

        attack_reserve = top_reserve(common + attack_new, reserve_limit)
        honest_reserve = top_reserve(common + honest_new, reserve_limit)
        attack_floor = reserve_floor(attack_reserve)
        honest_floor = reserve_floor(honest_reserve)
        attack_floor_values.append(attack_floor)
        honest_floor_values.append(honest_floor)

        attack_wins = attack_floor > honest_floor
        if attack_wins:
            successes += 1

        attack_slots = attacker_slots(attack_reserve, args.shared_slots)
        honest_slots = attacker_slots(honest_reserve, args.shared_slots)
        delta_slots = attack_slots - honest_slots
        attacker_slot_deltas.append(delta_slots)

        survival_delta_slots = attacker_survival_value_delta(
            attack_reserve,
            honest_reserve,
            shared_slots=args.shared_slots,
            network_difficulty=network_diff,
        )
        attacker_survival_value_deltas.append(survival_delta_slots)

        if args.reward_model == "immediate-slot":
            reward = max(0, delta_slots) * slot_value_btc if attack_wins else 0.0
        else:
            reward = max(0.0, survival_delta_slots) * slot_value_btc if attack_wins else 0.0
        reward_values.append(reward)
        roi_values.append(reward - stale_cost_btc)

    success_probability = successes / args.trials
    mean_reward = statistics.fmean(reward_values)
    mean_delta_slots = statistics.fmean(attacker_slot_deltas)
    mean_success_delta_slots = statistics.fmean(
        [delta for delta, reward in zip(attacker_slot_deltas, reward_values) if reward > 0]
        or [0.0]
    )
    mean_survival_delta_slots = statistics.fmean(attacker_survival_value_deltas)
    mean_success_survival_delta_slots = statistics.fmean(
        [delta for delta, reward in zip(attacker_survival_value_deltas, reward_values) if reward > 0]
        or [0.0]
    )
    return {
        "attacker_share": variant.attacker_share,
        "attack_window_blocks": variant.attack_window_blocks,
        "trials": args.trials,
        "success_probability": success_probability,
        "mean_attacker_slot_delta": mean_delta_slots,
        "mean_positive_slot_delta_when_successful": mean_success_delta_slots,
        "mean_survival_adjusted_slot_delta": mean_survival_delta_slots,
        "mean_positive_survival_adjusted_slot_delta_when_successful": mean_success_survival_delta_slots,
        "mean_attack_floor": statistics.fmean(attack_floor_values),
        "mean_honest_floor": statistics.fmean(honest_floor_values),
        "expected_extra_shared_reward_btc": mean_reward,
        "expected_stale_work_cost_btc": stale_cost_btc,
        "expected_net_btc": mean_reward - stale_cost_btc,
        "reward_cost_ratio": safe_div(mean_reward, stale_cost_btc),
        "mean_trial_net_btc": statistics.fmean(roi_values),
        "slot_value_btc": slot_value_btc,
        "shared_subsidy_fraction": shared_subsidy_fraction(args),
        "slot0_subsidy_fraction": 1.0 - shared_subsidy_fraction(args),
        "network_difficulty": network_diff,
        "reward_model": args.reward_model,
    }


def sample_common_reserve(
    rng: random.Random,
    *,
    samples: int,
    reserve_limit: int,
    floor: float,
    attacker_share: float,
) -> list[Proof]:
    proofs = [
        Proof(
            difficulty=sample_pareto_difficulty(rng, floor),
            owner="attacker" if rng.random() < attacker_share else "honest",
        )
        for _ in range(samples)
    ]
    return top_reserve(proofs, reserve_limit)


def sample_new_proofs(
    rng: random.Random,
    *,
    expected_count: float,
    floor: float,
    owner: str,
) -> list[Proof]:
    count = sample_poisson(rng, expected_count)
    return [Proof(sample_pareto_difficulty(rng, floor), owner) for _ in range(count)]


def top_reserve(proofs: list[Proof], reserve_limit: int) -> list[Proof]:
    if len(proofs) <= reserve_limit:
        return sorted(proofs, key=lambda proof: proof.difficulty, reverse=True)
    return heapq.nlargest(reserve_limit, proofs, key=lambda proof: proof.difficulty)


def reserve_floor(proofs: list[Proof]) -> float:
    return proofs[-1].difficulty if proofs else 0.0


def attacker_slots(proofs: list[Proof], shared_slots: int) -> int:
    return sum(1 for proof in proofs[:shared_slots] if proof.owner == "attacker")


def attacker_survival_value_delta(
    attack_reserve: list[Proof],
    honest_reserve: list[Proof],
    *,
    shared_slots: int,
    network_difficulty: float,
) -> float:
    attack_value = sum(
        share_survival_probability(proof.difficulty, network_difficulty, shared_slots)
        for proof in attack_reserve[:shared_slots]
        if proof.owner == "attacker"
    )
    honest_value = sum(
        share_survival_probability(proof.difficulty, network_difficulty, shared_slots)
        for proof in honest_reserve[:shared_slots]
        if proof.owner == "attacker"
    )
    return attack_value - honest_value


def share_survival_probability(share_difficulty: float, network_difficulty: float, shared_slots: int) -> float:
    if share_difficulty <= 0 or network_difficulty <= 0 or shared_slots <= 0:
        return 0.0
    return 1.0 - (network_difficulty / (share_difficulty + network_difficulty)) ** shared_slots


def network_difficulty(args: argparse.Namespace) -> float:
    return args.admission_floor * (
        args.shares_per_network_block_at_full_team / args.pool_network_share
    )


def shared_subsidy_fraction(args: argparse.Namespace) -> float:
    if args.shared_subsidy_fraction is None:
        return args.shared_slots / args.total_slots
    return max(0.0, min(1.0, args.shared_subsidy_fraction))


def write_csv(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: list[dict[str, float | int | str]], metadata: dict[str, object]) -> None:
    lines = [
        "# Delayed Snapshot Attack Economics",
        "",
        "Status: generated by `run_delayed_snapshot_attack.py`.",
        "",
        "## Model",
        "",
        "This model estimates a delayed-snapshot stale-branch attack:",
        "",
        "1. Honest nodes snapshot after a Bitcoin block.",
        "2. The attacker keeps hashing stale templates on the previous parent.",
        "3. The stale branch can accumulate attacker-favorable shares, but cannot find a valid Bitcoin block.",
        "4. The attacker later reveals the branch and wins only if its reserve floor beats the honest branch reserve floor.",
        "",
        "Cost is the attacker's expected gross BTC from valid mining during the stale window.",
        "Reward is extra shared payout slots if the delayed branch wins.",
        "",
        "## Parameters",
        "",
        "| Parameter | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "trials",
        "shared_slots",
        "total_slots",
        "reserve_limit",
        "common_samples",
        "shares_per_network_block_at_full_team",
        "pool_network_share",
        "network_difficulty",
        "subsidy_btc",
        "fees_btc",
        "shared_subsidy_fraction",
        "slot0_subsidy_fraction",
        "reward_model",
    ]:
        lines.append(f"| `{key}` | `{metadata[key]}` |")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Attacker Share | Window Blocks | Success | Mean Slot Delta | Survival-Adj Slot Delta | Extra Reward BTC | Stale Cost BTC | Net BTC | Reward/Cost |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            "| {share:.0%} | {window} | {success:.2%} | {delta:.3f} | {survival_delta:.3f} | {reward:.8f} | {cost:.8f} | {net:.8f} | {ratio:.4f} |".format(
                share=float(row["attacker_share"]),
                window=int(row["attack_window_blocks"]),
                success=float(row["success_probability"]),
                delta=float(row["mean_attacker_slot_delta"]),
                survival_delta=float(row["mean_survival_adjusted_slot_delta"]),
                reward=float(row["expected_extra_shared_reward_btc"]),
                cost=float(row["expected_stale_work_cost_btc"]),
                net=float(row["expected_net_btc"]),
                ratio=float(row["reward_cost_ratio"]),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Values below `1.0` in Reward/Cost mean the attack burns more expected BTC than it gains in extra shared slots.",
            "- In the default `survival-discounted` model, low-difficulty early slots are not valued as guaranteed payouts. They are discounted by the chance they remain in the top shared slots until the next GridPool block.",
            "- This model is intentionally attacker-favorable because it ignores detection, coordination failure, and future miner response.",
            "- The result does not model a state-sponsored griefer whose utility is external to Bitcoin mining economics.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_floats(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def parse_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


if __name__ == "__main__":
    raise SystemExit(main())

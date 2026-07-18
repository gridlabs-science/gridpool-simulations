#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import statistics
from typing import Iterable


@dataclass(frozen=True)
class Proof:
    proof_id: int
    owner: str
    difficulty: float
    context: str


@dataclass(frozen=True)
class Variant:
    attacker_share: float
    strategy: str
    merge_policy: str


@dataclass
class Ledger:
    attacker_btc: float = 0.0
    honest_btc: float = 0.0
    attacker_slot0_btc: float = 0.0
    attacker_shared_btc: float = 0.0
    honest_slot0_btc: float = 0.0
    honest_shared_btc: float = 0.0
    gridpool_blocks: int = 0
    attacker_blocks: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Model selective-inclusion/free-riding against V2.1 current-parent "
            "merge-forward behavior."
        )
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--blocks", type=int, default=3000)
    parser.add_argument("--replications", type=int, default=20)
    parser.add_argument("--seed", type=int, default=72117)
    parser.add_argument("--attacker-shares", default="0.10,0.35,0.51,0.67,0.90")
    parser.add_argument(
        "--strategies",
        default="free_ride,private_split",
        help="free_ride relays attacker proofs; private_split withholds them.",
    )
    parser.add_argument(
        "--merge-policies",
        default="merge_all_current_parent,canonical_context_only",
    )
    parser.add_argument("--pool-network-share", type=float, default=0.03)
    parser.add_argument("--shared-slots", type=int, default=299)
    parser.add_argument("--total-slots", type=int, default=300)
    parser.add_argument("--reserve-multiplier", type=float, default=3.0)
    parser.add_argument("--proofs-per-bitcoin-block", type=float, default=100.0)
    parser.add_argument("--bootstrap-multiplier", type=float, default=8.0)
    parser.add_argument("--subsidy-btc", type=float, default=3.125)
    parser.add_argument("--fees-btc", type=float, default=0.05)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.blocks = min(args.blocks, 800)
        args.replications = min(args.replications, 3)
        args.attacker_shares = "0.35,0.51,0.90"
    validate_args(args)

    variants = [
        Variant(attacker_share, strategy, merge_policy)
        for attacker_share in parse_floats(args.attacker_shares)
        for strategy in parse_strings(args.strategies)
        for merge_policy in parse_strings(args.merge_policies)
    ]
    raw_rows: list[dict[str, object]] = []
    total = len(variants) * args.replications
    completed = 0
    for variant_index, variant in enumerate(variants):
        for replication in range(args.replications):
            seed = args.seed + variant_index * 1_000_003 + replication
            raw_rows.append(run_paired_replication(args, variant, replication, seed))
            completed += 1
            if completed == total or completed % max(1, total // 20) == 0:
                print(f"[{completed}/{total}] {variant.strategy} {variant.merge_policy} attacker={variant.attacker_share:.0%}", flush=True)

    summary_rows = aggregate_rows(raw_rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "selective_inclusion_replications.csv", raw_rows)
    write_csv(args.out_dir / "selective_inclusion_summary.csv", summary_rows)
    metadata = build_metadata(args)
    (args.out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_report(args.out_dir / "report.md", summary_rows, metadata)
    print(f"Wrote selective-inclusion report to {args.out_dir / 'report.md'}")
    return 0


def validate_args(args: argparse.Namespace) -> None:
    if not 0 < args.pool_network_share <= 1:
        raise SystemExit("--pool-network-share must be in (0, 1].")
    if not 0 < args.shared_slots < args.total_slots:
        raise SystemExit("--shared-slots must be positive and below --total-slots.")
    if args.blocks <= 0 or args.replications <= 0:
        raise SystemExit("--blocks and --replications must be positive.")
    valid_strategies = {"free_ride", "private_split"}
    valid_policies = {"merge_all_current_parent", "canonical_context_only"}
    if not set(parse_strings(args.strategies)) <= valid_strategies:
        raise SystemExit(f"Strategies must be in {sorted(valid_strategies)}.")
    if not set(parse_strings(args.merge_policies)) <= valid_policies:
        raise SystemExit(f"Merge policies must be in {sorted(valid_policies)}.")


def run_paired_replication(
    args: argparse.Namespace,
    variant: Variant,
    replication: int,
    seed: int,
) -> dict[str, object]:
    rng = random.Random(seed)
    schedule = build_schedule(args, variant.attacker_share, rng)
    baseline = simulate(args, variant, schedule, attack=False)
    attacked = simulate(args, variant, schedule, attack=True)
    expected_total_btc = schedule["gridpool_blocks"] * (args.subsidy_btc + args.fees_btc)
    conservation_error = abs((attacked["ledger"].attacker_btc + attacked["ledger"].honest_btc) - expected_total_btc)
    if conservation_error > 1e-8:
        raise RuntimeError(f"Payout conservation failed by {conservation_error} BTC")

    return {
        "attacker_share": variant.attacker_share,
        "strategy": variant.strategy,
        "merge_policy": variant.merge_policy,
        "replication": replication,
        "seed": seed,
        "blocks": args.blocks,
        "gridpool_blocks": schedule["gridpool_blocks"],
        "attacker_blocks": schedule["attacker_blocks"],
        "baseline_attacker_btc": baseline["ledger"].attacker_btc,
        "attack_attacker_btc": attacked["ledger"].attacker_btc,
        "attacker_delta_btc": attacked["ledger"].attacker_btc - baseline["ledger"].attacker_btc,
        "baseline_honest_btc": baseline["ledger"].honest_btc,
        "attack_honest_btc": attacked["ledger"].honest_btc,
        "honest_delta_btc": attacked["ledger"].honest_btc - baseline["ledger"].honest_btc,
        "attacker_reward_share": safe_div(attacked["ledger"].attacker_btc, expected_total_btc),
        "attacker_reward_share_minus_hash_share": safe_div(attacked["ledger"].attacker_btc, expected_total_btc) - variant.attacker_share,
        "attacker_shared_btc": attacked["ledger"].attacker_shared_btc,
        "attacker_slot0_btc": attacked["ledger"].attacker_slot0_btc,
        "honest_shared_btc": attacked["ledger"].honest_shared_btc,
        "divergent_boundary_fraction": safe_div(attacked["divergent_boundaries"], args.blocks),
        "attacker_mean_slots_honest_snapshot": safe_div(attacked["attacker_slots_honest_sum"], args.blocks),
        "attacker_mean_slots_private_snapshot": safe_div(attacked["attacker_slots_private_sum"], args.blocks),
        "cross_context_proofs_credited": attacked["cross_context_credited"],
        "cross_context_proofs_rejected": attacked["cross_context_rejected"],
        "private_floor_beats_honest_fraction": safe_div(attacked["private_floor_wins"], args.blocks),
        "established_nodes_forced_to_switch": 0,
        "payout_conservation_error_btc": conservation_error,
    }


def build_schedule(args: argparse.Namespace, attacker_share: float, rng: random.Random) -> dict[str, object]:
    intervals: list[dict[str, object]] = []
    gridpool_blocks = 0
    attacker_blocks = 0
    for _ in range(args.blocks):
        proof_count = sample_poisson(rng, args.proofs_per_bitcoin_block)
        proofs = [
            (
                "attacker" if rng.random() < attacker_share else "honest",
                sample_pareto(rng, 1.0),
            )
            for _ in range(proof_count)
        ]
        is_gridpool_block = rng.random() < args.pool_network_share
        finder = None
        block_difficulty = None
        if is_gridpool_block:
            gridpool_blocks += 1
            finder = "attacker" if rng.random() < attacker_share else "honest"
            attacker_blocks += int(finder == "attacker")
            network_difficulty = args.proofs_per_bitcoin_block / args.pool_network_share
            block_difficulty = sample_pareto(rng, network_difficulty)
        intervals.append(
            {
                "proofs": proofs,
                "is_gridpool_block": is_gridpool_block,
                "finder": finder,
                "block_difficulty": block_difficulty,
            }
        )
    return {
        "intervals": intervals,
        "gridpool_blocks": gridpool_blocks,
        "attacker_blocks": attacker_blocks,
        "bootstrap_seed": rng.randrange(1 << 63),
    }


def simulate(
    args: argparse.Namespace,
    variant: Variant,
    schedule: dict[str, object],
    *,
    attack: bool,
) -> dict[str, object]:
    reserve_limit = math.ceil(args.shared_slots * args.reserve_multiplier)
    bootstrap_count = math.ceil(reserve_limit * args.bootstrap_multiplier)
    bootstrap_rng = random.Random(int(schedule["bootstrap_seed"]))
    next_id = 1
    common: list[Proof] = []
    for _ in range(bootstrap_count):
        owner = "attacker" if bootstrap_rng.random() < variant.attacker_share else "honest"
        common.append(Proof(next_id, owner, sample_pareto(bootstrap_rng, 1.0), "common"))
        next_id += 1
    honest_reserve = top_proofs(common, reserve_limit)
    attacker_reserve = list(honest_reserve)
    honest_snapshot = top_proofs(honest_reserve, args.shared_slots)
    attacker_snapshot = list(honest_snapshot)
    ledger = Ledger()
    divergent_boundaries = 0
    attacker_slots_honest_sum = 0
    attacker_slots_private_sum = 0
    cross_context_credited = 0
    cross_context_rejected = 0
    private_floor_wins = 0

    for interval_index, interval in enumerate(schedule["intervals"]):
        if interval["is_gridpool_block"]:
            finder = str(interval["finder"])
            paid_snapshot = attacker_snapshot if attack and finder == "attacker" else honest_snapshot
            pay_block(args, ledger, finder, paid_snapshot)
            paid_ids = {proof.proof_id for proof in paid_snapshot}
            honest_reserve = [proof for proof in honest_reserve if proof.proof_id not in paid_ids]
            attacker_reserve = [proof for proof in attacker_reserve if proof.proof_id not in paid_ids]
            context = "attacker" if attack and finder == "attacker" else "honest"
            block_proof = Proof(next_id, finder, float(interval["block_difficulty"]), context)
            next_id += 1
            honest_reserve.append(block_proof)
            if not attack or variant.strategy == "free_ride" or finder == "attacker":
                attacker_reserve.append(block_proof)

        current_contexts_match = proof_ids(honest_snapshot) == proof_ids(attacker_snapshot)
        for owner, difficulty in interval["proofs"]:
            owner = str(owner)
            if not attack:
                proof = Proof(next_id, owner, float(difficulty), "honest")
                next_id += 1
                honest_reserve.append(proof)
                attacker_reserve.append(proof)
                continue

            if owner == "honest":
                proof = Proof(next_id, owner, float(difficulty), "honest")
                next_id += 1
                honest_reserve.append(proof)
                # The selective attacker deliberately excludes honest proofs.
                continue

            proof = Proof(next_id, owner, float(difficulty), "attacker")
            next_id += 1
            attacker_reserve.append(proof)
            if variant.strategy == "private_split":
                continue
            if variant.merge_policy == "merge_all_current_parent" or current_contexts_match:
                honest_reserve.append(proof)
                if not current_contexts_match:
                    cross_context_credited += 1
            else:
                cross_context_rejected += 1

        honest_reserve = top_proofs(honest_reserve, reserve_limit)
        attacker_reserve = top_proofs(attacker_reserve, reserve_limit)
        honest_snapshot = top_proofs(honest_reserve, args.shared_slots)
        attacker_snapshot = top_proofs(attacker_reserve, args.shared_slots)
        if proof_ids(honest_snapshot) != proof_ids(attacker_snapshot):
            divergent_boundaries += 1
        if reserve_floor(attacker_reserve, reserve_limit) > reserve_floor(honest_reserve, reserve_limit):
            private_floor_wins += 1
        attacker_slots_honest_sum += owner_slots(honest_snapshot, "attacker")
        attacker_slots_private_sum += owner_slots(attacker_snapshot, "attacker")

    return {
        "ledger": ledger,
        "divergent_boundaries": divergent_boundaries,
        "attacker_slots_honest_sum": attacker_slots_honest_sum,
        "attacker_slots_private_sum": attacker_slots_private_sum,
        "cross_context_credited": cross_context_credited,
        "cross_context_rejected": cross_context_rejected,
        "private_floor_wins": private_floor_wins,
    }


def pay_block(args: argparse.Namespace, ledger: Ledger, finder: str, snapshot: list[Proof]) -> None:
    slot_value = args.subsidy_btc / args.total_slots
    shared_value = slot_value * len(snapshot)
    slot0_value = args.subsidy_btc - shared_value + args.fees_btc
    attacker_slots = owner_slots(snapshot, "attacker")
    attacker_shared = attacker_slots * slot_value
    honest_shared = shared_value - attacker_shared
    ledger.gridpool_blocks += 1
    ledger.attacker_blocks += int(finder == "attacker")
    ledger.attacker_shared_btc += attacker_shared
    ledger.honest_shared_btc += honest_shared
    ledger.attacker_btc += attacker_shared
    ledger.honest_btc += honest_shared
    if finder == "attacker":
        ledger.attacker_slot0_btc += slot0_value
        ledger.attacker_btc += slot0_value
    else:
        ledger.honest_slot0_btc += slot0_value
        ledger.honest_btc += slot0_value


def aggregate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = (row["attacker_share"], row["strategy"], row["merge_policy"])
        grouped.setdefault(key, []).append(row)
    output: list[dict[str, object]] = []
    metric_names = [
        "attacker_delta_btc",
        "honest_delta_btc",
        "attacker_reward_share",
        "attacker_reward_share_minus_hash_share",
        "divergent_boundary_fraction",
        "attacker_mean_slots_honest_snapshot",
        "attacker_mean_slots_private_snapshot",
        "cross_context_proofs_credited",
        "cross_context_proofs_rejected",
        "private_floor_beats_honest_fraction",
    ]
    for key, group in sorted(grouped.items()):
        row: dict[str, object] = {
            "attacker_share": key[0],
            "strategy": key[1],
            "merge_policy": key[2],
            "replications": len(group),
            "mean_gridpool_blocks": statistics.fmean(float(item["gridpool_blocks"]) for item in group),
        }
        for metric in metric_names:
            values = [float(item[metric]) for item in group]
            row[f"mean_{metric}"] = statistics.fmean(values)
            row[f"se_{metric}"] = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        output.append(row)
    return output


def build_metadata(args: argparse.Namespace) -> dict[str, object]:
    return {
        "blocks_per_replication": args.blocks,
        "replications": args.replications,
        "pool_network_share": args.pool_network_share,
        "shared_slots": args.shared_slots,
        "total_slots": args.total_slots,
        "reserve_limit": math.ceil(args.shared_slots * args.reserve_multiplier),
        "proofs_per_bitcoin_block": args.proofs_per_bitcoin_block,
        "subsidy_btc": args.subsidy_btc,
        "fees_btc": args.fees_btc,
        "model_boundaries": [
            "All variants use the same proof and block-finder schedule as their paired honest baseline.",
            "free_ride relays attacker proofs to honest nodes while excluding honest proofs from the attacker's private view.",
            "private_split withholds attacker proofs and excludes honest proofs; it is a separate subteam, not a free rider.",
            "merge_all_current_parent is a deliberately permissive counterfactual that cross-credits proofs across genuinely different active payout states.",
            "The tested V2.1 candidate-import path anchors candidate IDs to the active state and rejects that cross-state transition.",
            "canonical_context_only approximates the tested candidate-import boundary by rejecting work built on a different active snapshot.",
            "Established V2.1 nodes never switch active snapshots merely because a private reserve scores higher.",
            "This first model assumes instantaneous delivery and no accidental boundary races; latency belongs in a later combined model.",
            "The existing delayed-snapshot model separately measures stale-parent mining cost and gives a counterfactual takeover upper bound; V2.1 established nodes reject that replacement.",
            "Paid IDs from either branch are conservatively removed from both reserves; divergent-payment recognition needs a runtime integration test.",
        ],
    }


def write_report(path: Path, rows: list[dict[str, object]], metadata: dict[str, object]) -> None:
    lines = [
        "# V2.1 Selective-Inclusion And Merge-Forward Model",
        "",
        "Status: exploratory mechanism-design model. Results are not protocol proof.",
        "",
        "## Question",
        "",
        "Can a miner exclude other miners from its own payout snapshot while continuing to have its current-parent proofs credited by an inclusive GridPool team?",
        "",
        "The model deliberately separates this from stale-parent takeover. A `free_ride` attacker keeps mining the current Bitcoin parent, preserves slot-0 eligibility, relays its own proofs, and excludes honest proofs locally. A `private_split` attacker also withholds its proofs and therefore behaves as a separate subteam.",
        "",
        "## Policies",
        "",
        "- `merge_all_current_parent`: deliberately permissive counterfactual in which valid current-parent proofs cross-credit across genuinely different active payout states.",
        "- `canonical_context_only`: credits a proof only while the attacker's active snapshot equals the honest snapshot; this approximates the tested candidate-import boundary.",
        "- Existing V2.1 nodes do not switch their active snapshot based on private reserve strength; `established_nodes_forced_to_switch` is therefore zero by rule.",
        "",
        "## Results",
        "",
        "| Attacker Hash | Strategy | Merge Policy | Attacker BTC Delta | Honest BTC Delta | Reward Share - Hash Share | Divergent Boundaries | Slots On Honest Snapshot | Slots On Private Snapshot | Private Floor Wins |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {share:.0%} | `{strategy}` | `{policy}` | {attacker_delta:.5f} | {honest_delta:.5f} | {reward_edge:+.3%} | {divergence:.2%} | {honest_slots:.2f} | {private_slots:.2f} | {floor_wins:.2%} |".format(
                share=float(row["attacker_share"]),
                strategy=row["strategy"],
                policy=row["merge_policy"],
                attacker_delta=float(row["mean_attacker_delta_btc"]),
                honest_delta=float(row["mean_honest_delta_btc"]),
                reward_edge=float(row["mean_attacker_reward_share_minus_hash_share"]),
                divergence=float(row["mean_divergent_boundary_fraction"]),
                honest_slots=float(row["mean_attacker_mean_slots_honest_snapshot"]),
                private_slots=float(row["mean_attacker_mean_slots_private_snapshot"]),
                floor_wins=float(row["mean_private_floor_beats_honest_fraction"]),
            )
        )
    lines.extend(
        [
            "",
            "## Reading The Result",
            "",
            "- Positive attacker BTC delta paired with an equal negative honest delta indicates transfer, not newly created value.",
            "- A free-rider edge under `merge_all_current_parent` shows why future split recovery must not blindly cross-credit different active payout states.",
            "- This is not a confirmed runtime exploit: the regression `CandidateImportRejectsCurrentParentProofFromDifferentActiveSnapshotAsync` rejects the modeled transition.",
            "- If `private_split` remains near fair expected value, exclusion mostly creates a separate high-variance subteam rather than theft.",
            "- `Private Floor Wins` is diagnostic only. V2.1 established nodes do not adopt that branch on this score, so majority hashrate cannot directly force an active-snapshot rewrite in this model.",
            "- Run the existing `run_delayed_snapshot_attack.py` beside this report for attacks that actually mine the previous Bitcoin parent and forfeit valid block opportunity.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {note}" for note in metadata["model_boundaries"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def top_proofs(proofs: Iterable[Proof], limit: int) -> list[Proof]:
    return sorted(proofs, key=lambda proof: (-proof.difficulty, proof.proof_id))[:limit]


def proof_ids(proofs: Iterable[Proof]) -> tuple[int, ...]:
    return tuple(proof.proof_id for proof in proofs)


def owner_slots(proofs: Iterable[Proof], owner: str) -> int:
    return sum(1 for proof in proofs if proof.owner == owner)


def reserve_floor(proofs: list[Proof], reserve_limit: int) -> float:
    return proofs[-1].difficulty if len(proofs) >= reserve_limit else 0.0


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


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_floats(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def parse_strings(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


if __name__ == "__main__":
    raise SystemExit(main())

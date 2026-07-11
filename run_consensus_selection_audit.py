#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.engine import sample_pareto_difficulty, sample_poisson


@dataclass(frozen=True)
class Variant:
    majority_share: float
    split_proofs: float
    common_mode: str
    profile: str
    eligibility_mode: str
    eligibility_alpha: float


@dataclass(frozen=True)
class TrialScores:
    score_a: float
    score_b: float


ScoreFn = Callable[[list[float], int, float], float]


SCORE_RULES: dict[str, ScoreFn] = {}

CHART_SCORE_RULES = [
    "sum_workset_difficulty",
    "sum_minus_top_1",
    "sum_minus_top_10",
    "sum_minus_top_30",
    "sum_capped_100x_floor",
    "sqrt_sum",
    "log_sum",
    "median_times_count",
    "p10_times_count",
    "bottom_10_mean_times_count",
]


def score_rule(name: str) -> Callable[[ScoreFn], ScoreFn]:
    def register(fn: ScoreFn) -> ScoreFn:
        SCORE_RULES[name] = fn
        return fn

    return register


@score_rule("sum_workset_difficulty")
def score_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return math.fsum(proofs)


@score_rule("snapshot_sum_difficulty")
def score_snapshot_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return math.fsum(sorted(proofs, reverse=True)[:shared_slots])


@score_rule("sum_minus_top_1")
def score_sum_minus_top_1(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(proofs, 1)


@score_rule("sum_minus_top_3")
def score_sum_minus_top_3(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(proofs, 3)


@score_rule("sum_minus_top_10")
def score_sum_minus_top_10(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(proofs, 10)


@score_rule("sum_minus_top_30")
def score_sum_minus_top_30(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(proofs, 30)


@score_rule("snapshot_sum_minus_top_1")
def score_snapshot_sum_minus_top_1(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(sorted(proofs, reverse=True)[:shared_slots], 1)


@score_rule("snapshot_sum_minus_top_10")
def score_snapshot_sum_minus_top_10(proofs: list[float], shared_slots: int, floor: float) -> float:
    return sum_minus_top_count(sorted(proofs, reverse=True)[:shared_slots], 10)


@score_rule("top_1pct_trimmed_sum")
def score_top_1pct_trimmed_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return top_trimmed_sum(proofs, 0.01)


@score_rule("top_5pct_trimmed_sum")
def score_top_5pct_trimmed_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return top_trimmed_sum(proofs, 0.05)


@score_rule("top_1pct_winsorized_sum")
def score_top_1pct_winsorized_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return top_winsorized_sum(proofs, 0.01)


@score_rule("top_5pct_winsorized_sum")
def score_top_5pct_winsorized_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return top_winsorized_sum(proofs, 0.05)


@score_rule("sum_capped_10x_floor")
def score_sum_capped_10x_floor(proofs: list[float], shared_slots: int, floor: float) -> float:
    return capped_sum(proofs, cap=floor * 10.0)


@score_rule("sum_capped_100x_floor")
def score_sum_capped_100x_floor(proofs: list[float], shared_slots: int, floor: float) -> float:
    return capped_sum(proofs, cap=floor * 100.0)


@score_rule("sum_capped_1000x_floor")
def score_sum_capped_1000x_floor(proofs: list[float], shared_slots: int, floor: float) -> float:
    return capped_sum(proofs, cap=floor * 1000.0)


@score_rule("sqrt_sum")
def score_sqrt_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return math.fsum(math.sqrt(max(0.0, proof / floor)) for proof in proofs)


@score_rule("log_sum")
def score_log_sum(proofs: list[float], shared_slots: int, floor: float) -> float:
    return math.fsum(math.log1p(max(0.0, proof / floor)) for proof in proofs)


@score_rule("median_times_count")
def score_median_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    if not proofs:
        return 0.0
    return statistics.median(proofs) * len(proofs)


@score_rule("p10_times_count")
def score_p10_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return percentile_times_count(proofs, 0.10)


@score_rule("p25_times_count")
def score_p25_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return percentile_times_count(proofs, 0.25)


@score_rule("bottom_1_times_count")
def score_bottom_1_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return bottom_mean_times_count(proofs, 1)


@score_rule("bottom_3_mean_times_count")
def score_bottom_3_mean_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return bottom_mean_times_count(proofs, 3)


@score_rule("bottom_10_mean_times_count")
def score_bottom_10_mean_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return bottom_mean_times_count(proofs, 10)


@score_rule("bottom_30_mean_times_count")
def score_bottom_30_mean_times_count(proofs: list[float], shared_slots: int, floor: float) -> float:
    return bottom_mean_times_count(proofs, 30)


@score_rule("count_only")
def score_count_only(proofs: list[float], shared_slots: int, floor: float) -> float:
    return float(len(proofs))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare GridPool candidate-state selection scores under heavy-tailed proof difficulty."
    )
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated reports.")
    parser.add_argument("--trials", type=int, default=3000, help="Monte Carlo trials per variant.")
    parser.add_argument("--quick", action="store_true", help="Fast smoke run with fewer variants/trials.")
    parser.add_argument("--jobs", type=int, default=1, help="Number of variants to run concurrently.")
    parser.add_argument("--seed", type=int, default=8675309, help="Base RNG seed.")
    parser.add_argument("--shared-slots", type=int, default=299, help="Shared payout slots in active snapshot.")
    parser.add_argument("--reserve-multiplier", type=float, default=3.0, help="Work Set reserve depth multiplier.")
    parser.add_argument("--admission-floor", type=float, default=1.0, help="Minimum proof difficulty floor.")
    parser.add_argument(
        "--majority-shares",
        default="0.51,0.55,0.60,0.67,0.75,0.90",
        help="Comma-separated true hashrate shares for side A.",
    )
    parser.add_argument(
        "--split-proofs",
        default="10,30,100,300,900",
        help="Comma-separated expected proof counts generated by the full team during the split window.",
    )
    parser.add_argument(
        "--common-modes",
        default="empty,mature",
        help="Comma-separated common reserve modes: empty,mature.",
    )
    parser.add_argument(
        "--profiles",
        default="honest",
        help="Comma-separated trial profiles: honest,minority_floor_flood,minority_reserve_fill.",
    )
    parser.add_argument(
        "--floor-spam-multiplier",
        type=float,
        default=6.0,
        help="Low-difficulty proof multiplier for minority_floor_flood and minority_reserve_fill profiles.",
    )
    parser.add_argument(
        "--eligibility-modes",
        default=None,
        help="Comma-separated score eligibility filters: none,active_snapshot_floor,reserve_floor.",
    )
    parser.add_argument(
        "--eligibility-alphas",
        default=None,
        help="Comma-separated alpha values for non-none eligibility modes.",
    )
    parser.add_argument(
        "--common-depth-multiplier",
        type=float,
        default=1.0,
        help="For mature mode, sample this many reserve depths and keep the top reserve.",
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0, help="Progress heartbeat interval.")
    args = parser.parse_args()

    if args.quick:
        args.trials = min(args.trials, 400)
        args.majority_shares = "0.51,0.60,0.75"
        args.split_proofs = "10,100,900"
        args.common_modes = "empty,mature"
        args.profiles = "honest,minority_floor_flood"
        args.eligibility_modes = args.eligibility_modes or "none,active_snapshot_floor"
        args.eligibility_alphas = args.eligibility_alphas or "0.5,1.0"

    args.eligibility_modes = args.eligibility_modes or "none"
    args.eligibility_alphas = args.eligibility_alphas or "0.5,0.75,1.0"

    reserve_limit = int(math.ceil(args.shared_slots * args.reserve_multiplier))
    eligibility_variants = build_eligibility_variants(
        modes=parse_str_list(args.eligibility_modes),
        alphas=parse_float_list(args.eligibility_alphas),
    )
    variants = [
        Variant(
            majority_share=majority,
            split_proofs=split_proofs,
            common_mode=common_mode,
            profile=profile,
            eligibility_mode=eligibility_mode,
            eligibility_alpha=eligibility_alpha,
        )
        for majority in parse_float_list(args.majority_shares)
        for split_proofs in parse_float_list(args.split_proofs)
        for common_mode in parse_str_list(args.common_modes)
        for profile in parse_str_list(args.profiles)
        for eligibility_mode, eligibility_alpha in eligibility_variants
    ]
    if not variants:
        raise ValueError("No variants selected")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "started_at": utc_now(),
        "trials_per_variant": args.trials,
        "variant_count": len(variants),
        "seed": args.seed,
        "shared_slots": args.shared_slots,
        "reserve_limit": reserve_limit,
        "reserve_multiplier": args.reserve_multiplier,
        "admission_floor": args.admission_floor,
        "profiles": parse_str_list(args.profiles),
        "floor_spam_multiplier": args.floor_spam_multiplier,
        "eligibility_modes": parse_str_list(args.eligibility_modes),
        "eligibility_alphas": parse_float_list(args.eligibility_alphas),
        "common_depth_multiplier": args.common_depth_multiplier,
        "score_rules": list(SCORE_RULES),
        "notes": [
            "Side A is always the true hashrate majority.",
            "Proof difficulty above the admission floor is sampled from P(D >= x | D >= floor) = floor / x.",
            "Mature common mode gives both sides an identical pre-split reserve, then lets new split proofs displace the bottom.",
            "Minority floor-flood profiles are adversarial stress tests, not honest hashrate models.",
            "Eligibility filters exclude low-difficulty proofs from state scoring, not from the underlying Work Set.",
        ],
    }
    (args.out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(
        f"Running {len(variants)} consensus-selection variants; "
        f"{args.trials} trials each; reserve={reserve_limit}; jobs={args.jobs}",
        flush=True,
    )
    started_at = time.monotonic()
    rows: list[dict[str, object]] = []

    if args.jobs <= 1:
        try:
            for index, variant in enumerate(variants, start=1):
                print_start(index, len(variants), variant, started_at)
                rows.extend(run_variant(variant, args, reserve_limit, index))
                write_outputs(args.out_dir, rows, metadata, status="running")
                print_done(index, len(variants), variant, started_at)
        except KeyboardInterrupt:
            write_outputs(args.out_dir, rows, metadata, status="interrupted")
            print(f"\nInterrupted. Partial outputs are in {args.out_dir}", flush=True)
            return 130
    else:
        executor = ProcessPoolExecutor(max_workers=args.jobs)
        futures = {}
        try:
            for index, variant in enumerate(variants, start=1):
                future = executor.submit(run_variant, variant, args, reserve_limit, index)
                futures[future] = (index, variant)

            pending = set(futures)
            completed = 0
            while pending:
                done, pending = wait(
                    pending,
                    timeout=max(1.0, args.heartbeat_seconds),
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    print_heartbeat(completed, len(variants), started_at)
                    write_progress(args.out_dir, rows, metadata, status="running")
                    continue

                for future in done:
                    index, variant = futures[future]
                    rows.extend(future.result())
                    completed += 1
                    write_outputs(args.out_dir, rows, metadata, status="running")
                    print_done(completed, len(variants), variant, started_at)
        except KeyboardInterrupt:
            print("\nInterrupt received; terminating workers...", flush=True)
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            write_outputs(args.out_dir, rows, metadata, status="interrupted")
            print(f"Interrupted. Partial outputs are in {args.out_dir}", flush=True)
            return 130
        finally:
            executor.shutdown(wait=True, cancel_futures=False)

    write_outputs(args.out_dir, rows, metadata, status="complete")
    print(f"Wrote consensus-selection report to {args.out_dir / 'report.md'}", flush=True)
    return 0


def run_variant(
    variant: Variant,
    args: argparse.Namespace,
    reserve_limit: int,
    variant_index: int,
) -> list[dict[str, object]]:
    rng = random.Random(args.seed + (variant_index * 1_000_003))
    accumulators: dict[str, dict[str, float]] = {
        rule: fresh_accumulator() for rule in SCORE_RULES
    }
    shared_slots = int(args.shared_slots)
    floor = float(args.admission_floor)
    common_samples = max(0, int(round(reserve_limit * float(args.common_depth_multiplier))))

    for _trial in range(int(args.trials)):
        common = sample_common_reserve(
            rng,
            mode=variant.common_mode,
            reserve_limit=reserve_limit,
            common_samples=common_samples,
            floor=floor,
        )
        side_a_new, side_b_new, side_a_new_count, side_b_new_count = sample_profile_proofs(
            rng,
            variant=variant,
            floor=floor,
            reserve_limit=reserve_limit,
            floor_spam_multiplier=float(args.floor_spam_multiplier),
        )
        side_a = top_reserve(common + side_a_new, reserve_limit)
        side_b = top_reserve(common + side_b_new, reserve_limit)
        side_a_max = max(side_a_new, default=0.0)
        side_b_max = max(side_b_new, default=0.0)
        side_a_score_proofs = filter_score_proofs(
            side_a,
            shared_slots=shared_slots,
            floor=floor,
            mode=variant.eligibility_mode,
            alpha=variant.eligibility_alpha,
        )
        side_b_score_proofs = filter_score_proofs(
            side_b,
            shared_slots=shared_slots,
            floor=floor,
            mode=variant.eligibility_mode,
            alpha=variant.eligibility_alpha,
        )

        for rule, scorer in SCORE_RULES.items():
            score_a = scorer(side_a_score_proofs, shared_slots, floor)
            score_b = scorer(side_b_score_proofs, shared_slots, floor)
            update_accumulator(
                accumulators[rule],
                score_a=score_a,
                score_b=score_b,
                side_a_new_count=side_a_new_count,
                side_b_new_count=side_b_new_count,
                side_a_max=side_a_max,
                side_b_max=side_b_max,
                eligible_a_count=len(side_a_score_proofs),
                eligible_b_count=len(side_b_score_proofs),
            )

    rows: list[dict[str, object]] = []
    for rule, acc in accumulators.items():
        trials = max(1.0, acc["trials"])
        rows.append(
            {
                "majority_share": variant.majority_share,
                "minority_share": 1.0 - variant.majority_share,
                "split_proofs": variant.split_proofs,
                "common_mode": variant.common_mode,
                "profile": variant.profile,
                "eligibility_mode": variant.eligibility_mode,
                "eligibility_alpha": variant.eligibility_alpha,
                "score_rule": rule,
                "trials": int(acc["trials"]),
                "majority_pick_rate": acc["majority_picks"] / trials,
                "minority_pick_rate": acc["minority_picks"] / trials,
                "tie_rate": acc["ties"] / trials,
                "tie_adjusted_accuracy": (acc["majority_picks"] + (0.5 * acc["ties"])) / trials,
                "minority_pick_with_bigger_max_rate": acc["minority_pick_with_bigger_max"] / trials,
                "minority_pick_with_fewer_new_proofs_rate": acc["minority_pick_with_fewer_new_proofs"] / trials,
                "mean_score_margin_ratio": acc["score_margin_ratio_sum"] / trials,
                "mean_new_proof_count_edge": acc["new_proof_count_edge_sum"] / trials,
                "mean_majority_new_proofs": acc["majority_new_proofs_sum"] / trials,
                "mean_minority_new_proofs": acc["minority_new_proofs_sum"] / trials,
                "mean_majority_eligible_proofs": acc["majority_eligible_proofs_sum"] / trials,
                "mean_minority_eligible_proofs": acc["minority_eligible_proofs_sum"] / trials,
            }
        )
    return rows


def filter_score_proofs(
    proofs: list[float],
    *,
    shared_slots: int,
    floor: float,
    mode: str,
    alpha: float,
) -> list[float]:
    if mode == "none":
        return list(proofs)
    if not proofs:
        return []

    ordered = sorted(proofs, reverse=True)
    if mode == "active_snapshot_floor":
        if len(ordered) >= shared_slots:
            anchor = ordered[shared_slots - 1]
        else:
            anchor = floor
    elif mode == "reserve_floor":
        anchor = ordered[-1]
    else:
        raise ValueError(f"Unknown eligibility mode: {mode}")

    threshold = max(floor, anchor * alpha)
    return [proof for proof in proofs if proof >= threshold]


def sample_profile_proofs(
    rng: random.Random,
    *,
    variant: Variant,
    floor: float,
    reserve_limit: int,
    floor_spam_multiplier: float,
) -> tuple[list[float], list[float], int, int]:
    side_a_new_count = sample_poisson(rng, variant.split_proofs * variant.majority_share)
    side_b_new_count = sample_poisson(rng, variant.split_proofs * (1.0 - variant.majority_share))
    side_a_new = [sample_pareto_difficulty(rng, floor) for _ in range(side_a_new_count)]
    side_b_new = [sample_pareto_difficulty(rng, floor) for _ in range(side_b_new_count)]

    if variant.profile == "honest":
        return side_a_new, side_b_new, side_a_new_count, side_b_new_count

    if variant.profile == "minority_floor_flood":
        spam_count = sample_poisson(
            rng,
            max(0.0, variant.split_proofs * (1.0 - variant.majority_share) * floor_spam_multiplier),
        )
        side_b_new.extend([floor for _ in range(spam_count)])
        return side_a_new, side_b_new, side_a_new_count, side_b_new_count + spam_count

    if variant.profile == "minority_reserve_fill":
        target_extra = max(0, reserve_limit - len(side_b_new))
        stochastic_extra = sample_poisson(
            rng,
            max(0.0, variant.split_proofs * (1.0 - variant.majority_share) * floor_spam_multiplier),
        )
        spam_count = target_extra + stochastic_extra
        side_b_new.extend([floor for _ in range(spam_count)])
        return side_a_new, side_b_new, side_a_new_count, side_b_new_count + spam_count

    raise ValueError(f"Unknown profile: {variant.profile}")


def fresh_accumulator() -> dict[str, float]:
    return {
        "trials": 0.0,
        "majority_picks": 0.0,
        "minority_picks": 0.0,
        "ties": 0.0,
        "minority_pick_with_bigger_max": 0.0,
        "minority_pick_with_fewer_new_proofs": 0.0,
        "score_margin_ratio_sum": 0.0,
        "new_proof_count_edge_sum": 0.0,
        "majority_new_proofs_sum": 0.0,
        "minority_new_proofs_sum": 0.0,
        "majority_eligible_proofs_sum": 0.0,
        "minority_eligible_proofs_sum": 0.0,
    }


def update_accumulator(
    acc: dict[str, float],
    *,
    score_a: float,
    score_b: float,
    side_a_new_count: int,
    side_b_new_count: int,
    side_a_max: float,
    side_b_max: float,
    eligible_a_count: int,
    eligible_b_count: int,
) -> None:
    epsilon = 1e-12 * max(1.0, abs(score_a), abs(score_b))
    acc["trials"] += 1.0
    acc["majority_new_proofs_sum"] += side_a_new_count
    acc["minority_new_proofs_sum"] += side_b_new_count
    acc["new_proof_count_edge_sum"] += side_a_new_count - side_b_new_count
    acc["majority_eligible_proofs_sum"] += eligible_a_count
    acc["minority_eligible_proofs_sum"] += eligible_b_count
    acc["score_margin_ratio_sum"] += (score_a - score_b) / max(1.0, abs(score_a), abs(score_b))

    if abs(score_a - score_b) <= epsilon:
        acc["ties"] += 1.0
        return
    if score_a > score_b:
        acc["majority_picks"] += 1.0
        return

    acc["minority_picks"] += 1.0
    if side_b_max > side_a_max:
        acc["minority_pick_with_bigger_max"] += 1.0
    if side_b_new_count < side_a_new_count:
        acc["minority_pick_with_fewer_new_proofs"] += 1.0


def sample_common_reserve(
    rng: random.Random,
    *,
    mode: str,
    reserve_limit: int,
    common_samples: int,
    floor: float,
) -> list[float]:
    if mode == "empty":
        return []
    if mode == "mature":
        return top_reserve(
            [sample_pareto_difficulty(rng, floor) for _ in range(common_samples)],
            reserve_limit,
        )
    raise ValueError(f"Unknown common reserve mode: {mode}")


def top_reserve(proofs: list[float], reserve_limit: int) -> list[float]:
    if len(proofs) <= reserve_limit:
        return list(proofs)
    return sorted(proofs, reverse=True)[:reserve_limit]


def sum_minus_top_count(proofs: list[float], count: int) -> float:
    if not proofs:
        return 0.0
    if count <= 0:
        return math.fsum(proofs)
    ordered = sorted(proofs, reverse=True)
    return math.fsum(ordered[min(count, len(ordered)) :])


def top_trimmed_sum(proofs: list[float], fraction: float) -> float:
    if not proofs:
        return 0.0
    ordered = sorted(proofs, reverse=True)
    trim_count = min(len(ordered), int(math.floor(len(ordered) * fraction)))
    return math.fsum(ordered[trim_count:])


def top_winsorized_sum(proofs: list[float], fraction: float) -> float:
    if not proofs:
        return 0.0
    ordered = sorted(proofs, reverse=True)
    cap_count = int(math.floor(len(ordered) * fraction))
    if cap_count <= 0 or cap_count >= len(ordered):
        return math.fsum(ordered)
    cap = ordered[cap_count]
    return math.fsum(min(proof, cap) for proof in ordered)


def capped_sum(proofs: list[float], *, cap: float) -> float:
    if not proofs:
        return 0.0
    return math.fsum(min(proof, cap) for proof in proofs)


def percentile_times_count(proofs: list[float], percentile: float) -> float:
    if not proofs:
        return 0.0
    ordered = sorted(proofs)
    index = int(round((len(ordered) - 1) * percentile))
    index = max(0, min(len(ordered) - 1, index))
    return ordered[index] * len(ordered)


def bottom_mean_times_count(proofs: list[float], count: int) -> float:
    if not proofs:
        return 0.0
    ordered = sorted(proofs)
    selected = ordered[: max(1, min(count, len(ordered)))]
    return (math.fsum(selected) / len(selected)) * len(ordered)


def write_outputs(
    out_dir: Path,
    rows: list[dict[str, object]],
    metadata: dict[str, object],
    *,
    status: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_results_csv(out_dir / "consensus_selection_results.csv", rows)
    write_summary_csv(out_dir / "summary_by_rule.csv", summarize_by_rule(rows))
    write_profile_summary_csv(
        out_dir / "summary_by_profile_and_rule.csv",
        summarize_by_profile_and_rule(rows),
    )
    write_report(out_dir / "report.md", rows, metadata, status=status)
    write_charts(out_dir / "charts", rows)
    write_progress(out_dir, rows, metadata, status=status)


def write_results_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "majority_share",
        "minority_share",
        "split_proofs",
        "common_mode",
        "profile",
        "eligibility_mode",
        "eligibility_alpha",
        "score_rule",
        "trials",
        "majority_pick_rate",
        "minority_pick_rate",
        "tie_rate",
        "tie_adjusted_accuracy",
        "minority_pick_with_bigger_max_rate",
        "minority_pick_with_fewer_new_proofs_rate",
        "mean_score_margin_ratio",
        "mean_new_proof_count_edge",
        "mean_majority_new_proofs",
        "mean_minority_new_proofs",
        "mean_majority_eligible_proofs",
        "mean_minority_eligible_proofs",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_by_rule(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for rule in sorted({str(row["score_rule"]) for row in rows}):
        rule_rows = [row for row in rows if row["score_rule"] == rule]
        if not rule_rows:
            continue
        output.append(
            {
                "score_rule": rule,
                "variants": len(rule_rows),
                "mean_tie_adjusted_accuracy": mean_field(rule_rows, "tie_adjusted_accuracy"),
                "mean_minority_pick_rate": mean_field(rule_rows, "minority_pick_rate"),
                "mean_tie_rate": mean_field(rule_rows, "tie_rate"),
                "mean_minority_pick_with_bigger_max_rate": mean_field(
                    rule_rows,
                    "minority_pick_with_bigger_max_rate",
                ),
                "mean_minority_pick_with_fewer_new_proofs_rate": mean_field(
                    rule_rows,
                    "minority_pick_with_fewer_new_proofs_rate",
                ),
                "worst_tie_adjusted_accuracy": min(float(row["tie_adjusted_accuracy"]) for row in rule_rows),
                "worst_case": describe_worst_case(rule_rows),
            }
        )
    output.sort(
        key=lambda row: (
            -float(row["mean_tie_adjusted_accuracy"]),
            float(row["mean_minority_pick_rate"]),
            float(row["mean_minority_pick_with_bigger_max_rate"]),
        )
    )
    return output


def summarize_by_profile_and_rule(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    groups = sorted({
        (
            str(row["profile"]),
            str(row.get("eligibility_mode", "none")),
            float(row.get("eligibility_alpha", 0.0)),
        )
        for row in rows
    })
    for profile, eligibility_mode, eligibility_alpha in groups:
        group_rows = [
            row
            for row in rows
            if row["profile"] == profile
            and row.get("eligibility_mode", "none") == eligibility_mode
            and float(row.get("eligibility_alpha", 0.0)) == eligibility_alpha
        ]
        for row in summarize_by_rule(group_rows):
            clone = dict(row)
            clone["profile"] = profile
            clone["eligibility_mode"] = eligibility_mode
            clone["eligibility_alpha"] = eligibility_alpha
            output.append(clone)
    output.sort(
        key=lambda row: (
            str(row["profile"]),
            str(row["eligibility_mode"]),
            float(row["eligibility_alpha"]),
            -float(row["mean_tie_adjusted_accuracy"]),
            float(row["mean_minority_pick_rate"]),
            float(row["mean_minority_pick_with_bigger_max_rate"]),
        )
    )
    return output


def write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "score_rule",
        "variants",
        "mean_tie_adjusted_accuracy",
        "mean_minority_pick_rate",
        "mean_tie_rate",
        "mean_minority_pick_with_bigger_max_rate",
        "mean_minority_pick_with_fewer_new_proofs_rate",
        "worst_tie_adjusted_accuracy",
        "worst_case",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_profile_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "profile",
        "eligibility_mode",
        "eligibility_alpha",
        "score_rule",
        "variants",
        "mean_tie_adjusted_accuracy",
        "mean_minority_pick_rate",
        "mean_tie_rate",
        "mean_minority_pick_with_bigger_max_rate",
        "mean_minority_pick_with_fewer_new_proofs_rate",
        "worst_tie_adjusted_accuracy",
        "worst_case",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    rows: list[dict[str, object]],
    metadata: dict[str, object],
    *,
    status: str,
) -> None:
    summary = summarize_by_rule(rows)
    lines = [
        "# Consensus Selection Audit Simulation",
        "",
        f"Status: `{status}`.",
        "",
        "This run compares candidate-state scoring rules for GridPool's heaviest-state convergence rule.",
        "Side A is always the true hashrate majority; side B is the minority.",
        "",
        "The model samples proof difficulty from the GridPool proof-of-work tail:",
        "",
        "```text",
        "P(D >= x | D >= floor) = floor / x",
        "```",
        "",
        "That heavy tail is exactly why this question matters: one valid outlier proof can dominate raw summed difficulty.",
        "",
        "## Run Parameters",
        "",
        f"- Trials per variant: `{metadata.get('trials_per_variant')}`",
        f"- Variants: `{metadata.get('variant_count')}`",
        f"- Shared slots: `{metadata.get('shared_slots')}`",
        f"- Reserve limit: `{metadata.get('reserve_limit')}`",
        f"- Admission floor: `{metadata.get('admission_floor')}`",
        f"- Common reserve depth multiplier: `{metadata.get('common_depth_multiplier')}`",
        f"- Profiles: `{', '.join(str(item) for item in metadata.get('profiles', []))}`",
        f"- Floor spam multiplier: `{metadata.get('floor_spam_multiplier')}`",
        f"- Eligibility modes: `{', '.join(str(item) for item in metadata.get('eligibility_modes', []))}`",
        f"- Eligibility alphas: `{', '.join(str(item) for item in metadata.get('eligibility_alphas', []))}`",
        "",
        "## Score Rule Ranking",
        "",
        "| Rule | Mean Tie-Adjusted Accuracy | Mean Minority Pick | Monster-Minority Pick | Fewer-Proofs Minority Pick | Worst Accuracy | Worst Case |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary:
        lines.append(
            "| `{rule}` | {accuracy:.4%} | {minority:.4%} | {monster:.4%} | {fewer:.4%} | {worst:.4%} | {case} |".format(
                rule=row["score_rule"],
                accuracy=float(row["mean_tie_adjusted_accuracy"]),
                minority=float(row["mean_minority_pick_rate"]),
                monster=float(row["mean_minority_pick_with_bigger_max_rate"]),
                fewer=float(row["mean_minority_pick_with_fewer_new_proofs_rate"]),
                worst=float(row["worst_tie_adjusted_accuracy"]),
                case=row["worst_case"],
            )
        )
    profile_summary = summarize_by_profile_and_rule(rows)
    if profile_summary:
        lines.extend([
            "",
            "## Profile And Eligibility Leaders",
            "",
            "| Profile | Eligibility | Alpha | Best Rule | Mean Tie-Adjusted Accuracy | Mean Minority Pick | Monster-Minority Pick |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: |",
        ])
        groups = sorted({
            (
                str(row["profile"]),
                str(row["eligibility_mode"]),
                float(row["eligibility_alpha"]),
            )
            for row in profile_summary
        })
        for profile, eligibility_mode, eligibility_alpha in groups:
            group_rows = [
                row
                for row in profile_summary
                if row["profile"] == profile
                and row["eligibility_mode"] == eligibility_mode
                and float(row["eligibility_alpha"]) == eligibility_alpha
            ]
            if not group_rows:
                continue
            row = group_rows[0]
            lines.append(
                "| `{profile}` | `{eligibility}` | {alpha:g} | `{rule}` | {accuracy:.4%} | {minority:.4%} | {monster:.4%} |".format(
                    profile=profile,
                    eligibility=eligibility_mode,
                    alpha=eligibility_alpha,
                    rule=row["score_rule"],
                    accuracy=float(row["mean_tie_adjusted_accuracy"]),
                    minority=float(row["mean_minority_pick_rate"]),
                    monster=float(row["mean_minority_pick_with_bigger_max_rate"]),
                )
            )
    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- `sum_workset_difficulty` approximates the current production rule.",
            "- `snapshot_sum_difficulty` tests whether scoring only the active payout snapshot behaves differently from scoring the full reserve.",
            "- `sum_minus_top_N` tests the simple idea of stripping the largest Poisson outliers before summing.",
            "- `bottom_N_mean_times_count` and percentile rules use the retained reserve floor as a compact order-statistic hashrate estimator.",
            "- Trimmed and winsorized sums test whether clipping the heaviest tail improves convergence toward the larger active team.",
            "- `minority_floor_flood` and `minority_reserve_fill` are adversarial stress profiles; if a score picks the minority there, it may overweight low-difficulty proof count.",
            "- `count_only` is intentionally included as a baseline; it usually fails when mature reserves have equal proof counts.",
            "- A minority pick is not necessarily theft. The minority proof is still valid work. This test asks a narrower convergence question: which score best predicts the side with more active hashrate during a split?",
            "",
            "## Outputs",
            "",
            "- `consensus_selection_results.csv`: all variant/rule rows.",
            "- `summary_by_rule.csv`: aggregate rule ranking.",
            "- `summary_by_profile_and_rule.csv`: rule ranking split by trial profile.",
            "- `charts/index.html`: quick SVG chart index.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_progress(
    out_dir: Path,
    rows: list[dict[str, object]],
    metadata: dict[str, object],
    *,
    status: str,
) -> None:
    completed_variants = len({
        (
            row.get("majority_share"),
            row.get("split_proofs"),
            row.get("common_mode"),
            row.get("profile"),
            row.get("eligibility_mode"),
            row.get("eligibility_alpha"),
        )
        for row in rows
    })
    payload = {
        "status": status,
        "updated_at": utc_now(),
        "completed_variants": completed_variants,
        "total_variants": metadata.get("variant_count"),
        "rows": len(rows),
    }
    (out_dir / "progress.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (out_dir / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def write_charts(out_dir: Path, rows: list[dict[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.svg"):
        stale.unlink()

    charts: list[Path] = []
    chart_groups = sorted({
        (
            str(row["profile"]),
            str(row["common_mode"]),
            str(row.get("eligibility_mode", "none")),
            float(row.get("eligibility_alpha", 0.0)),
        )
        for row in rows
    })
    for profile, common_mode, eligibility_mode, eligibility_alpha in chart_groups:
        mode_rows = [
            row
            for row in rows
            if row["profile"] == profile
            and row["common_mode"] == common_mode
            and row.get("eligibility_mode", "none") == eligibility_mode
            and float(row.get("eligibility_alpha", 0.0)) == eligibility_alpha
        ]
        if not mode_rows:
            continue
        max_split = max(float(row["split_proofs"]) for row in mode_rows)
        filtered = [row for row in mode_rows if float(row["split_proofs"]) == max_split]
        eligibility_slug = f"{eligibility_mode}_{slug_number(eligibility_alpha)}"
        eligibility_title = f"{eligibility_mode}:{eligibility_alpha:g}"
        charts.append(
            write_line_chart(
                out_dir / f"accuracy_{profile}_{common_mode}_{eligibility_slug}_split_{slug_number(max_split)}.svg",
                title=f"Consensus Selection Accuracy ({profile}, {common_mode}, {eligibility_title})",
                subtitle=f"Tie-adjusted accuracy by true majority share. Split window: {max_split:g} expected proofs. Chart shows selected rules.",
                x_label="True hashrate share of side A",
                y_label="Tie-adjusted accuracy",
                rows=filtered,
                y_key="tie_adjusted_accuracy",
                y_min=0.0,
                y_max=1.0,
            )
        )
        charts.append(
            write_line_chart(
                out_dir / f"minority_picks_{profile}_{common_mode}_{eligibility_slug}_split_{slug_number(max_split)}.svg",
                title=f"Minority State Pick Rate ({profile}, {common_mode}, {eligibility_title})",
                subtitle=f"Lower is better for active-hashrate convergence. Split window: {max_split:g} expected proofs. Chart shows selected rules.",
                x_label="True hashrate share of side A",
                y_label="Minority pick rate",
                rows=filtered,
                y_key="minority_pick_rate",
                y_min=0.0,
                y_max=1.0,
            )
        )

    write_chart_index(out_dir, charts)


def write_line_chart(
    path: Path,
    *,
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    rows: list[dict[str, object]],
    y_key: str,
    y_min: float,
    y_max: float,
) -> Path:
    if not rows:
        path.write_text("", encoding="utf-8")
        return path

    width = 920
    height = 520
    left = 86
    right = 28
    top = 76
    bottom = 76
    plot_w = width - left - right
    plot_h = height - top - bottom
    x_values = sorted({float(row["majority_share"]) for row in rows})
    x_min = min(x_values)
    x_max = max(x_values)
    available_rules = {str(row["score_rule"]) for row in rows}
    rules = [rule for rule in CHART_SCORE_RULES if rule in available_rules]
    if not rules:
        rules = sorted(available_rules)
    palette = [
        "#62a0ea",
        "#33d17a",
        "#f6d32d",
        "#ff7800",
        "#dc8add",
        "#5bc8af",
        "#e01b24",
        "#c0bfbc",
        "#8ff0a4",
        "#99c1f1",
    ]

    def x_coord(value: float) -> float:
        if x_max == x_min:
            return left + (plot_w / 2)
        return left + ((value - x_min) / (x_max - x_min) * plot_w)

    def y_coord(value: float) -> float:
        bounded = max(y_min, min(y_max, value))
        return top + ((y_max - bounded) / (y_max - y_min) * plot_h)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#111318"/>',
        f'<text x="{left}" y="30" fill="#eeeeec" font-family="monospace" font-size="20">{html.escape(title)}</text>',
        f'<text x="{left}" y="54" fill="#c0bfbc" font-family="monospace" font-size="12">{html.escape(subtitle)}</text>',
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#181b22" stroke="#3d414d"/>',
    ]
    for tick in range(0, 6):
        y_value = y_min + ((y_max - y_min) * tick / 5)
        y = y_coord(y_value)
        parts.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y:.2f}" y2="{y:.2f}" stroke="#2a2d36"/>')
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.2f}" fill="#c0bfbc" font-family="monospace" font-size="11" text-anchor="end">{y_value:.0%}</text>'
        )
    for x_value in x_values:
        x = x_coord(x_value)
        parts.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{top}" y2="{top + plot_h}" stroke="#222630"/>')
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_h + 22}" fill="#c0bfbc" font-family="monospace" font-size="11" text-anchor="middle">{x_value:.0%}</text>'
        )

    for index, rule in enumerate(rules):
        color = palette[index % len(palette)]
        points = []
        by_x = {
            float(row["majority_share"]): float(row[y_key])
            for row in rows
            if str(row["score_rule"]) == rule
        }
        for x_value in x_values:
            if x_value in by_x:
                points.append(f"{x_coord(x_value):.2f},{y_coord(by_x[x_value]):.2f}")
        if len(points) >= 2:
            parts.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2.4" points="{" ".join(points)}"/>'
            )
        for point in points:
            x, y = point.split(",")
            parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>')

    legend_x = left + 12
    legend_y = top + 18
    for index, rule in enumerate(rules):
        color = palette[index % len(palette)]
        y = legend_y + (index * 18)
        parts.append(f'<rect x="{legend_x}" y="{y - 9}" width="10" height="10" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 16}" y="{y}" fill="#eeeeec" font-family="monospace" font-size="11">{html.escape(rule)}</text>'
        )

    parts.append(
        f'<text x="{left + plot_w / 2}" y="{height - 22}" fill="#eeeeec" font-family="monospace" font-size="13" text-anchor="middle">{html.escape(x_label)}</text>'
    )
    parts.append(
        f'<text transform="translate(22 {top + plot_h / 2}) rotate(-90)" fill="#eeeeec" font-family="monospace" font-size="13" text-anchor="middle">{html.escape(y_label)}</text>'
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def write_chart_index(out_dir: Path, charts: list[Path]) -> None:
    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>Consensus Selection Charts</title>",
        "<style>body{background:#111318;color:#eeeeec;font-family:monospace;margin:24px} img{max-width:100%;display:block;margin:16px 0 32px;border:1px solid #3d414d}</style>",
        "</head><body>",
        "<h1>Consensus Selection Charts</h1>",
    ]
    for chart in charts:
        if chart.exists() and chart.stat().st_size > 0:
            lines.append(f"<h2>{html.escape(chart.name)}</h2>")
            lines.append(f"<img src='{html.escape(chart.name)}' alt='{html.escape(chart.name)}'>")
    lines.append("</body></html>")
    (out_dir / "index.html").write_text("\n".join(lines), encoding="utf-8")


def mean_field(rows: list[dict[str, object]], field: str) -> float:
    values = [float(row[field]) for row in rows]
    return sum(values) / len(values) if values else 0.0


def describe_worst_case(rows: list[dict[str, object]]) -> str:
    row = min(rows, key=lambda item: float(item["tie_adjusted_accuracy"]))
    return (
        f"majority={float(row['majority_share']):.0%}, "
        f"split_proofs={float(row['split_proofs']):g}, "
        f"common={row['common_mode']}, "
        f"profile={row['profile']}, "
        f"eligibility={row.get('eligibility_mode', 'none')}:{float(row.get('eligibility_alpha', 0.0)):g}"
    )


def print_start(index: int, total: int, variant: Variant, started_at: float) -> None:
    print(
        f"[{index}/{total}] start majority={variant.majority_share:.0%} "
        f"split_proofs={variant.split_proofs:g} common={variant.common_mode} "
        f"profile={variant.profile} eligibility={variant.eligibility_mode}:{variant.eligibility_alpha:g} "
        f"(elapsed {format_duration(time.monotonic() - started_at)})",
        flush=True,
    )


def print_done(index: int, total: int, variant: Variant, started_at: float) -> None:
    eta = estimate_eta(total, index, started_at)
    eta_text = format_duration(eta) if eta is not None else "unknown"
    print(
        f"[{index}/{total}] done majority={variant.majority_share:.0%} "
        f"split_proofs={variant.split_proofs:g} common={variant.common_mode} "
        f"profile={variant.profile} eligibility={variant.eligibility_mode}:{variant.eligibility_alpha:g}; ETA {eta_text}",
        flush=True,
    )


def print_heartbeat(completed: int, total: int, started_at: float) -> None:
    eta = estimate_eta(total, completed, started_at)
    eta_text = format_duration(eta) if eta is not None else "unknown"
    print(
        f"[heartbeat] completed {completed}/{total}; "
        f"elapsed {format_duration(time.monotonic() - started_at)}; ETA {eta_text}",
        flush=True,
    )


def estimate_eta(total: int, completed: int, started_at: float) -> float | None:
    if completed <= 0:
        return None
    elapsed = time.monotonic() - started_at
    rate = completed / elapsed if elapsed > 0 else 0.0
    if rate <= 0:
        return None
    return max(0.0, (total - completed) / rate)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minute:02d}m{sec:02d}s"
    if minute:
        return f"{minute}m{sec:02d}s"
    return f"{sec}s"


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_str_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_eligibility_variants(modes: list[str], alphas: list[float]) -> list[tuple[str, float]]:
    valid_modes = {"none", "active_snapshot_floor", "reserve_floor"}
    output: list[tuple[str, float]] = []
    for mode in modes:
        if mode not in valid_modes:
            raise ValueError(f"Unknown eligibility mode: {mode}")
        if mode == "none":
            output.append((mode, 0.0))
            continue
        for alpha in alphas:
            if alpha < 0:
                raise ValueError("Eligibility alpha must be non-negative")
            output.append((mode, alpha))
    deduped: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for item in output:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def slug_number(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

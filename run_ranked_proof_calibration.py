#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import random
from statistics import mean, pstdev
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate ranked-proof aggregate work estimation and per-miner sampling "
            "accuracy using exact order-statistic and binomial distributions."
        )
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=100_000)
    parser.add_argument("--share-counts", default="10000,1000000")
    parser.add_argument("--rank-counts", default="10,30,100,299,897")
    parser.add_argument("--list-sizes", default="10,30,100,299,897")
    parser.add_argument("--expected-miner-slots", default="0.1,0.3,1,3,10,30,100,300")
    parser.add_argument("--seed", type=int, default=21041)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.trials = min(args.trials, 3000)
        args.share_counts = "10000"
        args.rank_counts = "10,100,897"
        args.list_sizes = "299,897"
        args.expected_miner_slots = "0.3,1,10,100"

    share_counts = parse_int_list(args.share_counts)
    rank_counts = parse_int_list(args.rank_counts)
    list_sizes = parse_int_list(args.list_sizes)
    expected_slots = parse_float_list(args.expected_miner_slots)
    if min(rank_counts + list_sizes) < 3:
        raise SystemExit("Rank/list sizes must be at least 3 for finite inverse-order-statistic variance.")
    if any(rank > share_count for rank in rank_counts for share_count in share_counts):
        raise SystemExit("Every --rank-counts value must be <= every --share-counts value.")

    aggregate_rows = run_aggregate_calibration(args.trials, share_counts, rank_counts, args.seed)
    miner_rows = run_miner_calibration(args.trials, list_sizes, expected_slots, args.seed + 1_000_000)
    churn_rows = run_churn_calibration(args.trials, max(list_sizes), args.seed + 2_000_000)
    write_outputs(args.out_dir, args, aggregate_rows, miner_rows, churn_rows)
    print(f"Wrote ranked-proof calibration report to {args.out_dir / 'report.md'}")
    return 0


def run_aggregate_calibration(
    trials: int,
    share_counts: list[int],
    rank_counts: list[int],
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for share_index, share_count in enumerate(share_counts):
        for rank_index, rank_count in enumerate(rank_counts):
            rng = random.Random(seed + share_index * 100_000 + rank_index)
            naive_ratios: list[float] = []
            corrected_ratios: list[float] = []
            for _ in range(trials):
                cutoff = rng.betavariate(rank_count, share_count - rank_count + 1)
                naive_ratios.append((rank_count / cutoff) / share_count)
                corrected_ratios.append(((rank_count - 1) / cutoff) / share_count)

            theoretical_corrected_rse = math.sqrt(
                (share_count - rank_count + 1) / (share_count * (rank_count - 2))
            )
            rows.append(
                {
                    "total_submitted_shares": share_count,
                    "retained_rank": rank_count,
                    "trials": trials,
                    "naive_mean_ratio": mean(naive_ratios),
                    "naive_relative_bias": mean(naive_ratios) - 1.0,
                    "naive_empirical_rse": pstdev(naive_ratios),
                    "naive_theoretical_mean_ratio": rank_count / (rank_count - 1),
                    "corrected_mean_ratio": mean(corrected_ratios),
                    "corrected_relative_bias": mean(corrected_ratios) - 1.0,
                    "corrected_empirical_rse": pstdev(corrected_ratios),
                    "corrected_theoretical_rse": theoretical_corrected_rse,
                    "approximate_one_over_sqrt_m": 1.0 / math.sqrt(rank_count),
                    "corrected_p05_ratio": percentile(corrected_ratios, 5),
                    "corrected_p50_ratio": percentile(corrected_ratios, 50),
                    "corrected_p95_ratio": percentile(corrected_ratios, 95),
                }
            )
            print(
                f"[ranked-proof] aggregate S={share_count} m={rank_count} trials={trials} done",
                flush=True,
            )
    return rows


def run_miner_calibration(
    trials: int,
    list_sizes: list[int],
    expected_slots_values: list[float],
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    variant = 0
    for list_size in list_sizes:
        for expected_slots in expected_slots_values:
            if expected_slots > list_size:
                continue
            miner_share = expected_slots / list_size
            rng = random.Random(seed + variant)
            variant += 1
            counts = [sample_binomial(rng, list_size, miner_share) for _ in range(trials)]
            share_estimates = [count / list_size for count in counts]
            theoretical_rse = (
                math.sqrt((1.0 - miner_share) / (list_size * miner_share))
                if miner_share > 0
                else math.inf
            )
            theoretical_zero = (1.0 - miner_share) ** list_size
            rows.append(
                {
                    "list_size": list_size,
                    "expected_miner_slots": expected_slots,
                    "true_cumulative_work_share": miner_share,
                    "trials": trials,
                    "empirical_mean_slots": mean(counts),
                    "empirical_mean_share": mean(share_estimates),
                    "empirical_relative_bias": mean(share_estimates) / miner_share - 1.0,
                    "empirical_relative_sampling_error": pstdev(share_estimates) / miner_share,
                    "theoretical_relative_sampling_error": theoretical_rse,
                    "empirical_zero_slot_probability": sum(count == 0 for count in counts) / trials,
                    "theoretical_zero_slot_probability": theoretical_zero,
                    "slot_count_p05": percentile(counts, 5),
                    "slot_count_p50": percentile(counts, 50),
                    "slot_count_p95": percentile(counts, 95),
                }
            )
            print(
                f"[ranked-proof] miner list={list_size} expected_slots={expected_slots:g} trials={trials} done",
                flush=True,
            )
    return rows


def run_churn_calibration(trials: int, list_size: int, seed: int) -> list[dict[str, Any]]:
    scenarios = [
        (0.001, 0.001),
        (0.001, 0.01),
        (0.001, 0.10),
        (0.10, 0.001),
        (0.10, 0.01),
        (0.10, 0.10),
    ]
    rows: list[dict[str, Any]] = []
    for index, (first_phase_share, second_phase_share) in enumerate(scenarios):
        # Equal-work phases make the retained-label probability the arithmetic
        # mean. The reserve estimates cumulative work, not the final phase rate.
        cumulative_share = (first_phase_share + second_phase_share) / 2.0
        rng = random.Random(seed + index)
        estimates = [sample_binomial(rng, list_size, cumulative_share) / list_size for _ in range(trials)]
        estimate_mean = mean(estimates)
        rows.append(
            {
                "list_size": list_size,
                "first_phase_share": first_phase_share,
                "second_phase_current_share": second_phase_share,
                "cumulative_work_share": cumulative_share,
                "empirical_mean_estimate": estimate_mean,
                "bias_vs_cumulative_work_share": estimate_mean - cumulative_share,
                "difference_vs_current_share": estimate_mean - second_phase_share,
                "empirical_relative_error_vs_cumulative": pstdev(estimates) / cumulative_share,
                "zero_slot_probability": sum(value == 0.0 for value in estimates) / trials,
            }
        )
    return rows


def sample_binomial(rng: random.Random, n: int, p: float) -> int:
    if p <= 0.0:
        return 0
    if p >= 1.0:
        return n
    if p > 0.5:
        return n - sample_binomial(rng, n, 1.0 - p)

    q = 1.0 - p
    probability = q**n
    marker = rng.random()
    cumulative = probability
    count = 0
    while marker > cumulative and count < n:
        count += 1
        probability *= ((n - count + 1) / count) * (p / q)
        cumulative += probability
    return count


def write_outputs(
    out_dir: Path,
    args: argparse.Namespace,
    aggregate_rows: list[dict[str, Any]],
    miner_rows: list[dict[str, Any]],
    churn_rows: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dict_csv(out_dir / "aggregate_order_statistic_calibration.csv", aggregate_rows)
    write_dict_csv(out_dir / "per_miner_sampling_calibration.csv", miner_rows)
    write_dict_csv(out_dir / "hashrate_churn_calibration.csv", churn_rows)
    summary = {
        "scenario": {
            "trials": args.trials,
            "share_counts": parse_int_list(args.share_counts),
            "rank_counts": parse_int_list(args.rank_counts),
            "list_sizes": parse_int_list(args.list_sizes),
            "expected_miner_slots": parse_float_list(args.expected_miner_slots),
            "seed": args.seed,
        },
        "aggregate_order_statistic": aggregate_rows,
        "per_miner_sampling": miner_rows,
        "hashrate_churn": churn_rows,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_report(out_dir / "report.md", summary)
    write_aggregate_svg(out_dir / "aggregate_estimator_rse.svg", aggregate_rows)
    write_miner_svg(out_dir / "per_miner_sampling_rse.svg", miner_rows)


def write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, summary: dict[str, Any]) -> None:
    scenario = summary["scenario"]
    largest_share_count = max(scenario["share_counts"])
    aggregate = [
        row for row in summary["aggregate_order_statistic"] if row["total_submitted_shares"] == largest_share_count
    ]
    largest_list = max(scenario["list_sizes"])
    miner = [row for row in summary["per_miner_sampling"] if row["list_size"] == largest_list]
    lines = [
        "# Ranked-Proof Work And Miner-Sampling Calibration",
        "",
        "Status: generated by `run_ranked_proof_calibration.py`.",
        "",
        "## Two Different Error Questions",
        "",
        "1. The difficulty of the `m`th-ranked proof estimates aggregate cumulative work. "
        "Its relative uncertainty is approximately `1/sqrt(m)`.",
        "2. A miner's identity count inside a fixed retained list estimates that miner's "
        "cumulative fraction of the work. Its relative sampling error is approximately "
        "`sqrt((1-p)/(m*p))`, where `m*p` is the miner's expected retained-slot count.",
        "",
        "The aggregate reserve can therefore estimate total work accurately while a tiny "
        "miner's individual representation remains deliberately lottery-like. The miner "
        "estimate is unbiased in expectation, but it is not a precise instantaneous hashrate meter.",
        "",
        "## Aggregate Work Estimator",
        "",
        f"The table below uses `S={largest_share_count:,}` submitted shares and `{scenario['trials']:,}` trials per rank.",
        "",
        "| Retained Rank m | Naive Bias m/V | Corrected Bias (m-1)/V | Empirical Corrected RSE | Exact Corrected RSE | 1/sqrt(m) | 5%-95% Estimate Ratio |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate:
        lines.append(
            "| {m} | {nb:.4%} | {cb:.4%} | {er:.4%} | {tr:.4%} | {approx:.4%} | {p05:.3f}-{p95:.3f} |".format(
                m=row["retained_rank"],
                nb=row["naive_relative_bias"],
                cb=row["corrected_relative_bias"],
                er=row["corrected_empirical_rse"],
                tr=row["corrected_theoretical_rse"],
                approx=row["approximate_one_over_sqrt_m"],
                p05=row["corrected_p05_ratio"],
                p95=row["corrected_p95_ratio"],
            )
        )
    lines.extend(
        [
            "",
            "## Per-Miner Sampling Inside The Reserve",
            "",
            f"The table below uses a `{largest_list}`-proof retained reserve.",
            "",
            "| Expected Miner Proofs | Miner Work Share | Empirical Relative Error | Theoretical Relative Error | Probability Of Zero Proofs | Median Proofs | 5%-95% Proofs |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in miner:
        lines.append(
            "| {slots:g} | {share:.5%} | {er:.2%} | {tr:.2%} | {zero:.2%} | {median:.1f} | {p05:.1f}-{p95:.1f} |".format(
                slots=row["expected_miner_slots"],
                share=row["true_cumulative_work_share"],
                er=row["empirical_relative_sampling_error"],
                tr=row["theoretical_relative_sampling_error"],
                zero=row["empirical_zero_slot_probability"],
                median=row["slot_count_p50"],
                p05=row["slot_count_p05"],
                p95=row["slot_count_p95"],
            )
        )
    lines.extend(
        [
            "",
            "## Hashrate Churn",
            "",
            "With equal-work phases, retained miner labels estimate the average cumulative work share across both phases. "
            "They do not jump immediately to the second phase's current hashrate. This is a feature of the accounting "
            "window and a reason the UI should label reserve-derived per-miner values as cumulative or estimated, not instantaneous.",
            "",
            "## Fairness Interpretation",
            "",
            "High per-miner sampling variance does not imply biased payout attribution. Each retained position has miner "
            "probability `p`, so expected positions equal `m*p`. Small miners frequently receive zero positions and "
            "occasionally receive one or more; larger miners receive enough observations for relative error to fall as "
            "the square root of expected positions. Actual multi-block BTC variance is handled by the separate payout-variance model.",
            "",
            "## Limits",
            "",
            "- The order-statistic calculation assumes independent hashes and a fixed observation window.",
            "- Per-miner label sampling assumes honest attribution and miner-independent proof quality.",
            "- Snapshot positions are correlated across real GridPool blocks because unpaid proofs carry forward; this script does not replace the actual BTC payout-variance model.",
            "- The reserve estimates accumulated work over its effective history, not instantaneous hashrate after abrupt joins or departures.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_aggregate_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    largest_share_count = max(row["total_submitted_shares"] for row in rows)
    selected = sorted(
        (row for row in rows if row["total_submitted_shares"] == largest_share_count),
        key=lambda row: row["retained_rank"],
    )
    write_log_line_svg(
        path,
        selected,
        x_key="retained_rank",
        series=[("corrected_empirical_rse", "Empirical", "#12a594"), ("corrected_theoretical_rse", "Exact", "#f0a830")],
        title="Aggregate work-estimator relative error",
        x_label="Retained rank m (log scale)",
        y_label="Relative standard error",
        y_percent=True,
    )


def write_miner_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    largest_list = max(row["list_size"] for row in rows)
    selected = sorted(
        (row for row in rows if row["list_size"] == largest_list),
        key=lambda row: row["expected_miner_slots"],
    )
    write_log_line_svg(
        path,
        selected,
        x_key="expected_miner_slots",
        series=[
            ("empirical_relative_sampling_error", "Empirical", "#12a594"),
            ("theoretical_relative_sampling_error", "Binomial theory", "#f0a830"),
        ],
        title=f"Per-miner sampling error in a {largest_list}-proof reserve",
        x_label="Expected retained proofs for miner (log scale)",
        y_label="Relative sampling error",
        y_percent=True,
    )


def write_log_line_svg(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    x_key: str,
    series: list[tuple[str, str, str]],
    title: str,
    x_label: str,
    y_label: str,
    y_percent: bool,
) -> None:
    width, height = 1000, 620
    left, right, top, bottom = 110, 40, 80, 90
    chart_w, chart_h = width - left - right, height - top - bottom
    x_values = [float(row[x_key]) for row in rows]
    y_values = [float(row[key]) for row in rows for key, _, _ in series]
    x_min, x_max = min(x_values), max(x_values)
    y_max = max(y_values) * 1.08

    def x_pos(value: float) -> float:
        if x_min == x_max:
            return left + chart_w / 2
        return left + (math.log(value) - math.log(x_min)) / (math.log(x_max) - math.log(x_min)) * chart_w

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
        label = f"{value:.0%}" if y_percent else f"{value:.3g}"
        parts.extend(
            [
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}" stroke="#274044" stroke-width="1"/>',
                f'<text x="{left - 12}" y="{y + 5:.2f}" text-anchor="end" fill="#a9bdba" font-family="sans-serif" font-size="14">{label}</text>',
            ]
        )
    for value in x_values:
        x = x_pos(value)
        parts.extend(
            [
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + chart_h}" stroke="#1b3033" stroke-width="1"/>',
                f'<text x="{x:.2f}" y="{top + chart_h + 25}" text-anchor="middle" fill="#a9bdba" font-family="sans-serif" font-size="14">{value:g}</text>',
            ]
        )
    for index, (key, label, color) in enumerate(series):
        points = " ".join(f"{x_pos(float(row[x_key])):.2f},{y_pos(float(row[key])):.2f}" for row in rows)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="4"/>')
        for row in rows:
            parts.append(
                f'<circle cx="{x_pos(float(row[x_key])):.2f}" cy="{y_pos(float(row[key])):.2f}" r="5" fill="{color}"/>'
            )
        legend_x = left + index * 220
        parts.extend(
            [
                f'<line x1="{legend_x}" y1="{height - 25}" x2="{legend_x + 35}" y2="{height - 25}" stroke="{color}" stroke-width="4"/>',
                f'<text x="{legend_x + 45}" y="{height - 20}" fill="#d8e3df" font-family="sans-serif" font-size="15">{label}</text>',
            ]
        )
    parts.extend(
        [
            f'<text x="{left + chart_w / 2}" y="{height - 52}" text-anchor="middle" fill="#d8e3df" font-family="sans-serif" font-size="16">{x_label}</text>',
            f'<text x="26" y="{top + chart_h / 2}" transform="rotate(-90 26 {top + chart_h / 2})" text-anchor="middle" fill="#d8e3df" font-family="sans-serif" font-size="16">{y_label}</text>',
            '</svg>',
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def percentile(values: list[float] | list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = p / 100.0 * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


if __name__ == "__main__":
    raise SystemExit(main())

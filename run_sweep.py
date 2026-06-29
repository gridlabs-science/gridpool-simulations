#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.adversary import MajorityAdversarySimulator, aggregate_adversary_results
from gridpool_sim.adversary_reporting import expected_network_ev_by_miner as expected_adversary_ev
from gridpool_sim.engine import GridPoolSimulator, aggregate_results
from gridpool_sim.network import NetworkLatencySimulator, relay_profiles_from_config
from gridpool_sim.network_reporting import aggregate_latency_results
from gridpool_sim.reporting import (
    expected_network_ev_by_miner as expected_economic_ev,
    paired_strategy_comparisons,
)
from gridpool_sim.variance import analyze_variance_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description="Run parameter sweeps for GridPool simulations.")
    parser.add_argument("--sweep", required=True, type=Path, help="Path to a sweep JSON file.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated sweep reports.")
    parser.add_argument("--quick", action="store_true", help="Reduce each variant for a smoke run.")
    parser.add_argument("--jobs", type=int, default=1, help="Number of variants to run concurrently.")
    parser.add_argument("--max-variants", type=int, default=0, help="Optional cap for smoke/debugging.")
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0, help="Progress heartbeat interval.")
    args = parser.parse_args()

    sweep = load_json(args.sweep)
    tasks = build_tasks(sweep, args.quick)
    if args.max_variants > 0:
        tasks = tasks[: args.max_variants]

    if not tasks:
        raise ValueError("Sweep produced no tasks")

    print(f"Running {len(tasks)} variants from {args.sweep}", flush=True)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    started_at = time.monotonic()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_progress(
        args.out_dir,
        sweep=sweep,
        status="running",
        total=len(tasks),
        completed=completed,
        running=[task["variant_label"] for task in tasks[: max(1, args.jobs)]],
        started_at=started_at,
    )
    if args.jobs <= 1:
        try:
            for index, task in enumerate(tasks, start=1):
                print_progress_start(index, len(tasks), task, started_at)
                variant_started_at = time.monotonic()
                variant_rows = run_task(task)
                rows.extend(variant_rows)
                completed.append(completed_variant(task, variant_rows, variant_started_at))
                checkpoint(args.out_dir, sweep, rows, completed, len(tasks), started_at, status="running")
                print_progress_done(index, len(tasks), task, completed[-1], started_at)
        except KeyboardInterrupt:
            checkpoint(args.out_dir, sweep, rows, completed, len(tasks), started_at, status="interrupted")
            print(f"\nInterrupted. Partial outputs are in {args.out_dir}", flush=True)
            return 130
    else:
        executor = ProcessPoolExecutor(max_workers=args.jobs)
        futures = {}
        future_started_at = {}
        interrupted = False
        try:
            for task in tasks:
                future = executor.submit(run_task, task)
                futures[future] = task
                future_started_at[future] = time.monotonic()

            pending = set(futures)
            while pending:
                done, pending = wait(
                    pending,
                    timeout=max(1.0, args.heartbeat_seconds),
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    print_heartbeat(
                        total=len(tasks),
                        completed=completed,
                        pending=[futures[future]["variant_label"] for future in pending],
                        started_at=started_at,
                    )
                    write_progress(
                        args.out_dir,
                        sweep=sweep,
                        status="running",
                        total=len(tasks),
                        completed=completed,
                        running=[futures[future]["variant_label"] for future in pending],
                        started_at=started_at,
                    )
                    continue

                for future in done:
                    task = futures[future]
                    index = len(completed) + 1
                    variant_rows = future.result()
                    rows.extend(variant_rows)
                    completed.append(completed_variant(task, variant_rows, future_started_at[future]))
                    checkpoint(args.out_dir, sweep, rows, completed, len(tasks), started_at, status="running")
                    print_progress_done(index, len(tasks), task, completed[-1], started_at)
        except KeyboardInterrupt:
            interrupted = True
            print("\nInterrupt received; terminating sweep workers...", flush=True)
            for future in futures:
                future.cancel()
            terminate_executor_workers(executor)
            checkpoint(args.out_dir, sweep, rows, completed, len(tasks), started_at, status="interrupted")
            print(f"Interrupted. Partial outputs are in {args.out_dir}", flush=True)
            return 130
        finally:
            executor.shutdown(wait=not interrupted, cancel_futures=interrupted)

    write_sweep_outputs(args.out_dir, sweep, rows)
    write_progress(
        args.out_dir,
        sweep=sweep,
        status="complete",
        total=len(tasks),
        completed=completed,
        running=[],
        started_at=started_at,
    )
    print(f"Wrote sweep report to {args.out_dir / 'report.md'}", flush=True)
    return 0


def print_progress_start(index: int, total: int, task: dict[str, Any], started_at: float) -> None:
    print(
        f"[{index}/{total}] start {task['variant_label']} "
        f"(elapsed {format_duration(time.monotonic() - started_at)})",
        flush=True,
    )


def print_progress_done(
    index: int,
    total: int,
    task: dict[str, Any],
    completed_info: dict[str, Any],
    started_at: float,
) -> None:
    eta = estimate_eta(total=total, completed_count=index, started_at=started_at)
    eta_text = format_duration(eta) if eta is not None else "unknown"
    print(
        f"[{index}/{total}] done {task['variant_label']} "
        f"in {format_duration(float(completed_info['elapsed_seconds']))}; "
        f"rows={completed_info['rows']}; ETA {eta_text}",
        flush=True,
    )


def print_heartbeat(
    *,
    total: int,
    completed: list[dict[str, Any]],
    pending: list[str],
    started_at: float,
) -> None:
    eta = estimate_eta(total=total, completed_count=len(completed), started_at=started_at)
    eta_text = format_duration(eta) if eta is not None else "unknown"
    active_preview = ", ".join(sorted(pending)[:6])
    if len(pending) > 6:
        active_preview += f", +{len(pending) - 6} more"
    print(
        f"[heartbeat] completed {len(completed)}/{total}; "
        f"elapsed {format_duration(time.monotonic() - started_at)}; "
        f"ETA {eta_text}; pending: {active_preview}",
        flush=True,
    )


def completed_variant(
    task: dict[str, Any],
    rows: list[dict[str, Any]],
    started_at: float,
) -> dict[str, Any]:
    return {
        "variant": task["variant_label"],
        "rows": len(rows),
        "elapsed_seconds": time.monotonic() - started_at,
        "completed_at": utc_now(),
    }


def checkpoint(
    out_dir: Path,
    sweep: dict[str, Any],
    rows: list[dict[str, Any]],
    completed: list[dict[str, Any]],
    total: int,
    started_at: float,
    *,
    status: str,
) -> None:
    write_sweep_outputs(out_dir, sweep, rows)
    write_progress(
        out_dir,
        sweep=sweep,
        status=status,
        total=total,
        completed=completed,
        running=[],
        started_at=started_at,
    )


def write_progress(
    out_dir: Path,
    *,
    sweep: dict[str, Any],
    status: str,
    total: int,
    completed: list[dict[str, Any]],
    running: list[str],
    started_at: float,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    elapsed = time.monotonic() - started_at
    eta = estimate_eta(total=total, completed_count=len(completed), started_at=started_at)
    payload = {
        "status": status,
        "sweep": sweep.get("name", "unnamed"),
        "updated_at": utc_now(),
        "total_variants": total,
        "completed_variants": len(completed),
        "remaining_variants": max(0, total - len(completed)),
        "elapsed_seconds": elapsed,
        "eta_seconds": eta,
        "running_variants": sorted(running),
        "completed": completed,
    }
    (out_dir / "progress.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with (out_dir / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def estimate_eta(*, total: int, completed_count: int, started_at: float) -> float | None:
    if completed_count <= 0:
        return None
    remaining = max(0, total - completed_count)
    if remaining == 0:
        return 0.0
    elapsed = time.monotonic() - started_at
    return (elapsed / completed_count) * remaining


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def terminate_executor_workers(executor: ProcessPoolExecutor) -> None:
    processes = getattr(executor, "_processes", None) or {}
    for process in processes.values():
        if process.is_alive():
            process.terminate()
    time.sleep(1)
    for process in processes.values():
        if process.is_alive():
            process.kill()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_tasks(sweep: dict[str, Any], quick: bool) -> list[dict[str, Any]]:
    base_path = Path(sweep["base_scenario"])
    if not base_path.is_absolute():
        base_path = Path.cwd() / base_path
    base_scenario = load_json(base_path)
    for path, value in sweep.get("overrides", {}).items():
        set_path(base_scenario, path, value)

    tasks = []
    for variant in expand_matrix(sweep.get("matrix", [])):
        scenario = copy.deepcopy(base_scenario)
        variant_bits = []
        parameters = {}
        for entry in variant:
            for patch in entry["patches"]:
                set_path(scenario, patch["path"], patch["value"])
            variant_bits.append(f"{entry['name']}={entry['label']}")
            parameters[entry["name"]] = entry["label"]
        if quick:
            scenario = quicken_scenario(sweep["engine"], scenario)
        variant_label = "__".join(variant_bits) if variant_bits else "base"
        scenario["name"] = f"{sweep.get('name', 'sweep')}__{variant_label}"
        tasks.append(
            {
                "engine": sweep["engine"],
                "variant_label": variant_label,
                "parameters": parameters,
                "scenario": scenario,
            }
        )
    return tasks


def expand_matrix(matrix: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not matrix:
        return [[]]

    dimensions = []
    for dimension in matrix:
        values = []
        for raw in dimension["values"]:
            if isinstance(raw, dict) and "patches" in raw:
                label = str(raw.get("label", dimension["name"]))
                patches = [
                    {"path": patch["path"], "value": patch["value"]}
                    for patch in raw["patches"]
                ]
            elif isinstance(raw, dict) and "value" in raw:
                label = str(raw.get("label", raw["value"]))
                patches = [{"path": dimension["path"], "value": raw["value"]}]
            else:
                label = str(raw)
                patches = [{"path": dimension["path"], "value": raw}]
            values.append(
                {
                    "name": dimension["name"],
                    "label": label,
                    "patches": patches,
                }
            )
        dimensions.append(values)
    return [list(combo) for combo in itertools.product(*dimensions)]


def set_path(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cursor: Any = target
    for part in parts[:-1]:
        if isinstance(cursor, list):
            cursor = cursor[int(part)]
        else:
            cursor = cursor.setdefault(part, {})
    leaf = parts[-1]
    if isinstance(cursor, list):
        cursor[int(leaf)] = value
    else:
        cursor[leaf] = value


def quicken_scenario(engine: str, scenario: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(scenario)
    clone["blocks"] = min(int(clone.get("blocks", 500)), 500 if engine != "network" else 250)
    clone["replications"] = min(int(clone.get("replications", 1)), 2)
    clone["shares_per_network_block_at_full_team"] = min(
        float(clone.get("shares_per_network_block_at_full_team", 120)),
        120.0,
    )
    if engine == "network":
        clone["node_count"] = min(int(clone.get("node_count", 12)), 12)
        clone["peer_degree"] = min(int(clone.get("peer_degree", 4)), max(2, clone["node_count"] - 1))
    if engine == "variance":
        clone["miners"] = clone.get("miners", [])[:2]
        clone["team_multipliers"] = [
            value for value in clone.get("team_multipliers", []) if value in {10, 100, 300}
        ]
        clone["total_slots"] = [
            value for value in clone.get("total_slots", []) if value in {30, 300}
        ]
    return clone


def run_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    engine = task["engine"]
    if engine == "economic":
        return run_economic_task(task)
    if engine == "network":
        return run_network_task(task)
    if engine == "adversary":
        return run_adversary_task(task)
    if engine == "variance":
        return run_variance_task(task)
    raise ValueError(f"Unknown sweep engine: {engine}")


def run_economic_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = task["scenario"]
    base_seed = int(scenario.get("random_seed", 256))
    replications = int(scenario.get("replications", 1))
    strategy_runs = scenario.get("strategy_runs") or [
        {"label": "honest", "strategy": {"type": "always"}},
    ]
    results = []
    for strategy_index, strategy_run in enumerate(strategy_runs):
        for replication in range(replications):
            seed = strategy_seed(
                base_seed=base_seed,
                strategy_index=strategy_index,
                replication=replication,
                paired=bool(scenario.get("paired_strategy_seeds", False)),
            )
            results.append(
                GridPoolSimulator(
                    config=scenario,
                    label=strategy_run["label"],
                    seed=seed,
                    strategy=strategy_run.get("strategy", {"type": "always"}),
                ).run()
            )

    aggregate = aggregate_results(results)
    expected = expected_economic_ev(scenario)
    target_share = target_miner_hashrate_share(scenario, str(scenario.get("pool_hopping_target_miner", "hopper_15")))
    economic_context = {
        "param_external_payout_mode": scenario.get("external_payout_mode", "deterministic_fpps"),
        "param_external_fee_rate": scenario.get("external_fee_rate", 0.0),
        "param_fees_btc": scenario.get("fees_btc", 0.0),
        "param_pool_network_share": scenario.get("pool_network_share", 0.0),
        "param_snapshot_policy": scenario.get("snapshot_policy", "paid_once_reserve"),
        "target_miner_hashrate_share": target_share,
        "research_target_hashrate_ph": scenario.get("research_target_hashrate_ph", ""),
        "research_team_hashrate_ph": scenario.get("research_team_hashrate_ph", ""),
    }
    rows = []
    for label, data in aggregate.items():
        for miner_id, miner in data["miners"].items():
            expected_btc = float(expected.get(miner_id, 0.0))
            rows.append(
                base_row(task)
                | economic_context
                | {
                    "result_label": label,
                    "entity_type": "miner",
                    "entity": miner_id,
                    "metric_primary": miner["mean_total_btc"] / expected_btc if expected_btc > 0 else 0.0,
                    "metric_primary_name": "ev_ratio",
                    "mean_btc": miner["mean_total_btc"],
                    "std_btc": miner["std_total_btc"],
                    "sample_std_btc": miner["sample_std_total_btc"],
                    "stderr_btc": miner["stderr_total_btc"],
                    "ci95_btc_low": miner["ci95_total_btc_low"],
                    "ci95_btc_high": miner["ci95_total_btc_high"],
                    "mean_shared_slots_paid": miner["mean_shared_slots_paid"],
                    "mean_shared_payout_events": miner["mean_shared_payout_events"],
                    "mean_slot0_payout_events": miner["mean_slot0_payout_events"],
                    "mean_pool_blocks": data["mean_pool_blocks"],
                    "mean_inactive_snapshot_slots": data.get("mean_inactive_snapshot_slots", 0.0),
                    "mean_inactive_snapshot_fraction": data.get("mean_inactive_snapshot_fraction", 0.0),
                    "mean_inactive_work_set_proofs": data.get("mean_inactive_work_set_proofs", 0.0),
                    "mean_inactive_work_set_fraction": data.get("mean_inactive_work_set_fraction", 0.0),
                    "mean_active_team_hashrate_share": data.get("mean_active_team_hashrate_share", 1.0),
                    "mean_block_finds": miner["mean_block_finds"],
                    "mean_withheld_blocks": miner.get("mean_withheld_blocks", 0.0),
                    "mean_external_btc": miner["mean_external_btc"],
                }
            )
    paired = paired_strategy_comparisons(scenario, results, expected)
    for label, comparison in paired.get("comparisons", {}).items():
        for miner_id, miner in comparison["miners"].items():
            rows.append(
                base_row(task)
                | economic_context
                | {
                    "result_label": label,
                    "entity_type": "paired_delta",
                    "entity": miner_id,
                    "metric_primary": miner["delta_ev_ratio"]["mean"],
                    "metric_primary_name": "paired_delta_ev_ratio",
                    "paired_baseline": paired["baseline_label"],
                    "paired_n": miner["delta_total_btc"]["n"],
                    "mean_delta_btc": miner["delta_total_btc"]["mean"],
                    "ci95_delta_btc_low": miner["delta_total_btc"]["ci95_low"],
                    "ci95_delta_btc_high": miner["delta_total_btc"]["ci95_high"],
                    "mean_delta_ev_ratio": miner["delta_ev_ratio"]["mean"],
                    "ci95_delta_ev_ratio_low": miner["delta_ev_ratio"]["ci95_low"],
                    "ci95_delta_ev_ratio_high": miner["delta_ev_ratio"]["ci95_high"],
                    "mean_delta_shared_slots_paid": miner["delta_shared_slots_paid"]["mean"],
                    "mean_delta_shared_payout_events": miner["delta_shared_payout_events"]["mean"],
                }
            )
    return rows


def target_miner_hashrate_share(scenario: dict[str, Any], target_miner: str) -> float:
    miners = scenario.get("miners", [])
    total = sum(float(miner.get("hashrate", 0.0)) for miner in miners)
    if total <= 0:
        return 0.0
    target = sum(
        float(miner.get("hashrate", 0.0))
        for miner in miners
        if miner.get("id") == target_miner
    )
    return target / total


def run_variance_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result in analyze_variance_scenario(task["scenario"]):
        rows.append(
            base_row(task)
            | {
                "result_label": "gridpool_vs_solo_fpps",
                "entity_type": "miner",
                "entity": result.miner_id,
                "metric_primary": result.grid_variance_reduction_vs_solo,
                "metric_primary_name": "variance_reduction_vs_solo",
                "miner_hashrate_eh": result.miner_hashrate_eh,
                "expected_solo_blocks": result.expected_solo_blocks,
                "team_multiplier": result.team_multiplier,
                "team_network_share": result.team_network_share,
                "team_expected_blocks": result.team_expected_blocks,
                "total_slots": result.total_slots,
                "shared_slots": result.shared_slots,
                "expected_slots_per_team_block": result.expected_slots_per_team_block,
                "expected_shared_slots_per_period": result.expected_shared_slots_per_period,
                "probability_zero_shared_slots": result.probability_zero_shared_slots,
                "probability_zero_grid_payout": result.probability_zero_grid_payout,
                "solo_mean_btc": result.solo_mean_btc,
                "solo_std_btc": result.solo_std_btc,
                "solo_cv": result.solo_cv,
                "solo_probability_zero_payout": result.solo_probability_zero_payout,
                "fpps_mean_btc": result.fpps_mean_btc,
                "fpps_std_btc": result.fpps_std_btc,
                "fpps_cv": result.fpps_cv,
                "grid_mean_btc": result.grid_mean_btc,
                "grid_std_btc": result.grid_std_btc,
                "grid_cv": result.grid_cv,
                "grid_cv_reduction_vs_solo": result.grid_cv_reduction_vs_solo,
                "grid_effective_independent_payout_units": result.grid_effective_independent_payout_units,
            }
        )
    return rows


def run_network_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = task["scenario"]
    base_seed = int(scenario.get("random_seed", 1024))
    replications = int(scenario.get("replications", 1))
    results = []
    for profile_index, profile in enumerate(relay_profiles_from_config(scenario)):
        for replication in range(replications):
            seed = base_seed + (profile_index * 100_000) + replication
            results.append(NetworkLatencySimulator(scenario, profile, seed).run())

    aggregate = aggregate_latency_results(results)
    rows = []
    for label, data in aggregate.items():
        rows.append(
            base_row(task)
            | {
                "result_label": label,
                "entity_type": "relay_profile",
                "entity": label,
                "metric_primary": data["mean_split_rate"],
                "metric_primary_name": "split_rate",
                "mean_split_rate": data["mean_split_rate"],
                "mean_unique_snapshots": data["mean_unique_snapshots"],
                "mean_hashrate_on_canonical": data["mean_hashrate_on_canonical"],
                    "mean_p95_convergence_seconds": data["mean_p95_convergence_seconds"],
                    "mean_estimated_payload_mb": data["mean_estimated_payload_mb"],
                    "blocks": scenario.get("blocks"),
                    "block_interval_seconds": scenario.get("block_interval_seconds"),
                    "share_mean_ms": next(
                        (
                            profile.get("share_mean_ms")
                            for profile in scenario.get("relay_profiles", [])
                            if profile.get("label") == label
                        ),
                        "",
                    ),
                    "share_jitter_ms": next(
                        (
                            profile.get("share_jitter_ms", 0.0)
                            for profile in scenario.get("relay_profiles", [])
                            if profile.get("label") == label
                        ),
                        "",
                    ),
                    "block_mean_ms": next(
                        (
                            profile.get("block_mean_ms", scenario.get("block_mean_ms", 500.0))
                            for profile in scenario.get("relay_profiles", [])
                            if profile.get("label") == label
                        ),
                        "",
                    ),
                }
            )
    return rows


def run_adversary_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = task["scenario"]
    base_seed = int(scenario.get("random_seed", 1536))
    replications = int(scenario.get("replications", 1))
    strategy_runs = scenario.get("strategy_runs") or [
        {"label": "honest_single_team", "strategy": {"mode": "honest_single_team"}},
    ]
    results = []
    for strategy_index, strategy_run in enumerate(strategy_runs):
        for replication in range(replications):
            seed = strategy_seed(
                base_seed=base_seed,
                strategy_index=strategy_index,
                replication=replication,
                paired=bool(scenario.get("paired_strategy_seeds", False)),
            )
            results.append(
                MajorityAdversarySimulator(
                    config=scenario,
                    label=strategy_run["label"],
                    seed=seed,
                    strategy=strategy_run.get("strategy", {"mode": "honest_single_team"}),
                ).run()
            )

    aggregate = aggregate_adversary_results(results)
    expected = expected_adversary_ev(scenario)
    rows = []
    for label, data in aggregate.items():
        for miner_id, miner in data["miners"].items():
            expected_btc = float(expected.get(miner_id, 0.0))
            rows.append(
                base_row(task)
                | {
                    "result_label": label,
                    "entity_type": "miner",
                    "entity": miner_id,
                    "role": miner["role"],
                    "metric_primary": miner["mean_btc"] / expected_btc if expected_btc > 0 else 0.0,
                    "metric_primary_name": "ev_ratio",
                    "mean_btc": miner["mean_btc"],
                    "std_btc": miner["std_btc"],
                    "mean_block_finds": miner["mean_block_finds"],
                    "mean_shares_rejected_by_team": miner["mean_shares_rejected_by_team"],
                    "mean_snapshot_slot_observations": miner["mean_snapshot_slot_observations"],
                }
            )
        for team_id, team in data["teams"].items():
            rows.append(
                base_row(task)
                | {
                    "result_label": label,
                    "entity_type": "team",
                    "entity": team_id,
                    "metric_primary": team["mean_blocks_won"],
                    "metric_primary_name": "mean_blocks_won",
                    "mean_blocks_won": team["mean_blocks_won"],
                    "mean_final_work_set_count": team["mean_final_work_set_count"],
                }
            )
    return rows


def base_row(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": task["engine"],
        "variant": task["variant_label"],
        **{f"param_{key}": value for key, value in task["parameters"].items()},
    }


def strategy_seed(*, base_seed: int, strategy_index: int, replication: int, paired: bool) -> int:
    if paired:
        return base_seed + replication
    return base_seed + (strategy_index * 100_000) + replication


def write_sweep_outputs(out_dir: Path, sweep: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        rows,
        key=lambda row: (
            row.get("variant", ""),
            row.get("result_label", ""),
            row.get("entity_type", ""),
            row.get("entity", ""),
        ),
    )
    (out_dir / "summary.json").write_text(
        json.dumps({"sweep": sweep, "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_sweep_csv(out_dir / "sweep_results.csv", rows)
    write_sweep_markdown(out_dir / "report.md", sweep, rows)


def write_sweep_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    preferred = [
        "engine",
        "variant",
        "result_label",
        "entity_type",
        "entity",
        "role",
        "metric_primary_name",
        "metric_primary",
    ]
    ordered = [field for field in preferred if field in fieldnames] + [
        field for field in fieldnames if field not in preferred
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def write_sweep_markdown(path: Path, sweep: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = []
    lines.append(f"# GridPool Sweep Report: {sweep.get('name', 'unnamed')}")
    lines.append("")
    lines.append("Status: generated by `run_sweep.py`.")
    lines.append("")
    lines.append(f"- Engine: `{sweep['engine']}`")
    lines.append(f"- Variants: `{len({row['variant'] for row in rows})}`")
    lines.append(f"- Rows: `{len(rows)}`")
    lines.append("")
    lines.append("## Primary Metrics")
    lines.append("")
    lines.append("| Variant | Label | Entity | Primary Metric | Value |")
    lines.append("| --- | --- | --- | --- | ---: |")
    for row in rows[:500]:
        lines.append(
            "| {variant} | {label} | `{entity}` | `{metric}` | {value:.8f} |".format(
                variant=row.get("variant", ""),
                label=row.get("result_label", ""),
                entity=row.get("entity", ""),
                metric=row.get("metric_primary_name", ""),
                value=float(row.get("metric_primary", 0.0)),
            )
        )
    if len(rows) > 500:
        lines.append(f"| ... | ... | ... | ... | {len(rows) - 500} more rows in CSV |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Use `sweep_results.csv` for analysis and plotting.")
    lines.append("- Generated reports are ignored by git; promote reviewed reports manually if they support a public claim.")
    lines.append("- For long runs, prefer `--jobs N` with a sensible value for the local CPU.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

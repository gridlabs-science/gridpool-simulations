#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.engine import GridPoolSimulator
from gridpool_sim.reporting import write_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic GridPool research simulations.")
    parser.add_argument("--scenario", required=True, type=Path, help="Path to a JSON scenario file.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated reports.")
    parser.add_argument("--quick", action="store_true", help="Reduce blocks and replications for a smoke run.")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.quick:
        scenario = quicken(scenario)

    base_seed = int(scenario.get("random_seed", 256))
    replications = int(scenario.get("replications", 1))
    strategy_runs = scenario.get("strategy_runs") or [
        {"label": "honest", "strategy": {"type": "always"}},
    ]

    results = []
    for strategy_index, strategy_run in enumerate(strategy_runs):
        label = strategy_run["label"]
        strategy = strategy_run.get("strategy", {"type": "always"})
        for replication in range(replications):
            seed = strategy_seed(
                base_seed=base_seed,
                strategy_index=strategy_index,
                replication=replication,
                paired=bool(scenario.get("paired_strategy_seeds", False)),
            )
            simulator = GridPoolSimulator(
                config=scenario,
                label=label,
                seed=seed,
                strategy=strategy,
            )
            results.append(simulator.run())

    write_reports(args.out_dir, scenario, results)
    print(f"Wrote simulation report to {args.out_dir / 'report.md'}")
    return 0


def quicken(scenario: dict) -> dict:
    clone = copy.deepcopy(scenario)
    clone["name"] = f"{clone.get('name', 'scenario')}_quick"
    clone["blocks"] = min(int(clone.get("blocks", 500)), 500)
    clone["replications"] = min(int(clone.get("replications", 1)), 2)
    clone["shares_per_network_block_at_full_team"] = min(
        float(clone.get("shares_per_network_block_at_full_team", 120)),
        120.0,
    )
    return clone


def strategy_seed(*, base_seed: int, strategy_index: int, replication: int, paired: bool) -> int:
    if paired:
        return base_seed + replication
    return base_seed + (strategy_index * 100_000) + replication


if __name__ == "__main__":
    raise SystemExit(main())
